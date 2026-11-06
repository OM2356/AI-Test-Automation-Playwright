
import os
import json
import re
from datetime import datetime
from urllib.parse import urlparse

from dotenv import load_dotenv
from google import genai
from google.genai import types
from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError
)


# ------------------------------------------
# CONFIGURATION
# ------------------------------------------

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

if not API_KEY:
    raise ValueError(
        "Gemini API key missing. Add GEMINI_API_KEY to your .env file."
    )

client = genai.Client(api_key=API_KEY)

MAX_STEPS = 15
ACTION_TIMEOUT = 10000

os.makedirs("screenshots", exist_ok=True)
os.makedirs("reports", exist_ok=True)


# ------------------------------------------
# GET VISIBLE WEBSITE ELEMENTS
# ------------------------------------------

def get_page_elements(page):

    return page.evaluate("""
    () => {
        const elements = Array.from(
            document.querySelectorAll(
                'input, textarea, select, button, a, [role="button"], [role="link"]'
            )
        );

        const results = [];

        elements.forEach((element, index) => {

            const style = window.getComputedStyle(element);
            const rect = element.getBoundingClientRect();

            const visible =
                style.display !== 'none' &&
                style.visibility !== 'hidden' &&
                rect.width > 0 &&
                rect.height > 0;

            if (!visible || element.disabled) {
                return;
            }

            const labels = Array.from(element.labels || [])
                .map(label => label.innerText || label.textContent || '')
                .join(' ')
                .trim();

            const role =
                element.getAttribute('role') ||
                element.tagName.toLowerCase();

            const text = (
                element.innerText ||
                element.textContent ||
                ''
            ).trim().replace(/\\s+/g, ' ');

            const info = {
                ref: 'ai-' + index,
                tag: element.tagName.toLowerCase(),
                role: role,
                type: element.type || '',
                text: text.slice(0, 150),
                label: labels,
                placeholder: element.getAttribute('placeholder') || '',
                aria_label: element.getAttribute('aria-label') || '',
                name: element.getAttribute('name') || '',
                value: element.value || '',
                options: element.tagName === 'SELECT'
                    ? Array.from(element.options).map(o => ({
                        text: o.text.trim(),
                        value: o.value
                    }))
                    : []
            };

            element.setAttribute('data-ai-ref', info.ref);

            results.push(info);
        });

        return results;
    }
    """)


# ------------------------------------------
# GET WEBSITE INFORMATION
# ------------------------------------------

def get_page_information(page):

    try:
        page_text = page.locator("body").inner_text(timeout=5000)
    except PlaywrightTimeoutError:
        page_text = ""

    elements = get_page_elements(page)

    return {
        "url": page.url,
        "title": page.title(),
        "page_text": page_text[:5000],
        "elements": elements
    }


# ------------------------------------------
# ASK GEMINI FOR NEXT ACTION
# ------------------------------------------

