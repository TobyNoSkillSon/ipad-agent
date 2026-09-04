"""Pinned host automation versions and compatibility policy."""
from __future__ import annotations

import re

APPIUM_VERSION = "3.7.0"
XCUITEST_VERSION = "12.8.2"
DOCTOR_SCHEMA = "ipad-agent.doctor/v2"
SETUP_SCHEMA = "ipad-agent.setup/v2"
WDA_ARTIFACT_SCHEMA = "ipad-agent.wda-artifact/v1"
WDA_VERIFICATION_SCHEMA = "ipad-agent.wda-verification/v2"
APPIUM_OWNER_SCHEMA = "ipad-agent.appium-owner/v1"
WDA_VERIFICATION_TTL_SECONDS = 7 * 24 * 60 * 60


def version_tuple(value: str) -> tuple[int, int, int]:
    match = re.search(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", value or "")
    return (int(match.group(1)), int(match.group(2) or 0), int(match.group(3) or 0)) if match else (0, 0, 0)


def node_supported(version: tuple[int, int, int]) -> bool:
    major, minor, _ = version
    return major >= 24 or major == 22 and minor >= 12 or major == 20 and minor >= 19


__all__ = [
    "APPIUM_OWNER_SCHEMA", "APPIUM_VERSION", "DOCTOR_SCHEMA", "SETUP_SCHEMA",
    "WDA_ARTIFACT_SCHEMA", "WDA_VERIFICATION_SCHEMA", "WDA_VERIFICATION_TTL_SECONDS",
    "XCUITEST_VERSION", "node_supported", "version_tuple",
]
