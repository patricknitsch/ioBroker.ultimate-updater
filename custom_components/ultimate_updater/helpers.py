"""Pure helpers for the target/job payloads of Ultimate Updater (no Home Assistant imports).

The payload is third-party data whose shape depends on the Ultimate Updater version, so every
field is read defensively.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from .const import BUSY_STATES

Target = dict[str, Any]
Job = dict[str, Any]

SEPARATOR = "----------------------------"
LINUX_UPDATERS = ("apt", "debian", "dnf", "pkg", "pacman", "apk", "yum", "ha")
LINUX_OS = (
    "linux", "debian", "ubuntu", "freebsd", "pfsense", "fedora", "centos", "rhel", "rocky",
    "alma", "opensuse", "suse", "arch", "alpine", "gentoo", "home assistant", "haos",
)  # fmt: skip


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


def security_updates(t: Target) -> int | None:
    """Pending security updates, None if unknown."""
    return _int(t.get("security_updates"))


def normal_updates(t: Target) -> int | None:
    """Pending normal updates, None if unknown."""
    return _int(t.get("normal_updates"))


def available_updates(t: Target) -> int | None:
    """Pending updates in total, None if unknown."""
    updates = t.get("updates")
    if isinstance(updates, dict) and (n := _int(updates.get("available"))) is not None:
        return n
    sec, normal = security_updates(t), normal_updates(t)
    if sec is None and normal is None:
        return None
    return (sec or 0) + (normal or 0)


def is_host(t: Target) -> bool:
    return t.get("type") == "host" or str(t.get("id", "")).startswith("host:")


def is_stopped(t: Target) -> bool:
    skip = t.get("skip_reason")
    return (
        t.get("status") == "stopped"
        or t.get("check_status") == "stopped"
        or (isinstance(skip, dict) and "STOPPED" in str(skip.get("code") or ""))
    )


def is_current(t: Target) -> bool:
    """Whether the update counters stem from a current check (a shut down VM may carry old ones)."""
    status = str(t.get("check_status") or "")
    if status:
        return status in ("ok", "updates_available")
    return t.get("reachable") is not False and not is_stopped(t) and not t.get("skip_reason")


def label(t: Target) -> str:
    """ "101 · NAS" for guests, the node name for hosts."""
    tid = str(t.get("id") or "")
    if is_host(t):
        return str(t.get("node") or tid.removeprefix("host:"))
    short = re.sub(r"^(lxc|vm|guest|external):", "", tid)
    name = t.get("name")
    return f"{short} · {name}" if name and name != short else short


def icon(t: Target) -> str:
    """Icon per target as in the status mail of Ultimate Updater."""
    ttype = t.get("type")
    if ttype == "host":
        return "🖥️"
    if ttype == "lxc":
        return "🐧"
    if ttype != "vm":
        return "🌐"
    os_text = " ".join(str(t.get(k)) for k in ("os", "os_version", "os_display") if t.get(k)).lower()
    updater = str(t.get("updater") or "").lower()
    if "windows" in os_text or updater == "windows-update":
        return "🪟"
    if any(m in os_text for m in LINUX_OS) or updater in LINUX_UPDATERS:
        return "🐧"
    return "❔"


def jobs_of(t: Target, jobs: list[Job]) -> list[Job]:
    """Jobs of a target, newest first (host jobs run as node jobs)."""
    tid = t.get("id")
    node = t.get("node")
    own = [
        j for j in jobs if j.get("target") == tid or (is_host(t) and node and j.get("target") in (f"host:{node}", node))
    ]
    own.sort(key=lambda j: parse_time(j.get("started_at") or j.get("finished_at")) or _EPOCH, reverse=True)
    return own


def is_busy(job: Job) -> bool:
    return job.get("state") in BUSY_STATES


_EPOCH = datetime.fromtimestamp(0, UTC)


def parse_time(value: Any) -> datetime | None:
    """ISO string or epoch seconds/milliseconds → aware datetime."""
    if value is None or isinstance(value, bool) or value == "":
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:
            ts /= 1000
        try:
            return datetime.fromtimestamp(ts, UTC)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def summary_text(targets: list[Target]) -> str:
    """Short summary, e.g. "7 updates on 3 systems, 1 reboot required"."""
    total = sum(available_updates(t) or 0 for t in targets if is_current(t))
    systems = sum(1 for t in targets if is_current(t) and (available_updates(t) or 0) > 0)
    reboot = sum(1 for t in targets if t.get("reboot_required") is True)
    parts = [
        f"{total} update{'s' if total != 1 else ''} on {systems} system{'s' if systems != 1 else ''}"
        if total
        else "No updates"
    ]
    if reboot:
        parts.append(f"{reboot} reboot{'s' if reboot != 1 else ''} required")
    return ", ".join(parts)


def build_report(targets: list[Target]) -> str:
    """Status report like the status mail of Ultimate Updater (status-model.sh)."""
    updates: list[Target] = []
    current: list[Target] = []
    reboots: list[Target] = []
    offline: list[Target] = []
    errors: list[tuple[Target, str]] = []
    unsupported: list[Target] = []
    not_checked: list[Target] = []
    skipped: list[Target] = []
    total = 0
    known = False

    for t in targets:
        status = str(t.get("check_status") or "")
        count = available_updates(t)
        if is_current(t) and count is not None:
            known = True
            total += count
            if count > 0:
                updates.append(t)
            elif status == "ok":
                current.append(t)
        if t.get("reboot_required") is True:
            reboots.append(t)
        if t.get("skip_reason") or t.get("status") == "stopped":
            skipped.append(t)
        elif status == "offline" or t.get("reachable") is False:
            offline.append(t)
        elif status == "unsupported":
            unsupported.append(t)
        elif status == "error":
            err = t.get("error") or {}
            msg = (err.get("message") or err.get("code") or "") if isinstance(err, dict) else str(err)
            errors.append((t, msg))
        elif status in ("not_checked", "skipped", "stopped"):
            not_checked.append(t)

    def split(t: Target) -> list[str]:
        sec, normal = security_updates(t), normal_updates(t)
        if sec is not None or normal is not None:
            return [f"Security: {sec or 0}", f"Normal: {normal or 0}"]
        return [f"⬆️ {available_updates(t) or 0} updates"]

    title = "Ultimate Updater status"
    lines = [title, "=" * len(title), ""]
    if updates:
        lines.append("Updates available:")
        by_node: dict[str, list[Target]] = {}
        for t in updates:
            by_node.setdefault(str(t.get("node") or "-"), []).append(t)
        for node, items in by_node.items():
            host = next((t for t in items if t.get("type") == "host"), None) or next(
                (
                    t
                    for t in targets
                    if t.get("type") == "host"
                    and str(t.get("node") or "-") == node
                    and t.get("reachable") is not False
                    and str(t.get("check_status") or "") in ("ok", "updates_available", "")
                ),
                None,
            )
            lines.append("")
            if host:
                lines += [f"🖥️ {node}", *split(host)]
                if host.get("reboot_required") is True:
                    lines.append("🔄 Reboot required")
            else:
                lines += [f"🖥️ {node}", f"⬆️ {sum(available_updates(t) or 0 for t in items)} updates"]
            lines.append(SEPARATOR)
            for t in items:
                if t.get("type") == "host":
                    continue
                lines += [f"{icon(t)} {label(t)}", *split(t)]
                if t.get("reboot_required") is True:
                    lines.append("🔄 Reboot required")
                lines.append(SEPARATOR)
    else:
        lines.append("Updates available: none")
    if known:
        lines += ["", f"Total: {total}"]

    def section(heading: str, rows: list[str]) -> None:
        if rows:
            lines.extend(["", f"{heading}:", *rows])

    section("Up to date", [r for t in current for r in (f"✅ {icon(t)} {label(t)}", "   No updates")])
    section("Reboot required", [f"🔄 {label(t)}" for t in reboots])
    section("Not reachable", [f"⚠️ {icon(t)} {label(t)}" for t in offline])
    section("Errors", [f"⚠️ {icon(t)} {label(t)}{f': {m}' if m else ''}" for t, m in errors])
    section("Unsupported", [f"⚠️ {label(t)}" for t in unsupported])
    section("Not checked", [f"⚠️ {label(t)}" for t in not_checked])
    section("Skipped", [r for t in skipped for r in (f"💤 {label(t)}", f"   {_skip_text(t)}")])
    return "\n".join(lines)


def _skip_text(t: Target) -> str:
    skip = t.get("skip_reason")
    code = str(skip.get("code") or "") if isinstance(skip, dict) else ""
    if "STOPPED" in code or t.get("status") == "stopped":
        return "Shut down"
    if "PAUSED" in code:
        return "Paused"
    return "Skipped"
