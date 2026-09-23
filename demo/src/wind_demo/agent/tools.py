from __future__ import annotations

import json
from typing import Any, Callable

from ..forecast import export_submission, run_forecast
from ..ingest import ingest, load_hourly
from ..train import MODEL_NAME, load_model
from .policy import guard_tool


def audit_data(_: dict[str, Any] | None = None) -> dict[str, Any]:
    audit = ingest(prefer_raw=True)
    hourly = load_hourly()
    return {
        "audit": audit,
        "n_hourly": int(len(hourly)),
        "turbines": sorted(hourly["turbine_id"].unique().tolist()),
        "last_utc": str(hourly["valid_start_utc"].max()),
        "feb_2026_rows": int(
            ((hourly["valid_start_utc"] >= "2026-02-01") & (hourly["valid_start_utc"] < "2026-03-01")).sum()
        ),
    }


def tool_run_forecast(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    bundle = run_forecast(origin=args.get("origin"), turbine_ids=args.get("turbine_ids"))
    return {
        "origin_utc": str(bundle.origin_utc),
        "n_rows": len(bundle.rows),
        "contract_status": bundle.contract_status,
        "score_status": bundle.score_status,
        "metrics": bundle.metrics,
        "notes": bundle.notes,
        "sample": [r.model_dump() for r in bundle.rows[:4]],
    }


def explain_metrics(_: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        _, metrics = load_model()
        return {"model_version": MODEL_NAME, "metrics": metrics}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "hint": "Run train first"}


def tool_export_submission(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    return export_submission(origin=args.get("origin"))


TOOL_IMPL: dict[str, Callable[[dict[str, Any] | None], dict[str, Any]]] = {
    "audit_data": audit_data,
    "run_forecast": tool_run_forecast,
    "explain_metrics": explain_metrics,
    "export_submission": tool_export_submission,
}


OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "audit_data",
            "description": "Ingest SCADA/fixture data and report coverage (including Feb 2026 count).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_forecast",
            "description": "Run 48h ML power forecast for configured turbines.",
            "parameters": {
                "type": "object",
                "properties": {
                    "origin": {"type": "string", "description": "ISO origin UTC, optional"},
                    "turbine_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explain_metrics",
            "description": "Return trained model validation metrics.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_submission",
            "description": "Export forecast CSV preview for packaging.",
            "parameters": {
                "type": "object",
                "properties": {"origin": {"type": "string"}},
            },
        },
    },
]


def run_tool(name: str, arguments: str | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(arguments, str):
        args = json.loads(arguments or "{}")
    else:
        args = arguments or {}
    blocked = guard_tool(name, args)
    if blocked:
        return {"blocked": blocked}
    if name not in TOOL_IMPL:
        return {"error": f"Unknown tool {name}"}
    return TOOL_IMPL[name](args)