def ask_gemini(test_case, website_info, history):

    prompt = f"""
You are an intelligent browser testing assistant.

Your job is to execute a user's test case using browser actions.

USER TEST CASE:
{test_case}

CURRENT WEBSITE INFORMATION:
{json.dumps(website_info, ensure_ascii=False)}

PREVIOUS ACTIONS:
{json.dumps(history, ensure_ascii=False)}

Choose ONLY ONE next action.

AVAILABLE ACTIONS:

1. fill
   Use a visible input or textarea.
   Required: ref, value.

2. click
   Click a visible button, link, or interactive element.
   Required: ref.

3. select
   Select a dropdown option.
   Required: ref, value.
   Value should match an available option's text or value.

4. check
   Check a checkbox.
   Required: ref.

5. uncheck
   Uncheck a checkbox.
   Required: ref.

6. verify_text
   Verify that text is present on the page.
   Required: value.

7. verify_url
   Verify that the current URL contains a specified string.
   Required: value.

8. done
   Use only after all requested actions and verifications succeed.
   Required: summary.

9. fail
   Use when the requested test cannot be completed.
   Required: reason.

RULES:

- Use only element references that exist in CURRENT WEBSITE INFORMATION.
- Never invent element references.
- Never invent passwords, usernames, or other credentials.
- If login details are missing, return fail.
- Never submit payment or perform destructive actions.
- Never execute JavaScript, Python, shell commands, or arbitrary code.
- Never access unrelated websites.
- Do not claim a test passed without checking the expected result.
- Use verify_text or verify_url for explicit verification.
- Perform one action at a time.
- If an action has already succeeded, do not repeat it unnecessarily.
- If an element cannot be identified, return fail.
- Return valid JSON only.

OUTPUT FORMAT:

{{
    "action": "click",
    "ref": "ai-1",
    "value": "",
    "summary": "",
    "reason": ""
}}
"""

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.1
        )
    )

    result = json.loads(response.text)

    if not isinstance(result, dict):
        raise ValueError("Gemini returned an invalid action.")

    return result


# ------------------------------------------
# VALIDATE AI ACTION
# ------------------------------------------

def validate_action(action, website_info):

    allowed_actions = {
        "fill",
        "click",
        "select",
        "check",
        "uncheck",
        "verify_text",
        "verify_url",
        "done",
        "fail"
    }

    action_type = action.get("action")

    if action_type not in allowed_actions:
        raise ValueError("Unsupported action received from AI.")

    if action_type in {
        "fill", "click", "select", "check", "uncheck"
    }:

        ref = action.get("ref")

        available_refs = {
            element["ref"]
            for element in website_info["elements"]
        }

        if ref not in available_refs:
            raise ValueError(
                "AI selected an element that does not exist."
            )


# ------------------------------------------
# EXECUTE BROWSER ACTION
# ------------------------------------------

def execute_action(page, action):

    action_type = action["action"]

    if action_type in {
        "verify_text", "verify_url", "done", "fail"
    }:
        return

    ref = action["ref"]

    locator = page.locator(
        f'[data-ai-ref="{ref}"]'
    )

    locator.wait_for(
        state="visible",
        timeout=ACTION_TIMEOUT
    )

    if action_type == "fill":

        if locator.evaluate(
            "(e) => !['INPUT', 'TEXTAREA'].includes(e.tagName)"
        ):
            raise ValueError(
                "Fill is allowed only for inputs and textareas."
            )

        locator.fill(str(action.get("value", "")))

    elif action_type == "click":

        locator.click(timeout=ACTION_TIMEOUT)

    elif action_type == "select":

        if locator.evaluate(
            "(e) => e.tagName !== 'SELECT'"
        ):
            raise ValueError(
                "Select is allowed only for HTML dropdowns."
            )

        value = str(action.get("value", ""))

        try:
            locator.select_option(label=value)
        except Exception:
            locator.select_option(value=value)

    elif action_type == "check":

        locator.check(timeout=ACTION_TIMEOUT)

    elif action_type == "uncheck":

        locator.uncheck(timeout=ACTION_TIMEOUT)


# ------------------------------------------
# VERIFY EXPECTED RESULT
# ------------------------------------------

def verify_action(page, action):

    action_type = action["action"]

    if action_type == "verify_text":

        expected_text = str(action.get("value", ""))

        if not expected_text.strip():
            raise ValueError("Verification text is empty.")

        if not page.get_by_text(
            expected_text,
            exact=False
        ).first.is_visible(timeout=5000):
            raise AssertionError(
                f"Expected text not found: {expected_text}"
            )

        return True

    if action_type == "verify_url":

        expected_url = str(action.get("value", ""))

        if not expected_url:
            raise ValueError("Expected URL is empty.")

        if expected_url.lower() not in page.url.lower():
            raise AssertionError(
                f"Expected URL part not found: {expected_url}"
            )

        return True

    return False


