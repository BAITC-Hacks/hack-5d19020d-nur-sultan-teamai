from __future__ import annotations

from typing import Any


FORBIDDEN_ACTIONS = {
    "edit_power_numbers",
    "use_future_actual_weather",
    "overwrite_targets",
}


def guard_tool(name: str, args: dict[str, Any]) -> list[str]:
    blocked: list[str] = []
    if name in FORBIDDEN_ACTIONS:
        blocked.append(f"Tool `{name}` is forbidden by policy")
    if args.get("mutate_predictions") is True:
        blocked.append("LLM/tools may not mutate predictions")
    if args.get("use_observed_weather_as_forecast") is True:
        blocked.append("Observed weather cannot replace forecast inputs")
    return blocked


SYSTEM_PROMPT = """You are the WIND DEMO supervisor.
You may only call these tools: audit_data, run_forecast, explain_metrics, export_submission.
Numeric power forecasts come ONLY from the ML forecast tool.
Never invent February actuals, coordinates, or metrics.
If something is unknown, say so and point to ASSUMPTIONS.md.
Prefer one tool call, then summarize results for the user.
"""
