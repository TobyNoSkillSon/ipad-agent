"""Detached runtime daemon entry point."""
from __future__ import annotations

import argparse

from ipad_agent.runtime.engine import (
    DEFAULT_IDLE_TTL, DEFAULT_SOCKET_PATH, _env_float, run_daemon,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ipad-agent-daemon")
    parser.add_argument("--socket", default=str(DEFAULT_SOCKET_PATH))
    parser.add_argument("--idle-ttl", type=float, default=_env_float("IPAD_AGENT_RUNTIME_IDLE_TTL", DEFAULT_IDLE_TTL))
    parser.add_argument("--nonce")
    args = parser.parse_args(argv)
    from pathlib import Path
    return run_daemon(Path(args.socket), args.idle_ttl, nonce=args.nonce)


if __name__ == "__main__":
    raise SystemExit(main())
