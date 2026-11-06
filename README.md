# AI-Based Test Automation Using Playwright and Gemini

## Project Overview

This project was developed as part of an internship technical assessment. It uses Google Gemini AI and Playwright to convert plain-English testing instructions into automated browser actions.

## Objective

To build an AI-assisted automation system that understands test instructions, interacts with websites and verifies expected results.

## Technologies Used

- Python
- Playwright
- Google Gemini API
- python-dotenv

## Key Features

- Accepts test cases in plain English.
- Uses Gemini to plan browser actions.
- Identifies visible website elements.
- Executes browser actions using Playwright.
- Supports text and URL verification.
- Generates JSON test reports.
- Captures screenshots when a test fails.

## Installation

Install dependencies:

`pip install -r requirements.txt`

Install the browser:

`playwright install chromium`

## Configuration

Create a `.env` file:

`GEMINI_API_KEY=YOUR_API_KEY`

Never upload your API key to GitHub.

## Run the Project

`python main.py`

Enter the website URL and a test instruction when prompted.

## Example Test Case

"Open the website and verify that the login page is displayed."

## Limitations

- AI may misunderstand complex instructions.
- CAPTCHA and multi-factor authentication are not automatically handled.
- Custom website controls may require additional locator strategies.
- Test execution depends on website availability and structure.

## Author

Omkar Sathe

B.Sc. Computer Science Student
