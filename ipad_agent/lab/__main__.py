"""Host/static maintenance CLI. Device work is intentionally Python-only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .docs import integration_docs
from .scaffold import scaffold_integration
from .validation import validate_manifest


def _emit(value: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, separators=(",", ":"), ensure_ascii=False))
    else:
        print(json.dumps(value, indent=2, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m ipad_agent.lab", description="Static integration authoring tools; physical work is Python API only")
    commands = parser.add_subparsers(dest="command", required=True)

    scaffold = commands.add_parser("scaffold", help="preview or create one unindexed manifest")
    scaffold.add_argument("integration_id")
    scaffold.add_argument("--name", required=True)
    scaffold.add_argument("--kind", choices=["core", "addon"], default="addon")
    scaffold.add_argument("--bundle-id", action="append", required=True, dest="bundle_ids")
    scaffold.add_argument("--output")
    scaffold.add_argument("--apply", action="store_true", help="write the new manifest; default is dry-run")
    scaffold.add_argument("--json", action="store_true")

    validate = commands.add_parser("validate", help="strictly validate one manifest")
    validate.add_argument("manifest")
    validate.add_argument("--json", action="store_true")

    docs = commands.add_parser("docs", help="preview, write, or check generated integration docs")
    docs.add_argument("manifest")
    docs.add_argument("--output", required=True)
    mode = docs.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="write generated docs; default is dry-run")
    mode.add_argument("--check", action="store_true", help="exit nonzero when output has drifted")
    docs.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    try:
        if args.command == "scaffold":
            result = scaffold_integration(args.integration_id, name=args.name, kind=args.kind, bundle_ids=args.bundle_ids, output=args.output, apply=args.apply)
        elif args.command == "validate":
            manifest = validate_manifest(args.manifest)
            result = {"ok": True, "id": manifest["id"], "scenarios": sorted(manifest["scenarios"])}
        else:
            result = integration_docs(args.manifest, output=args.output, apply=args.apply, check=args.check)
        _emit(result, args.json)
        return 0 if result.get("ok") else 1
    except Exception as error:
        result = {"ok": False, "error": " ".join(str(error).split()), "type": type(error).__name__}
        _emit(result, getattr(args, "json", False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
