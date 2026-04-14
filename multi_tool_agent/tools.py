"""Tool functions for Zoho CRM CRUD operations through MCP."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import requests
from requests import Response
from requests.exceptions import RequestException

LOGGER = logging.getLogger(__name__)

MCP_ENDPOINT = os.getenv(
    "ZOHO_MCP_ENDPOINT",
    "https://nawabmcp-60069769339.zohomcp.in/mcp/cb77ed77d47f94f3ed4fe18b7fda88c4/message",
)
MCP_TIMEOUT_SECONDS = int(os.getenv("MCP_TIMEOUT_SECONDS", "30"))
ZOHO_API_DOMAIN = os.getenv("ZOHO_API_DOMAIN", "https://www.zohoapis.in").rstrip("/")
ZOHO_ACCOUNTS_URL = os.getenv("ZOHO_ACCOUNTS_URL", "https://accounts.zoho.in").rstrip("/")
ZOHO_CLIENT_ID = os.getenv("ZOHO_CLIENT_ID", "").strip()
ZOHO_CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET", "").strip()
ZOHO_REFRESH_TOKEN = os.getenv("ZOHO_REFRESH_TOKEN", "").strip()

_ACCESS_TOKEN_CACHE: dict[str, Any] = {"token": None, "expires_at": 0.0}


def _build_error(
    action: str,
    message: str,
    *,
    status_code: int | None = None,
    raw_response: Any | None = None,
) -> dict[str, Any]:
    """Return a normalized error payload for tool responses."""
    payload: dict[str, Any] = {
        "success": False,
        "action": action,
        "message": message,
        "status_code": status_code,
    }
    if raw_response is not None:
        payload["raw_response"] = raw_response
    return payload


def _parse_json_response(response: Response) -> Any | None:
    """Parse JSON safely and return None when response is not valid JSON."""
    try:
        return response.json()
    except ValueError:
        return None


def _parse_json_object_input(action: str, field_name: str, raw_value: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Parse a JSON-object argument passed as text and validate it."""
    if isinstance(raw_value, dict):
        if not raw_value:
            return None, _build_error(
                action,
                f"Invalid input: '{field_name}' must be a non-empty object.",
            )
        return raw_value, None

    if not isinstance(raw_value, str):
        return None, _build_error(
            action,
            f"Invalid input: '{field_name}' must be a JSON object string.",
        )

    normalized_value = raw_value.strip()
    if not normalized_value:
        return None, _build_error(
            action,
            f"Invalid input: '{field_name}' must be a non-empty JSON object string.",
        )

    try:
        parsed = json.loads(normalized_value)
    except json.JSONDecodeError as exc:
        return None, _build_error(
            action,
            f"Invalid input: '{field_name}' is not valid JSON ({exc.msg}).",
        )

    if not isinstance(parsed, dict) or not parsed:
        return None, _build_error(
            action,
            f"Invalid input: '{field_name}' must decode to a non-empty JSON object.",
        )

    return parsed, None


def _is_zoho_oauth_configured() -> bool:
    """Return whether all required Zoho OAuth environment values are present."""
    return all([ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN])


def _extract_token_expiry_seconds(token_payload: dict[str, Any]) -> int:
    """Read token expiry from Zoho token response with a safe default."""
    for key in ("expires_in_sec", "expires_in"):
        value = token_payload.get(key)
        if isinstance(value, int):
            return max(value, 60)
        if isinstance(value, str) and value.isdigit():
            return max(int(value), 60)
    return 3500


def _refresh_zoho_access_token() -> tuple[str | None, str | None]:
    """Refresh Zoho OAuth access token using refresh token flow."""
    if not _is_zoho_oauth_configured():
        return None, None

    token_url = f"{ZOHO_ACCOUNTS_URL}/oauth/v2/token"
    form_data = {
        "refresh_token": ZOHO_REFRESH_TOKEN,
        "client_id": ZOHO_CLIENT_ID,
        "client_secret": ZOHO_CLIENT_SECRET,
        "grant_type": "refresh_token",
    }

    try:
        response = requests.post(
            token_url,
            data=form_data,
            timeout=MCP_TIMEOUT_SECONDS,
        )
    except RequestException as exc:
        LOGGER.exception("Zoho token refresh request failed")
        return None, f"Unable to refresh Zoho access token: {exc}"

    parsed = _parse_json_response(response)

    if response.status_code >= 400:
        detail = ""
        if isinstance(parsed, dict):
            detail = str(parsed.get("error_description") or parsed.get("error") or "").strip()
        if not detail:
            detail = response.text.strip()[:500]
        message = f"Unable to refresh Zoho access token (HTTP {response.status_code})."
        if detail:
            message = f"{message} {detail}"
        return None, message

    if not isinstance(parsed, dict):
        return None, "Zoho token refresh returned a non-JSON response."

    access_token = str(parsed.get("access_token") or "").strip()
    if not access_token:
        return None, "Zoho token refresh did not return access_token."

    expires_in = _extract_token_expiry_seconds(parsed)
    _ACCESS_TOKEN_CACHE["token"] = access_token
    _ACCESS_TOKEN_CACHE["expires_at"] = time.time() + max(expires_in - 30, 30)

    LOGGER.info("Zoho OAuth access token refreshed successfully")
    return access_token, None


