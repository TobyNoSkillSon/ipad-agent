"""Maintenance entry point. Runtime control remains Python-first."""
from __future__ import annotations

import argparse
import json

from .cleanup import run_cleanup
from .doctor import run_doctor
from .setup import PHASES, run_setup
from .versions import DOCTOR_SCHEMA, SETUP_SCHEMA


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ipad-agent")
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor", help="read-only prerequisite and provenance report")
    doctor.add_argument("--json", action="store_true", help="emit one machine-readable document")
    setup = sub.add_parser("setup", help="plan or apply one repository-local setup transition")
    setup.add_argument("--phase", choices=PHASES, default="all")
    setup.add_argument("--apply", action="store_true", help="permit the selected setup mutation")
    setup.add_argument("--json", action="store_true", help="emit one machine-readable document")
    cleanup = sub.add_parser("cleanup", help="remove only metadata-proven ipad-agent WDA artifacts")
    cleanup.add_argument("--keep-fingerprint")
    cleanup.add_argument("--apply", action="store_true", help="permit owned artifact removal")
    cleanup.add_argument("--json", action="store_true", help="emit one machine-readable document")
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            report = run_doctor()
        elif args.command == "setup":
            report = run_setup(apply=args.apply, phase=args.phase)
        else:
            report = run_cleanup(apply=args.apply, keep_fingerprint=args.keep_fingerprint)
    except Exception as error:  # Last-resort stable JSON; never echo private exception text.
        if args.command == "doctor":
            report = {"schema": DOCTOR_SCHEMA, "state": "needs_agent_action", "ready": False, "exit_code": 20, "selected": {"device": False, "signing": False, "wda_artifact": False, "verified": False}, "checks": [{"id": "doctor.internal", "status": "fail", "message": "Doctor failed before diagnostics completed", "stage": "host", "evidence": None, "human_action": None, "remediation": "Fix the local configuration or tool error and rerun doctor."}], "next": ["doctor.internal"]}
        elif args.command == "setup":
            report = {"schema": SETUP_SCHEMA, "state": "failed", "ready": False, "exit_code": 20, "applied": bool(args.apply), "phase": args.phase, "changed": [], "actions": [{"kind": "agent_action", "instructions": "Fix the local setup error and rerun the same phase."}], "operations": [], "doctor": {}, "error": {"code": "uncaught_error", "message": "Setup failed before a diagnostic report was produced."}}
        else:
            report = {"schema": "ipad-agent.cleanup/v1", "state": "failed", "applied": bool(args.apply), "exit_code": 20, "candidates": [], "removed": [], "rejected": [], "error": "Cleanup failed before a report was produced."}
    if getattr(args, "json", False):
        print(json.dumps(report, separators=(",", ":"), ensure_ascii=False, sort_keys=True))
    else:
        print(report.get("state", "ready" if report.get("ready") else "needs action"))
        for item in report.get("next", []):
            print(item)
        for item in report.get("actions", []):
            print(item.get("instructions") or item.get("command"))
        if report.get("error"):
            error = report["error"]
            print(f"failed: {error.get('message') if isinstance(error, dict) else error}")
    return int(report.get("exit_code", 20))


if __name__ == "__main__":
    raise SystemExit(main())
