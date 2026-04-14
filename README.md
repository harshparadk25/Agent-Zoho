# Zoho CRM MCP Multi-Tool Agent

A Python CLI agent built with Google ADK that translates natural language into Zoho CRM CRUD operations through an MCP endpoint.

## Executive Summary

This project provides a single conversational interface for CRM operations:
- Create records
- Read/search records
- Update records
- Delete records

The runtime agent uses Gemini for intent detection and argument extraction, then calls one of four tool functions that communicate with the Zoho MCP endpoint.

## Quick Review

Current strengths:
- Clear separation of concerns between agent orchestration, prompt policy, and tool execution.
- Strong input validation for JSON arguments in create and update flows.
- Centralized error normalization for API and network failures.
- Token refresh logic with in-memory caching for Zoho OAuth.
- Model fallback strategy when a requested Gemini model is unavailable.
- Environment variables are loaded before tool imports, preventing stale env-backed constants.

Current gaps and recommended next steps:
- No automated tests yet.
- No dependency lock file or requirements file yet.
- No CI checks for linting and tests yet.
- No retries or backoff beyond a single 401 refresh retry.

## Project Layout

- multi_tool_agent/agent.py: CLI entrypoint, ADK agent setup, model resolution, session runner, terminal output.
- multi_tool_agent/tools.py: MCP transport, OAuth token refresh/cache, CRUD tool implementations.
- multi_tool_agent/prompts.py: System prompt and response contract.
- multi_tool_agent/__init__.py: Package marker.
- .gitignore: Excludes local env, virtual env, caches, and editor artifacts.

## Architecture

1. User types a natural-language request in CLI.
2. ADK agent decides one CRUD tool to call.
3. Tool validates input and sends payload to MCP endpoint.
4. Tool returns normalized success or error object.
5. Agent returns final model response text to terminal.

## Prerequisites

- Python 3.10 or newer
- A Google API key with access to Gemini models
- Zoho MCP endpoint access
- Optional: Zoho OAuth client credentials for direct token refresh flow

## Installation

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install google-adk google-genai python-dotenv requests
```

## Configuration

Create a .env file inside multi_tool_agent/ with the variables below.

Required:
- GOOGLE_API_KEY: Gemini API key

Optional runtime settings:
- GEMINI_MODEL: Requested Gemini model name (default: gemini-1.5-flash)
- LOG_LEVEL: DEBUG, INFO, WARNING, ERROR (default: INFO)

Optional MCP and Zoho settings:
- ZOHO_MCP_ENDPOINT: MCP message endpoint URL
- MCP_TIMEOUT_SECONDS: Request timeout in seconds (default: 30)
- ZOHO_API_DOMAIN: Zoho API domain (default: https://www.zohoapis.in)
- ZOHO_ACCOUNTS_URL: Zoho Accounts URL (default: https://accounts.zoho.in)
- ZOHO_CLIENT_ID: Zoho OAuth client id
- ZOHO_CLIENT_SECRET: Zoho OAuth client secret
- ZOHO_REFRESH_TOKEN: Zoho OAuth refresh token

If Zoho OAuth variables are present, the tool layer will automatically refresh and attach access tokens.

## Run

From repository root:

```powershell
python -m multi_tool_agent.agent
```

Alternative:

```powershell
python multi_tool_agent/agent.py
```

## Example Requests

- Create a lead named Arjun Mehta with email arjun.mehta@example.com and phone 123-456-7890
- Find records for Arjun Mehta
- Update record 64543997854 and set email to arjun.new@example.com
- Delete record 64543997854

## Response Behavior

- On success, terminal prints the agent response string directly.
- On failure, terminal prints a structured JSON error object with success=false and message.

The model is instructed to return a JSON object in text form with keys:
- status
- action
- summary
- tool_response

## Error Handling Notes

Tool layer handles:
- Invalid input validation errors
- Network exceptions
- Non-JSON API responses
- HTTP errors with status code and response detail
- One retry flow after 401 with forced token refresh

## Security Notes

- Never commit real .env secrets.
- .gitignore already excludes .env, .env.*, and .venv.
- Rotate API keys and refresh tokens if exposed.

## Push Checklist

1. Confirm .env is not tracked.
2. Confirm .venv is not tracked.
3. Run the agent once to validate startup.
4. Review staged files.
5. Commit and push.

Useful commands:

```powershell
git status
git add .
git commit -m "Add README and project docs"
git push
```

## Suggested Improvements

1. Add requirements.txt or pyproject.toml for reproducible installs.
2. Add unit tests for input parsing and MCP error normalization.
3. Add integration tests with mocked MCP responses.
4. Add structured logging context fields (action, request_id).
5. Add CI pipeline for lint and tests.
