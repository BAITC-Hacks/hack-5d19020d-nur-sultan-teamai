import json
import subprocess
import sys
import xml.etree.ElementTree as ET

from .config import ROOT, data_root, iso, now, project
from .llm import usage_summary
from .storage import db, read_json, sha256, write_json


def release_check():
    reports = data_root()/"reports"
    reports.mkdir(parents=True, exist_ok=True)
    commands = {}
    for name, args in [("lint", ["ruff", "check", "wind_agent", "ui", "tests"]),
                       ("tests", ["pytest", f"--junitxml={reports/'tests.xml'}"])]:
        result = subprocess.run([sys.executable, "-m", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
        (reports/f"{name}.log").write_text(result.stdout+result.stderr, encoding="utf-8")
        commands[name] = {"exit_code": result.returncode, "log": f"{name}.log"}
    cfg = project()
    audit_path = data_root()/"observations"/cfg.fingerprint/"audit.json"
    selection_path = data_root()/"evaluations"/"selected.json"
    active_path = data_root()/"models"/"active.json"
    replay_path = data_root()/"replays"/"latest.json"
    replay = read_json(replay_path) if replay_path.exists() else None
    selection = read_json(selection_path) if selection_path.exists() else None
    with db() as conn:
        verified = conn.execute("SELECT payload FROM events WHERE stage='supervisor_decision'").fetchall()
    llm_verified = any(json.loads(r[0]).get("request_id") for r in verified)
    real = bool(replay and replay["origins"] == 29 and replay["rows"] == 2784 and replay["february_rows"] == 2688)
    passed = all(v["exit_code"] == 0 for v in commands.values())
    tests = ET.parse(reports/"tests.xml").getroot().find("testsuite") if (reports/"tests.xml").exists() else None
    model_card = read_json(data_root()/"models"/read_json(active_path)["version"]/"card.json") if active_path.exists() else None
    report = {
        "created_at": iso(now()), "config_hash": cfg.fingerprint, "commands": commands,
        "test_counts": dict(tests.attrib) if tests is not None else None,
        "status": {"SOFTWARE_READY": passed and audit_path.exists() and active_path.exists(),
                   "REAL_DATA_RUN_EXECUTED": real,
                   "STRICT_REPLAY_VALIDATED": real and bool(replay.get("strict")),
                   "AGENT_INTEGRATION_VERIFIED": llm_verified,
                   "FEBRUARY_SCORE_AVAILABLE": False,
                   "PRODUCTION_APPROVED": False},
        "selection": selection,
        "model_card": model_card,
        "replay": replay,
        "api_usage": usage_summary(),
        "limitations": ["SCADA timezone and interval label assumed for MVP with user authorization",
                        "GFS release lag is conservative but unconfirmed; S3 timestamps preserved",
                        "1-degree GFS grid and sampled training/development origins for MVP",
                        "January interval coverage is measured, not assumed to equal 80%",
                        "February power actuals are absent; no February accuracy claim",
                        "Docker image has not been validated on this machine (daemon unavailable)",
                        "Optional TimesFM and two-stage OOF weather correction not implemented in MVP"],
        "source_sha256": {str(p.relative_to(ROOT)): sha256(p) for folder in ["wind_agent", "ui", "tests"] for p in (ROOT/folder).glob("*.py")},
    }
    write_json(reports/"RELEASE_EVIDENCE.json", report)
    write_json(ROOT/"docs"/"release"/"RELEASE_EVIDENCE.json", report)
    return report
