from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wind_demo.agent.graph import run_agent  # noqa: E402
from wind_demo.config import load_env  # noqa: E402
from wind_demo.fixtures import make_fixtures  # noqa: E402
from wind_demo.forecast import run_forecast  # noqa: E402
from wind_demo.ingest import ingest  # noqa: E402
from wind_demo.storage import ensure_dirs  # noqa: E402
from wind_demo.train import train_model  # noqa: E402


def main() -> int:
    load_env()
    ensure_dirs()
    print("== make fixtures ==")
    print(json.dumps(make_fixtures(days=45), indent=2))
    print("== ingest ==")
    print(json.dumps(ingest(prefer_raw=False), indent=2, default=str))
    print("== train ==")
    print(json.dumps(train_model(max_origins=24), indent=2))
    print("== forecast ==")
    bundle = run_forecast()
    print(
        json.dumps(
            {
                "origin": str(bundle.origin_utc),
                "rows": len(bundle.rows),
                "score_status": bundle.score_status,
                "contract_status": bundle.contract_status,
                "metrics": bundle.metrics,
            },
            indent=2,
        )
    )
    print("== agent (mock/openai/nvidia) ==")
    trace = run_agent("Audit coverage then run forecast and summarize readiness.")
    print(json.dumps({"mode": trace.mode, "final": trace.final_answer, "steps": len(trace.steps)}, indent=2))
    print("OK: demo pipeline finished")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
