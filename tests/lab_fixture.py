"""Self-contained inert integration data for generic lab tests."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
from unittest import mock


_DIRECTORY = Path(__file__).parent / "fixtures" / "lab_integration"
MANIFEST_PATH = _DIRECTORY / "integration.fixture"
POLICY_PATH = _DIRECTORY / "url-policy.fixture"


def lab_fixture_manifest() -> dict[str, object]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["_lab_url_policy"] = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    return manifest


def isolate_authorization_receipts(testcase: object) -> None:
    """Keep physical-authorization receipts out of the repository during tests."""
    temporary = tempfile.TemporaryDirectory()
    patcher = mock.patch(
        "ipad_agent.lab.runner.AUTHORIZATION_RECEIPT_ROOT", Path(temporary.name),
    )
    patcher.start()
    testcase.addCleanup(patcher.stop)
    testcase.addCleanup(temporary.cleanup)
