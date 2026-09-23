from __future__ import annotations

import json
import os
from typing import Any

from ..config import agent_config, load_env


def resolve_mode() -> str:
    load_env()
    mode = agent_config().llm_mode
    if mode != "auto":
        return mode
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    if os.getenv("NVIDIA_API_KEY"):
        return "nvidia"
    return "mock"


def chat(messages: list[dict[str, str]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Return OpenAI-style message dict: {role, content, tool_calls?}."""
    mode = resolve_mode()
    if mode == "mock":
        return _mock_decide(messages, allow_tools=tools is not None)
    if mode == "openai":
        return _openai_chat(messages, tools)
    if mode == "nvidia":
        return _nvidia_chat(messages, tools)
    raise ValueError(f"Unknown llm mode: {mode}")


def _mock_decide(messages: list[dict[str, str]], allow_tools: bool = True) -> dict[str, Any]:
    user_bits = [m.get("content", "") for m in messages if m.get("role") == "user"]
    text = " ".join(user_bits).lower()
    if not allow_tools:
        return {
            "role": "assistant",
            "content": (
                "Mock summary: tools finished. Forecast/audit artifacts are on disk under "
                "demo/data/exports and demo/data/processed. February actuals remain not_evaluated "
                "when missing."
            ),
        }
    if "export" in text or "submission" in text:
        name, args = "export_submission", {}
    elif "metric" in text or "explain" in text or "quality" in text:
        name, args = "explain_metrics", {}
    elif "audit" in text or "coverage" in text or "ingest" in text:
        name, args = "audit_data", {}
    elif "forecast" in text or "predict" in text:
        name, args = "run_forecast", {}
    else:
        name, args = "run_forecast", {}
    return {
        "role": "assistant",
        "content": f"[mock] Selecting tool `{name}` for the user goal.",
        "tool_calls": [
            {
                "id": "call_mock_1",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }
        ],
    }


def _openai_chat(messages: list[dict[str, str]], tools: list[dict[str, Any]] | None) -> dict[str, Any]:
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    kwargs: dict[str, Any] = {
        "model": agent_config().openai_model,
        "messages": messages,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    resp = client.chat.completions.create(**kwargs)
    msg = resp.choices[0].message
    out: dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
    if msg.tool_calls:
        out["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in msg.tool_calls
        ]
    return out


def _nvidia_chat(messages: list[dict[str, str]], tools: list[dict[str, Any]] | None) -> dict[str, Any]:
    from openai import OpenAI

    client = OpenAI(
        api_key=os.environ["NVIDIA_API_KEY"],
        base_url=os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
    )
    kwargs: dict[str, Any] = {
        "model": agent_config().nvidia_model,
        "messages": messages,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    resp = client.chat.completions.create(**kwargs)
    msg = resp.choices[0].message
    out: dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
    if msg.tool_calls:
        out["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"},
            }
            for tc in msg.tool_calls
        ]
    return out
