from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .config import data_root, project, utc
from .forecast import predict_origin
from .llm import ProviderUnavailable, choose_tool
from .models import PowerModel, active_model
from .storage import event, read_json


class AgentState(TypedDict, total=False):
    origin: str
    job_id: str
    provider: str
    model_version: str
    strict: bool
    decisions: int
    inspected_quality: bool
    inspected_model: bool
    result: dict
    quality: dict
    model: dict
    decision: dict
    degraded: bool
    finished: bool
    llm_verified: bool


def allowed_actions(state):
    actions = {}
    if not state.get("inspected_quality"):
        actions["get_quality_report"] = "Прочитать аудит исходных данных и принятые допущения"
    if not state.get("inspected_model"):
        actions["get_model_card"] = "Прочитать зарегистрированную модель и временную границу обучения"
    if state.get("inspected_quality") and state.get("inspected_model") and not state.get("result"):
        actions["run_forecast"] = "Получить погоду, рассчитать прогноз и проверить численные инварианты"
    if state.get("result"):
        actions["finish"] = "Завершить задачу с сохраненным и проверенным прогнозом"
    return actions


def _supervisor(state):
    actions = allowed_actions(state)
    if not actions:
        raise ValueError("Agent reached an invalid state")
    count = state.get("decisions", 0)
    if count >= 6:
        raise ValueError("Supervisor exceeded six decisions")
    context = {"origin": state["origin"], "quality": state.get("quality"), "model": state.get("model"),
               "result": state.get("result"), "decisions_remaining": 6-count,
               "assumptions": {"time_metadata_confirmed": project().time_metadata_confirmed,
                               "power_unit": "normalized, no rated power supplied"}}
    degraded = state.get("degraded", False)
    verified = state.get("llm_verified", False)
    if state["provider"] != "offline" and not degraded:
        try:
            decision = choose_tool(context, actions, state["provider"])
            verified = True
        except ProviderUnavailable as exc:
            degraded = True
            event(state["job_id"], "provider_unavailable", {"reason": str(exc), "fallback": "deterministic_policy"})
    else:
        degraded = state["provider"] != "offline" or degraded
    if state["provider"] == "offline" or degraded:
        decision = {"action": next(iter(actions)), "reason": "Локальная политика: следующий разрешенный шаг", "provider": "offline"}
    event(state["job_id"], "supervisor_decision", {**decision, "number": count+1})
    return {"decision": decision, "decisions": count+1, "degraded": degraded, "llm_verified": verified}


def _execute(state):
    action = state["decision"]["action"]
    if action not in allowed_actions(state):
        raise ValueError("Disallowed planner transition")
    if action == "get_quality_report":
        audit = read_json(data_root() / "observations" / project().fingerprint / "audit.json")
        summary = {"sites": [{k: r[k] for k in ["site_id", "full_hours", "partial_hours", "empty_hours"]} for r in audit["sites"]],
                   "time_metadata_confirmed": audit["confirmed_time_metadata"]}
        update = {"inspected_quality": True, "quality": summary}
    elif action == "get_model_card":
        model = PowerModel.load(state["model_version"])
        if utc(model.card["fit_cutoff"]) > utc(state["origin"]):
            raise ValueError("Registered model is from after the requested origin")
        summary = {k: model.card[k] for k in ["version", "kind", "fit_cutoff", "train_rows", "mode"]}
        update = {"inspected_model": True, "model": summary}
    elif action == "run_forecast":
        _, manifest = predict_origin(state["origin"], model=PowerModel.load(state["model_version"]), strict=state.get("strict", False))
        update = {"result": manifest}
    else:
        update = {"finished": True}
    event(state["job_id"], f"tool:{action}", update)
    return update


def run_agent(origin, job_id="interactive", provider="offline", strict=False, model_version=None):
    graph = StateGraph(AgentState)
    graph.add_node("supervisor", _supervisor)
    graph.add_node("tool", _execute)
    graph.add_edge(START, "supervisor")
    graph.add_edge("supervisor", "tool")
    graph.add_conditional_edges("tool", lambda state: "done" if state.get("finished") else "continue",
                                {"done": END, "continue": "supervisor"})
    state = graph.compile().invoke({"origin": str(utc(origin)), "job_id": job_id, "provider": provider,
                                    "model_version": model_version or active_model().card["version"],
                                    "strict": strict, "decisions": 0}, {"recursion_limit": 16})
    return {"forecast": state["result"], "provider": provider, "degraded": state.get("degraded", False),
            "llm_verified": state.get("llm_verified", False), "supervisor_decisions": state["decisions"]}