def _get_zoho_access_token(force_refresh: bool = False) -> tuple[str | None, str | None]:
    """Get a valid Zoho access token from cache or refresh endpoint."""
    if not _is_zoho_oauth_configured():
        return None, None

    cached_token = _ACCESS_TOKEN_CACHE.get("token")
    cached_expiry = float(_ACCESS_TOKEN_CACHE.get("expires_at") or 0)

    if not force_refresh and cached_token and time.time() < cached_expiry:
        return str(cached_token), None

    return _refresh_zoho_access_token()


def _build_mcp_headers(force_refresh: bool = False) -> tuple[dict[str, str], str | None]:
    """Build MCP request headers and attach Zoho auth when configured."""
    headers: dict[str, str] = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    access_token, token_error = _get_zoho_access_token(force_refresh=force_refresh)
    if token_error:
        return headers, token_error

    if access_token:
        headers["Authorization"] = f"Zoho-oauthtoken {access_token}"
        headers["X-ZOHO-API-DOMAIN"] = ZOHO_API_DOMAIN

    return headers, None


def _send_mcp_request(payload: dict[str, Any], headers: dict[str, str]) -> Response:
    """Send the MCP request with prepared headers."""
    return requests.post(
        MCP_ENDPOINT,
        json=payload,
        headers=headers,
        timeout=MCP_TIMEOUT_SECONDS,
    )


def _post_to_mcp(action: str, data: dict[str, Any]) -> dict[str, Any]:
    """Send a standardized MCP request and normalize the response."""
    payload = {
        "action": action,
        "module": "crm",
        "data": data,
    }

    LOGGER.info("MCP call started: action=%s", action)

    headers, token_error = _build_mcp_headers()
    if token_error:
        LOGGER.error("Zoho auth preparation failed for action=%s", action)
        return _build_error(action, token_error)

    try:
        response = _send_mcp_request(payload, headers)
    except RequestException as exc:
        LOGGER.exception("MCP request failed for action=%s", action)
        return _build_error(action, f"Network error while calling MCP: {exc}")

    if response.status_code == 401 and _is_zoho_oauth_configured():
        LOGGER.warning("MCP returned 401 for action=%s. Retrying with refreshed token.", action)
        headers, token_error = _build_mcp_headers(force_refresh=True)
        if token_error:
            return _build_error(action, token_error, status_code=401)
        try:
            response = _send_mcp_request(payload, headers)
        except RequestException as exc:
            LOGGER.exception("MCP retry failed for action=%s", action)
            return _build_error(action, f"Network error while retrying MCP call: {exc}")

    parsed = _parse_json_response(response)

    if response.status_code >= 400:
        detail = ""
        if isinstance(parsed, dict):
            detail = str(parsed.get("message") or parsed.get("error") or "").strip()
        if not detail:
            detail = response.text.strip()[:500]

        message = f"MCP returned HTTP {response.status_code}."
        if detail:
            message = f"{message} {detail}"

        LOGGER.warning("MCP call failed: action=%s status=%s", action, response.status_code)
        return _build_error(
            action,
            message,
            status_code=response.status_code,
            raw_response=parsed if parsed is not None else response.text,
        )

    if parsed is None:
        LOGGER.error("MCP returned non-JSON response for action=%s", action)
        return _build_error(
            action,
            "MCP response was not valid JSON.",
            status_code=response.status_code,
            raw_response=response.text,
        )

    LOGGER.info("MCP call completed: action=%s status=%s", action, response.status_code)
    return {
        "success": True,
        "action": action,
        "status_code": response.status_code,
        "data": parsed,
    }


def create_record(data: str) -> dict[str, Any]:
    """Create a CRM record via MCP.

    Args:
        data: JSON object string containing record fields.
    """
    parsed_data, error = _parse_json_object_input("create", "data", data)
    if error:
        return error
    return _post_to_mcp("create", parsed_data)


def get_records(query: str) -> dict[str, Any]:
    """Read CRM records via MCP using natural text or JSON object text."""
    normalized_query = str(query).strip() if query is not None else ""
    if not normalized_query:
        return _build_error("read", "Invalid input: 'query' must not be empty.")

    payload: dict[str, Any] = {"query": normalized_query}
    try:
        parsed_query = json.loads(normalized_query)
        if isinstance(parsed_query, dict) and parsed_query:
            payload = parsed_query
    except json.JSONDecodeError:
        pass

    return _post_to_mcp("read", payload)


def update_record(id: str, data: str) -> dict[str, Any]:
    """Update a CRM record by id via MCP.

    Args:
        id: Record id in Zoho CRM.
        data: JSON object string containing fields to update.
    """
    record_id = str(id).strip() if id is not None else ""
    if not record_id:
        return _build_error("update", "Invalid input: 'id' is required.")

    parsed_data, error = _parse_json_object_input("update", "data", data)
    if error:
        return error

    return _post_to_mcp("update", {"id": record_id, "data": parsed_data})


def delete_record(id: str) -> dict[str, Any]:
    """Delete a CRM record by id via MCP."""
    record_id = str(id).strip() if id is not None else ""
    if not record_id:
        return _build_error("delete", "Invalid input: 'id' is required.")

    return _post_to_mcp("delete", {"id": record_id})
