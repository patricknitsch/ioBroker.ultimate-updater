"""Pure helpers (report like the status mail of Ultimate Updater)."""

from custom_components.ultimate_updater.helpers import available_updates, build_report, is_stopped, label, summary_text


def test_label() -> None:
    assert label({"id": "lxc:101", "name": "web", "type": "lxc"}) == "101 · web"
    assert label({"id": "host:pve", "type": "host", "node": "pve"}) == "pve"
    assert label({"id": "vm:200", "name": "200", "type": "vm"}) == "200"


def test_counts() -> None:
    assert available_updates({"updates": {"available": 4}, "security_updates": 1}) == 4
    assert available_updates({"security_updates": 1, "normal_updates": 2}) == 3
    assert available_updates({}) is None
    assert is_stopped({"skip_reason": {"code": "STOPPED_READ_ONLY"}})


def test_report() -> None:
    targets = [
        {"id": "host:pve", "type": "host", "node": "pve", "security_updates": 0, "normal_updates": 1,
         "reboot_required": True, "check_status": "updates_available"},
        {"id": "lxc:101", "name": "web", "type": "lxc", "node": "pve", "security_updates": 2, "normal_updates": 5,
         "check_status": "updates_available"},
        {"id": "vm:300", "name": "old", "type": "vm", "node": "pve", "security_updates": 9,
         "skip_reason": {"code": "STOPPED_READ_ONLY"}, "check_status": "not_checked"},
        {"id": "lxc:105", "name": "x", "type": "lxc", "check_status": "error", "error": {"message": "apt broken"}},
    ]  # fmt: skip
    report = build_report(targets)
    assert "🖥️ pve" in report
    assert "🐧 101 · web\nSecurity: 2\nNormal: 5" in report
    assert "Total: 8" in report  # the shut down VM does not count
    assert "💤 300 · old\n   Shut down" in report
    assert "⚠️ 🐧 105 · x: apt broken" in report
    assert summary_text(targets) == "8 updates on 2 systems, 1 reboot required"
