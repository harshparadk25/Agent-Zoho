"""Interactive ADK agent for Zoho CRM MCP CRUD operations."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
import sys
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

# Support direct script execution: python multi_tool_agent/agent.py
if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parent.parent))

# Load environment before importing tool modules so env-backed constants initialize correctly.
ENV_PATH = Path(__file__).resolve().with_name(".env")
load_dotenv(dotenv_path=ENV_PATH)

from multi_tool_agent.prompts import SYSTEM_PROMPT
from multi_tool_agent.tools import create_record, delete_record, get_records, update_record

APP_NAME = "zoho_crm_mcp_agent"
USER_ID = "local_user"
DEFAULT_GEMINI_MODEL = "gemini-1.5-flash"
FALLBACK_GEMINI_MODELS = (
    "gemini-2.0-flash",
    "gemini-2.5-flash",
    "gemini-1.5-flash-8b",
)

LOGGER = logging.getLogger(__name__)


class CRMAgentApp:
    """Application wrapper for an ADK tool-based CRM agent."""

    def __init__(self) -> None:
        self._configure_logging()
        self._validate_environment()
        model_name = self._resolve_model_name()

        self.agent = Agent(
            name="zoho_crm_agent",
            model=model_name,
            description="Handles Zoho CRM CRUD actions via MCP tools.",
            instruction=SYSTEM_PROMPT,
            generate_content_config=types.GenerateContentConfig(
                toolConfig=types.ToolConfig(
                    functionCallingConfig=types.FunctionCallingConfig(
                        mode=types.FunctionCallingConfigMode.AUTO,
                    )
                ),
                automaticFunctionCalling=types.AutomaticFunctionCallingConfig(
                    disable=False,
                    maximumRemoteCalls=1,
                ),
            ),
            tools=[create_record, get_records, update_record, delete_record],
        )

        self.session_service = InMemorySessionService()
        session = asyncio.run(
            self.session_service.create_session(
                app_name=APP_NAME,
                user_id=USER_ID,
            )
        )
        self.session_id = session.id

        self.runner = Runner(
            agent=self.agent,
            app_name=APP_NAME,
            session_service=self.session_service,
        )

        LOGGER.info(
            "ADK CRM agent initialized with model=%s session_id=%s",
            model_name,
            self.session_id,
        )

    @staticmethod
    def _configure_logging() -> None:
        level_name = os.getenv("LOG_LEVEL", "INFO").upper()
        level = getattr(logging, level_name, logging.INFO)
        logging.basicConfig(
            level=level,
            format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        )

    @staticmethod
    def _validate_environment() -> None:
        if not os.getenv("GOOGLE_API_KEY"):
            raise RuntimeError(
                "GOOGLE_API_KEY is missing. Add it in multi_tool_agent/.env before running the agent."
            )

    @staticmethod
    def _normalize_model_name(model_name: str) -> str:
        return model_name.split("/", 1)[-1] if "/" in model_name else model_name

    def _resolve_model_name(self) -> str:
        """Resolve the best available Gemini model, with fallbacks for compatibility."""
        requested_model = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip() or DEFAULT_GEMINI_MODEL
        requested_model = self._normalize_model_name(requested_model)

        candidates: list[str] = [requested_model]
        for fallback in FALLBACK_GEMINI_MODELS:
            if fallback not in candidates:
                candidates.append(fallback)

        try:
            client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
            available_models: list[str] = [
                self._normalize_model_name(model.name)
                for model in client.models.list()
                if getattr(model, "name", None)
            ]
        except Exception as exc:
            LOGGER.warning(
                "Could not list available Gemini models; using requested model=%s (%s)",
                requested_model,
                exc,
            )
            return requested_model

        available_set = set(available_models)
        for candidate in candidates:
            if candidate in available_set:
                return candidate

        for candidate in candidates:
            prefix_matches = sorted([name for name in available_models if name.startswith(candidate)])
            if prefix_matches:
                chosen = prefix_matches[0]
                LOGGER.warning(
                    "Requested model=%s not found; using compatible model=%s",
                    requested_model,
                    chosen,
                )
                return chosen

        LOGGER.warning(
            "Requested model=%s is unavailable and no fallback was found; using requested name.",
            requested_model,
        )
        return requested_model

    def run(self, user_input: str) -> dict[str, Any]:
        """Run one user turn through ADK and return a structured response."""
        message = types.Content(role="user", parts=[types.Part(text=user_input)])

        try:
            final_text = ""
            for event in self.runner.run(
                user_id=USER_ID,
                session_id=self.session_id,
                new_message=message,
            ):
                if event.is_final_response() and event.content and event.content.parts:
                    final_text = self._extract_text(event.content.parts)

            if not final_text:
                return {
                    "success": False,
                    "message": "Agent did not produce a final response. Check logs for model/auth/tool errors.",
                }

            return {
                "success": True,
                "response": final_text,
            }
        except Exception as exc:
            LOGGER.exception("Agent execution failed")
            return {
                "success": False,
                "message": f"Agent execution failed: {exc}",
            }

    @staticmethod
    def _extract_text(parts: list[types.Part]) -> str:
        text_chunks: list[str] = []
        for part in parts:
            if getattr(part, "text", None):
                text_chunks.append(part.text)
        return "\n".join(text_chunks).strip()

def _format_output(result: dict[str, Any]) -> str:
    """Format agent output for readable terminal display."""
    if result.get("success") and isinstance(result.get("response"), str):
        return result["response"]

    return json.dumps(result, indent=2, ensure_ascii=True)


def main() -> None:
    app = CRMAgentApp()
    print("Zoho CRM MCP agent is ready. Type your request (or 'exit' to quit).")

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting agent.")
            break

        if not user_input:
            continue

        if user_input.lower() in {"exit", "quit"}:
            print("Exiting agent.")
            break

        result = app.run(user_input)
        print("\nAgent:")
        print(_format_output(result))


if __name__ == "__main__":
    main()
