from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from ..config import get_paths
from ..schemas import AgentTrace
from ..storage import write_json
from .policy import SYSTEM_PROMPT
from .providers import chat, resolve_mode
from .tools import OPENAI_TOOLS, run_tool


class AgentState(TypedDict, total=False):
    goal: str
    messages: list[dict[str, Any]]
    steps: list[dict[str, Any]]
    blocked: list[str]
    final_answer: str
    step_count: int


def _planner(state: AgentState) -> AgentState:
    messages = list(state.get("messages") or [])
    if not messages:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": state["goal"]},
        ]
    reply = chat(messages, tools=OPENAI_TOOLS)
    messages.append(reply)
    steps = list(state.get("steps") or [])
    steps.append({"type": "llm", "mode": resolve_mode(), "content": reply.get("content"), "tool_calls": reply.get("tool_calls")})
    out = {
        **state,
        "messages": messages,
        "steps": steps,
        "step_count": int(state.get("step_count") or 0) + 1,
    }
    if not reply.get("tool_calls"):
        out["final_answer"] = reply.get("content") or "No tool selected."
    return out


def _executor(state: AgentState) -> AgentState:
    messages = list(state.get("messages") or [])
    last = messages[-1] if messages else {}
    tool_calls = last.get("tool_calls") or []
    steps = list(state.get("steps") or [])
    blocked = list(state.get("blocked") or [])
    if not tool_calls:
        return {**state, "final_answer": last.get("content") or "No tool selected."}
    for tc in tool_calls:
        name = tc["function"]["name"]
        args = tc["function"].get("arguments") or "{}"
        result = run_tool(name, args)
        if "blocked" in result:
            blocked.extend(result["blocked"])
        steps.append({"type": "tool", "name": name, "arguments": args, "result": result})
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tc.get("id", "call"),
                "name": name,
                "content": json.dumps(result, default=str),
            }
        )
    # one-shot summary without further tools
    summary = chat(
        messages
        + [
            {
                "role": "user",
                "content": "Summarize tool results for the operator. Do not call more tools. Be concise.",
            }
        ],
        tools=None,
    )
    messages.append(summary)
    steps.append({"type": "llm_summary", "content": summary.get("content")})
    return {
        **state,
        "messages": messages,
        "steps": steps,
        "blocked": blocked,
        "final_answer": summary.get("content") or "Done.",
        "step_count": int(state.get("step_count") or 0) + 1,
    }


def _route(state: AgentState) -> str:
    last = (state.get("messages") or [{}])[-1]
    if last.get("tool_calls"):
        return "executor"
    return END


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("planner", _planner)
    g.add_node("executor", _executor)
    g.set_entry_point("planner")
    g.add_conditional_edges("planner", _route, {"executor": "executor", END: END})
    g.add_edge("executor", END)
    return g.compile()


def run_agent(goal: str) -> AgentTrace:
    graph = build_graph()
    final_state = graph.invoke({"goal": goal, "messages": [], "steps": [], "blocked": [], "step_count": 0})
    trace = AgentTrace(
        created_at_utc=datetime.now(timezone.utc),
        mode=resolve_mode(),
        goal=goal,
        steps=final_state.get("steps") or [],
        final_answer=final_state.get("final_answer") or "",
        blocked=final_state.get("blocked") or [],
    )
    out = get_paths()["traces"] / f"trace_{trace.created_at_utc.strftime('%Y%m%dT%H%M%S')}.json"
    write_json(out, trace.model_dump())
    return trace