# ------------------------------------------
# SAVE TEST REPORT
# ------------------------------------------

def save_report(result, test_case, history, error=None):

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    report = {
        "test_case": test_case,
        "status": result,
        "steps": history,
        "error": error,
        "created_at": datetime.now().isoformat()
    }

    filename = f"reports/report_{timestamp}.json"

    with open(filename, "w", encoding="utf-8") as file:
        json.dump(
            report,
            file,
            indent=4,
            ensure_ascii=False
        )

    print(f"Report saved: {filename}")


# ------------------------------------------
# MAIN AUTOMATION ENGINE
# ------------------------------------------

def run_test():

    print("\n================================")
    print(" AI-BASED TEST AUTOMATION SYSTEM")
    print("================================\n")

    website_url = input(
        "Enter website URL: "
    ).strip()

    test_case = input(
        "Enter test case in plain English: "
    ).strip()

    if not website_url or not test_case:
        print("Website URL and test case are required.")
        return

    parsed_url = urlparse(website_url)

    if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
        print("Please enter a valid HTTP or HTTPS website URL.")
        return

    history = []
    verification_count = 0
    status = "FAIL"
    error_message = None
    page = None

    with sync_playwright() as playwright:

        browser = playwright.chromium.launch(
            headless=False
        )

        page = browser.new_page()

        page.set_default_timeout(ACTION_TIMEOUT)

        try:

            print("\nOpening website...")

            page.goto(
                website_url,
                wait_until="domcontentloaded",
                timeout=30000
            )

            for step_number in range(1, MAX_STEPS + 1):

                print(f"\nAI planning step {step_number}...")

                website_info = get_page_information(page)

                action = ask_gemini(
                    test_case,
                    website_info,
                    history
                )

                validate_action(action, website_info)

                action_type = action["action"]

                print("AI action:", action_type)

                if action_type == "fail":

                    raise Exception(
                        action.get("reason", "AI could not complete the test.")
                    )

                if action_type == "done":

                    if verification_count == 0:
                        raise Exception(
                            "No verification was performed. "
                            "A test cannot pass without an assertion."
                        )

                    status = "PASS"

                    history.append({
                        "step": step_number,
                        "action": "done",
                        "summary": action.get("summary", "")
                    })

                    break

                if action_type in {"verify_text", "verify_url"}:

                    verify_action(page, action)
                    verification_count += 1

                    history.append({
                        "step": step_number,
                        "action": action_type,
                        "value": action.get("value"),
                        "result": "PASS"
                    })

                else:

                    execute_action(page, action)

                    history.append({
                        "step": step_number,
                        "action": action_type,
                        "ref": action.get("ref"),
                        "value": action.get("value"),
                        "result": "EXECUTED"
                    })

                print("Action completed.")

            else:

                raise Exception(
                    "Maximum AI action limit reached."
                )

        except Exception as error:

            error_message = str(error)

            print("\nTEST FAILED:", error_message)

            if page and not page.is_closed():

                try:
                    timestamp = datetime.now().strftime(
                        "%Y%m%d_%H%M%S"
                    )

                    screenshot_path = (
                        f"screenshots/failure_{timestamp}.png"
                    )

                    page.screenshot(
                        path=screenshot_path,
                        full_page=True
                    )

                    print(
                        "Failure screenshot:",
                        screenshot_path
                    )

                except Exception:
                    print("Could not save failure screenshot.")

        finally:

            save_report(
                status,
                test_case,
                history,
                error_message
            )

            print("\n================================")
            print("FINAL RESULT:", status)
            print("================================")

            browser.close()


# ------------------------------------------
# START PROGRAM
# ------------------------------------------

if __name__ == "__main__":
    try:
        run_test()

    except KeyboardInterrupt:
        print("\nAutomation stopped by user.")

    except Exception as error:
        print("\nSYSTEM ERROR:", error)
