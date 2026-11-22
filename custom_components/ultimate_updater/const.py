"""Constants of the Ultimate Updater integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "ultimate_updater"
MANUFACTURER: Final = "Ultimate Updater (BassT23)"

DEFAULT_PORT: Final = 8765

CONF_VALIDATE_CERT: Final = "validate_certificate"

# options
CONF_STATUS_INTERVAL: Final = "status_interval"  # minutes
CONF_POLL_IDLE: Final = "poll_idle"  # seconds
CONF_POLL_BUSY: Final = "poll_busy"  # seconds
CONF_EXCLUDE: Final = "exclude_targets"
CONF_BULK_TARGETS: Final = "bulk_targets"
CONF_ALLOW_REBOOT: Final = "allow_reboot"
CONF_REMOVE_STALE: Final = "remove_stale"

DEFAULT_STATUS_INTERVAL: Final = 60
DEFAULT_POLL_IDLE: Final = 30
DEFAULT_POLL_BUSY: Final = 2

BULK_RUNNING: Final = "running"
BULK_ALL: Final = "all"

# job states of Ultimate Updater (web-ui/server.py)
BUSY_STATES: Final = ("running", "pending", "starting")
FAILURE_STATES: Final = ("failed", "interrupted")
SUCCESS_STATES: Final = ("completed", "completed_with_warnings")

# event entity
JOB_EVENT_TYPES: Final = [
    "completed",
    "completed_with_warnings",
    "skipped",
    "failed",
    "interrupted",
]

# a single update should never take 3 h
JOB_TIMEOUT_S: Final = 3 * 60 * 60
