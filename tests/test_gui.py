from threading import Event

import pytest
from PySide6.QtCore import QThreadPool, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QToolBar,
)

from unifi2netbox.config import (
    BehaviorConfig,
    NetBoxConfig,
    UniFiConfig,
    load_behavior_config,
    load_config,
    load_unifi_config,
    save_config,
    save_unifi_config,
)
from unifi2netbox.connections import ConnectionRunner
from unifi2netbox.gui import (
    InventoryPreviewResult,
    InventoryPreviewRow,
    MainWindow,
    SettingsDialog,
    WriteExecutionGuiResult,
    _preview_rows,
    _scope_unmatched_netbox_for_delete,
)
from unifi2netbox.inventory import (
    InventoryDevice,
    InventoryDeviceType,
    InventorySnapshot,
    InventorySource,
)
from unifi2netbox.matching import (
    deduplicate_inventory,
    suggest_device_types_for_unmatched,
)
from unifi2netbox.netbox import ConnectionResult, ConnectionState
from unifi2netbox.preview import build_change_preview, build_difference_preview
from unifi2netbox.write_plan import build_write_plan


@pytest.fixture
def pool(qapp):
    thread_pool = QThreadPool(qapp)
    thread_pool.setMaxThreadCount(2)
    yield thread_pool
    assert thread_pool.waitForDone(5000)


def online(config):
    return ConnectionResult(
        ConnectionState.ONLINE, "Synthetic inventory read.", "4.7.3"
    )


def dialog(qtbot, tmp_path, pool, checker=online):
    widget = SettingsDialog(tmp_path / "config.toml", NetBoxConfig(), pool, checker)
    qtbot.addWidget(widget)
    widget.show()
    return widget


def test_settings_save_masks_and_roundtrips_token(qtbot, tmp_path, pool):
    widget = dialog(qtbot, tmp_path, pool)
    assert widget.netbox.token.echoMode() == QLineEdit.EchoMode.Password
    widget.netbox.url.setText("https://netbox.invalid/")
    widget.netbox.token.setText("synthetic-token")
    widget.netbox.verify_tls.setChecked(False)
    assert "disabled" in widget.netbox.warning.text()
    widget.save()
    assert widget.result() == QDialog.DialogCode.Accepted
    assert load_config(widget.path) == widget.saved_config
    assert widget.saved_config.token == "synthetic-token"
    reopened = SettingsDialog(widget.path, widget.saved_config, pool)
    qtbot.addWidget(reopened)
    reopened.save()
    assert load_config(widget.path).token == "synthetic-token"


def test_cancel_does_not_save(qtbot, tmp_path, pool):
    widget = dialog(qtbot, tmp_path, pool)
    widget.netbox.token.setText("unsaved-token")
    widget.reject()
    assert not widget.path.exists()


def test_first_run_opens_settings(qtbot, tmp_path, pool, monkeypatch):
    opened = []
    monkeypatch.setattr(MainWindow, "open_settings", lambda self: opened.append(True))
    window = MainWindow(tmp_path / "config.toml", pool)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: bool(opened))
    assert window.state.text() == "Unconfigured"


def test_show_token_toggle(qtbot, tmp_path, pool):
    widget = dialog(qtbot, tmp_path, pool)
    widget.netbox.show_token.setChecked(True)
    assert widget.netbox.token.echoMode() == QLineEdit.EchoMode.Normal
    widget.netbox.show_token.setChecked(False)
    assert widget.netbox.token.echoMode() == QLineEdit.EchoMode.Password


def test_validation_and_save_errors_stay_in_dialog(qtbot, tmp_path, pool, monkeypatch):
    widget = dialog(qtbot, tmp_path, pool)
    widget.netbox.url.setText("invalid")
    widget.save()
    assert "explicit" in widget.outcome.text()
    assert widget.saved_config is None
    widget.netbox.url.setText("https://netbox.invalid")

    def fail(*args):
        from unifi2netbox.config import ConfigError

        raise ConfigError("Cannot save configuration.")

    monkeypatch.setattr("unifi2netbox.gui.save_connections", fail)
    widget.save()
    assert "Cannot save" in widget.outcome.text()
    assert widget.isVisible()


def test_test_connection_uses_unsaved_values(qtbot, tmp_path, pool):
    received = []

    def checker(config):
        received.append(config)
        return online(config)

    widget = dialog(qtbot, tmp_path, pool, checker)
    widget.netbox.url.setText("https://netbox.invalid")
    widget.netbox.token.setText("unsaved-token")
    widget.test_connections()
    qtbot.waitUntil(lambda: not widget.busy)
    assert received[0].token == "unsaved-token"
    assert "Online" in widget.outcome.text()
    assert widget.test_button.isEnabled()
    assert not widget.path.exists()


def test_worker_exception_does_not_leak_secret(qtbot, pool):
    def broken(config):
        raise RuntimeError("synthetic-private-token")

    runner = ConnectionRunner(pool, broken)
    with qtbot.waitSignal(runner.finished) as blocker:
        runner.start(NetBoxConfig())
    assert blocker.args[1].state == ConnectionState.ERROR
    assert "private-token" not in blocker.args[1].message


def test_unconfigured_window_does_not_create_file(qtbot, tmp_path, pool):
    path = tmp_path / "config.toml"
    window = MainWindow(path, pool, open_first_run=False)
    qtbot.addWidget(window)
    window.show()
    assert window.state.text() == "Unconfigured"
    assert not path.exists()


def test_startup_checks_saved_connection(qtbot, tmp_path, pool):
    path = tmp_path / "config.toml"
    save_config(path, NetBoxConfig("https://netbox.invalid", "synthetic-token"))
    window = MainWindow(path, pool, online)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.state.text() == "Online")
    assert window.server_version.text() == "4.7.3"
    assert window.check_action.isEnabled()


def test_malformed_config_is_reported_without_overwrite(qtbot, tmp_path, pool):
    path = tmp_path / "config.toml"
    path.write_text("[broken", encoding="utf-8")
    window = MainWindow(path, pool, open_first_run=False)
    qtbot.addWidget(window)
    assert window.state.text() == "Error"
    assert path.read_text() == "[broken"


def test_main_window_remains_responsive_and_defers_close(qtbot, tmp_path, pool):
    release = Event()
    running = Event()

    def blocked(config):
        running.set()
        assert release.wait(5)
        return online(config)

    window = MainWindow(tmp_path / "config.toml", pool, blocked, open_first_run=False)
    qtbot.addWidget(window)
    window.show()
    try:
        window.recheck()
        qtbot.waitUntil(running.is_set)
        assert not window.runner.start(NetBoxConfig())
        processed = []
        QTimer.singleShot(0, lambda: processed.append(True))
        qtbot.waitUntil(lambda: bool(processed))
        window.close()
        assert window.isVisible()
        assert window.closing
    finally:
        release.set()
    qtbot.waitUntil(lambda: not window.isVisible())


def test_stale_result_does_not_replace_new_settings(qtbot, tmp_path, pool):
    release = Event()
    running = Event()

    def checker(config):
        if config.url == "https://old.invalid":
            running.set()
            assert release.wait(5)
            return ConnectionResult(ConnectionState.OFFLINE, "Old result")
        return online(config)

    window = MainWindow(tmp_path / "config.toml", pool, checker, open_first_run=False)
    qtbot.addWidget(window)
    try:
        window.apply_config(NetBoxConfig("https://old.invalid", "old-token"))
        qtbot.waitUntil(running.is_set)
        window.apply_config(NetBoxConfig("https://new.invalid", "new-token"))
    finally:
        release.set()
    qtbot.waitUntil(lambda: window.state.text() == "Online")
    assert window.endpoint.text() == "https://new.invalid"
    assert "Old result" not in window.details.text()


def test_dialog_close_waits_for_worker(qtbot, tmp_path, pool):
    release = Event()
    running = Event()

    def blocked(config):
        running.set()
        assert release.wait(5)
        return online(config)

    widget = dialog(qtbot, tmp_path, pool, blocked)
    try:
        widget.test_connections()
        qtbot.waitUntil(running.is_set)
        widget.reject()
        assert widget.isVisible()
        assert not widget.buttons.isEnabled()
    finally:
        release.set()
    qtbot.waitUntil(lambda: not widget.isVisible())


def unifi_online(config):
    return ConnectionResult(
        ConnectionState.ONLINE, "Synthetic local API access.", "10.6.100", "Default"
    )


def test_unifi_settings_save_preserves_netbox(qtbot, tmp_path, pool):
    path = tmp_path / "config.toml"
    netbox = NetBoxConfig("https://netbox.invalid", "netbox-synthetic")
    save_config(path, netbox)
    widget = SettingsDialog(
        path,
        netbox,
        pool,
        online,
        unifi_config=UniFiConfig(),
        unifi_checker=unifi_online,
    )
    qtbot.addWidget(widget)
    widget.unifi.url.setText("https://console.invalid")
    widget.unifi.token.setText("unifi-synthetic")
    widget.unifi.verify_tls.setChecked(False)
    widget.unifi.site.setEditText("default")
    widget.save()
    assert widget.result() == QDialog.DialogCode.Accepted
    assert load_config(path) == netbox
    assert load_unifi_config(path).site == "default"
    assert load_unifi_config(path).verify_tls is False
    assert load_config(path).verify_tls is True


def test_unifi_site_discovery_then_selection(qtbot, tmp_path, pool):
    choices = (("site-one", "First"), ("site-two", "Second"))

    def discover(config):
        assert isinstance(config, UniFiConfig)
        return ConnectionResult(
            ConnectionState.UNCONFIGURED, "Choose a site.", "10.6.100", sites=choices
        )

    path = tmp_path / "config.toml"
    config = UniFiConfig("https://console.invalid", "synthetic-key")
    widget = SettingsDialog(
        path, NetBoxConfig(), pool, online, unifi_config=config, unifi_checker=discover
    )
    qtbot.addWidget(widget)
    widget.test_connections()
    qtbot.waitUntil(lambda: not widget.busy)
    assert not path.exists()
    assert widget.unifi.site.count() == 3
    assert widget.unifi.token.echoMode() == QLineEdit.EchoMode.Password
    widget.unifi.site.setCurrentIndex(widget.unifi.site.findData("site-two"))
    widget.save()
    assert load_unifi_config(path).site == "site-two"


def test_services_have_independent_startup_statuses(qtbot, tmp_path, pool):
    path = tmp_path / "config.toml"
    save_config(path, NetBoxConfig("https://netbox.invalid", "netbox-synthetic"))
    save_unifi_config(path, UniFiConfig("https://console.invalid", "unifi-synthetic"))

    def unavailable(config):
        return ConnectionResult(ConnectionState.OFFLINE, "Synthetic NetBox failure.")

    window = MainWindow(path, pool, unavailable, unifi_checker=unifi_online)
    qtbot.addWidget(window)
    qtbot.waitUntil(lambda: window.netbox.state.text() == "Offline")
    qtbot.waitUntil(lambda: window.unifi.state.text() == "Online")
    assert window.unifi.server_version.text() == "10.6.100"
    assert window.unifi.selected_site.text() == "Default"
    assert window.check_action.isEnabled()


def test_invalid_netbox_section_does_not_block_unifi(qtbot, tmp_path, pool):
    path = tmp_path / "config.toml"
    path.write_text('[netbox]\ntimeout = "invalid"\n')
    save_unifi_config(path, UniFiConfig("https://console.invalid", "unifi-synthetic"))
    window = MainWindow(path, pool, unifi_checker=unifi_online)
    qtbot.addWidget(window)
    qtbot.waitUntil(lambda: window.unifi.state.text() == "Online")
    assert window.netbox.state.text() == "Error"


def test_unifi_settings_cancel_preserves_saved_values(qtbot, tmp_path, pool):
    path = tmp_path / "config.toml"
    config = UniFiConfig("https://console.invalid", "original-synthetic")
    save_unifi_config(path, config)
    widget = SettingsDialog(
        path,
        NetBoxConfig(),
        pool,
        online,
        unifi_config=config,
        unifi_checker=unifi_online,
    )
    qtbot.addWidget(widget)
    widget.unifi.token.setText("unsaved-synthetic")
    widget.reject()
    assert load_unifi_config(path) == config


def test_settings_save_persists_delete_scope_behavior(qtbot, tmp_path, pool):
    path = tmp_path / "config.toml"
    widget = SettingsDialog(
        path,
        NetBoxConfig("https://netbox.invalid", "netbox-synthetic"),
        pool,
        online,
        unifi_config=UniFiConfig("https://console.invalid", "unifi-synthetic"),
        unifi_checker=unifi_online,
    )
    qtbot.addWidget(widget)
    widget.include_all_netbox_delete_candidates.setChecked(True)
    widget.default_device_role_name.setText("Network Device")
    widget.save()

    assert widget.result() == QDialog.DialogCode.Accepted
    assert widget.saved_behavior_config == BehaviorConfig(
        include_all_netbox_delete_candidates=True,
        default_device_role_name="Network Device",
    )
    assert load_behavior_config(path) == BehaviorConfig(
        include_all_netbox_delete_candidates=True,
        default_device_role_name="Network Device",
    )


def test_old_unifi_result_cannot_replace_new_settings(qtbot, tmp_path, pool):
    release = Event()
    running = Event()

    def checker(config):
        if config.url == "https://old.invalid":
            running.set()
            assert release.wait(5)
            return ConnectionResult(ConnectionState.UNAUTHORIZED, "Old result")
        return unifi_online(config)

    window = MainWindow(
        tmp_path / "config.toml", pool, open_first_run=False, unifi_checker=checker
    )
    qtbot.addWidget(window)
    try:
        window.unifi.apply_config(UniFiConfig("https://old.invalid", "old-synthetic"))
        qtbot.waitUntil(running.is_set)
        window.unifi.apply_config(UniFiConfig("https://new.invalid", "new-synthetic"))
    finally:
        release.set()
    qtbot.waitUntil(lambda: window.unifi.state.text() == "Online")
    assert window.unifi.endpoint.text() == "https://new.invalid"
    assert window.netbox.state.text() == "Unconfigured"


def test_close_waits_for_both_connection_workers(qtbot, tmp_path, pool):
    release_netbox = Event()
    release_unifi = Event()
    started_netbox = Event()
    started_unifi = Event()

    def netbox_check(config):
        started_netbox.set()
        assert release_netbox.wait(5)
        return online(config)

    def unifi_check(config):
        started_unifi.set()
        assert release_unifi.wait(5)
        return unifi_online(config)

    window = MainWindow(
        tmp_path / "config.toml",
        pool,
        netbox_check,
        open_first_run=False,
        unifi_checker=unifi_check,
    )
    qtbot.addWidget(window)
    window.show()
    try:
        window.netbox.apply_config(
            NetBoxConfig("https://netbox.invalid", "test-netbox")
        )
        window.unifi.apply_config(UniFiConfig("https://console.invalid", "test-unifi"))
        qtbot.waitUntil(lambda: started_netbox.is_set() and started_unifi.is_set())
        window.close()
        release_netbox.set()
        qtbot.waitUntil(lambda: not window.netbox.runner.busy)
        assert window.isVisible()
        assert window.unifi.runner.busy
    finally:
        release_netbox.set()
        release_unifi.set()
    qtbot.waitUntil(lambda: not window.isVisible())


def test_inventory_preview_requires_configured_connections(qtbot, tmp_path, pool):
    window = MainWindow(tmp_path / "config.toml", pool, open_first_run=False)
    qtbot.addWidget(window)
    window.show()

    window.refresh_inventory_preview()

    assert window.preview_status.text() == "Unconfigured"
    assert "Configure NetBox and UniFi Network" in window.preview_plan.text()


def test_inventory_preview_finished_updates_visible_summary(qtbot, tmp_path, pool):
    window = MainWindow(tmp_path / "config.toml", pool, open_first_run=False)
    qtbot.addWidget(window)
    window.show()

    window.inventory_preview_finished(
        InventoryPreviewResult(
            status="Ready",
            details="Synthetic summary.",
            netbox_devices=12,
            unifi_devices=10,
            matched_devices=8,
            unmatched_unifi=2,
            unmatched_netbox=4,
            conflicts=1,
            preview_rows=6,
            executable_operations=5,
            last_updated="2026-11-01T14:00:00+00:00",
            detail_lines=(
                "Match unifi:a -> netbox:1 (identity)",
                "Plan #1 create_device create:unifi:a",
            ),
        )
    )

    assert window.preview_status.text() == "Ready"
    assert "NetBox: 12 | UniFi: 10" in window.preview_counts.text()
    assert "Matched: 8" in window.preview_matches.text()
    assert "Executable operations: 5" in window.preview_plan.text()
    assert window.preview_checked_at.text() == "2026-11-01T14:00:00+00:00"
    assert window.preview_detail_list.count() == 2
    assert "Match unifi:a -> netbox:1" in window.preview_detail_text.text()
    window.preview_detail_list.setCurrentRow(1)
    assert "Plan #1 create_device create:unifi:a" in window.preview_detail_text.text()


def test_inventory_preview_enables_execute_when_plan_is_executable(
    qtbot, tmp_path, pool
):
    window = MainWindow(tmp_path / "config.toml", pool, open_first_run=False)
    qtbot.addWidget(window)
    window.show()

    netbox = InventorySnapshot(
        source=InventorySource.NETBOX,
        captured_at="2026-11-01T10:00:00+00:00",
        devices=(),
    )
    unifi = InventorySnapshot(
        source=InventorySource.UNIFI_NETWORK,
        captured_at="2026-11-01T10:00:00+00:00",
        devices=(InventoryDevice(source_id="a", name="switch-a", site="HQ"),),
    )
    dedup = deduplicate_inventory(netbox, unifi)
    diff = build_difference_preview(netbox, unifi, dedup)
    change = build_change_preview(diff)
    plan = build_write_plan(diff, change)

    window.inventory_preview_finished(
        InventoryPreviewResult(
            status="Ready",
            details="Synthetic summary.",
            rows=(
                InventoryPreviewRow(
                    device_key="create:unifi:a",
                    action="create",
                    source_label="switch-a",
                    target_label="",
                    selected_fields="name, site",
                    executable="Yes",
                ),
            ),
            difference_preview=diff,
            write_plan=plan,
        )
    )

    assert window.execute_plan_button.isEnabled()


def test_execute_write_plan_starts_runner_after_confirmation(
    qtbot, tmp_path, pool, monkeypatch
):
    window = MainWindow(tmp_path / "config.toml", pool, open_first_run=False)
    qtbot.addWidget(window)
    window.show()

    netbox = InventorySnapshot(
        source=InventorySource.NETBOX,
        captured_at="2026-11-01T10:00:00+00:00",
        devices=(),
    )
    unifi = InventorySnapshot(
        source=InventorySource.UNIFI_NETWORK,
        captured_at="2026-11-01T10:00:00+00:00",
        devices=(InventoryDevice(source_id="a", name="switch-a", site="HQ"),),
    )
    dedup = deduplicate_inventory(netbox, unifi)
    diff = build_difference_preview(netbox, unifi, dedup)
    change = build_change_preview(diff)
    plan = build_write_plan(diff, change)

    window.current_difference_preview = diff
    window.current_write_plan = plan

    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    started = {}

    def fake_start(
        netbox_config,
        behavior,
        difference_preview,
        write_plan,
        role_overrides,
        site_overrides,
        status_overrides,
        *,
        dry_run,
    ):
        started["called"] = True
        started["dry_run"] = dry_run
        started["plan"] = write_plan
        started["role_overrides"] = role_overrides
        started["site_overrides"] = site_overrides
        started["status_overrides"] = status_overrides
        return True

    monkeypatch.setattr(window.write_runner, "start", fake_start)
    window.dry_run_only.setChecked(True)

    window.execute_write_plan_from_preview()

    assert started["called"] is True
    assert started["dry_run"] is True
    assert started["plan"] == plan
    assert isinstance(started["role_overrides"], dict)
    assert isinstance(started["site_overrides"], dict)
    assert isinstance(started["status_overrides"], dict)


def test_write_execution_finished_updates_preview_details(qtbot, tmp_path, pool):
    window = MainWindow(tmp_path / "config.toml", pool, open_first_run=False)
    qtbot.addWidget(window)
    window.show()

    window.write_execution_finished(
        WriteExecutionGuiResult(
            status="Applied",
            details="Write execution finished: 1 success, 0 failed, 0 skipped.",
            detail_lines=("Write #1 update_device: success Updated device in NetBox.",),
        )
    )

    assert window.preview_status.text() == "Applied"
    assert "1 success" in window.preview_plan.text()
    assert window.preview_detail_list.count() == 1


def test_inventory_preview_finished_shows_fallback_details_for_partial(
    qtbot, tmp_path, pool
):
    window = MainWindow(tmp_path / "config.toml", pool, open_first_run=False)
    qtbot.addWidget(window)
    window.show()

    window.inventory_preview_finished(
        InventoryPreviewResult(
            status="Partial",
            details="Synthetic partial refresh.",
            detail_lines=("Inventory refresh is partial; check source diagnostics.",),
        )
    )

    assert window.preview_detail_list.count() == 1
    assert "partial" in window.preview_detail_text.text().lower()


def test_inventory_preview_copy_selected_highlight(qtbot, tmp_path, pool):
    window = MainWindow(tmp_path / "config.toml", pool, open_first_run=False)
    qtbot.addWidget(window)
    window.show()

    window.inventory_preview_finished(
        InventoryPreviewResult(
            status="Ready",
            details="Synthetic summary.",
            detail_lines=("Line A", "Line B"),
        )
    )
    window.preview_detail_list.setCurrentRow(1)
    window.copy_selected_highlight()

    assert QApplication.clipboard().text() == "Line B"


def test_inventory_preview_copy_all_highlights(qtbot, tmp_path, pool):
    window = MainWindow(tmp_path / "config.toml", pool, open_first_run=False)
    qtbot.addWidget(window)
    window.show()

    window.inventory_preview_finished(
        InventoryPreviewResult(
            status="Ready",
            details="Synthetic summary.",
            detail_lines=("First", "Second", "Third"),
        )
    )
    window.copy_all_highlights()

    assert QApplication.clipboard().text() == "First\nSecond\nThird"


def test_inventory_preview_show_all_rows_dialog(qtbot, tmp_path, pool):
    window = MainWindow(tmp_path / "config.toml", pool, open_first_run=False)
    qtbot.addWidget(window)
    window.show()

    window.inventory_preview_finished(
        InventoryPreviewResult(
            status="Ready",
            details="Synthetic summary.",
            detail_lines=("Line A",),
            rows=(
                InventoryPreviewRow(
                    device_key="create:unifi:a",
                    action="create",
                    source_label="switch-a",
                    target_label="",
                    selected_fields="name, site",
                    executable="Yes",
                ),
            ),
        )
    )

    assert window.show_rows_button.isEnabled()
    window.show_preview_rows_dialog()
    assert window.preview_rows_dialog is not None
    assert window.preview_rows_dialog.isVisible()
    table = window.preview_rows_dialog.findChild(QTableWidget, "preview_rows_table")
    assert table is not None
    assert table.rowCount() == 1
    assert table.item(0, 0).text() == "create:unifi:a"
    window.preview_rows_dialog.close()


def test_inventory_preview_rows_dialog_filters(qtbot, tmp_path, pool):
    window = MainWindow(tmp_path / "config.toml", pool, open_first_run=False)
    qtbot.addWidget(window)
    window.show()

    window.inventory_preview_finished(
        InventoryPreviewResult(
            status="Ready",
            details="Synthetic summary.",
            rows=(
                InventoryPreviewRow(
                    device_key="create:unifi:a",
                    action="create",
                    source_label="switch-a",
                    target_label="",
                    selected_fields="name, site",
                    executable="Yes",
                ),
                InventoryPreviewRow(
                    device_key="unifi:b->netbox:2",
                    action="update",
                    source_label="switch-b",
                    target_label="switch-b-old",
                    selected_fields="name",
                    executable="No",
                ),
                InventoryPreviewRow(
                    device_key="target-only:netbox:3",
                    action="target_only",
                    source_label="",
                    target_label="switch-c",
                    selected_fields="",
                    executable="No",
                ),
            ),
        )
    )

    window.show_preview_rows_dialog()
    assert window.preview_rows_dialog is not None
    table = window.preview_rows_dialog.findChild(QTableWidget, "preview_rows_table")
    action_filter = window.preview_rows_dialog.findChild(
        QComboBox, "preview_rows_action_filter"
    )
    executable_filter = window.preview_rows_dialog.findChild(
        QCheckBox, "preview_rows_executable_filter"
    )
    assert table is not None
    assert action_filter is not None
    assert executable_filter is not None

    assert table.rowCount() == 3
    action_filter.setCurrentIndex(action_filter.findData("update"))
    qtbot.waitUntil(lambda: table.rowCount() == 1)
    assert table.item(0, 1).text() == "update"

    action_filter.setCurrentIndex(action_filter.findData(""))
    executable_filter.setChecked(True)
    qtbot.waitUntil(lambda: table.rowCount() == 1)
    assert table.item(0, 5).text() == "Yes"
    window.preview_rows_dialog.close()


def test_inventory_preview_rows_dialog_shows_blocked_reason(qtbot, tmp_path, pool):
    window = MainWindow(tmp_path / "config.toml", pool, open_first_run=False)
    qtbot.addWidget(window)
    window.show()

    netbox = InventorySnapshot(
        source=InventorySource.NETBOX,
        captured_at="2026-11-01T10:00:00+00:00",
        devices=(),
    )
    unifi = InventorySnapshot(
        source=InventorySource.UNIFI_NETWORK,
        captured_at="2026-11-01T10:00:00+00:00",
        devices=(InventoryDevice(source_id="a", name="switch-a", site=""),),
    )
    dedup = deduplicate_inventory(netbox, unifi)
    diff = build_difference_preview(netbox, unifi, dedup)
    change = build_change_preview(diff)
    plan = build_write_plan(diff, change)

    window.inventory_preview_finished(
        InventoryPreviewResult(
            status="Ready",
            details="Synthetic summary.",
            rows=_preview_rows(diff, change, plan),
            difference_preview=diff,
            write_plan=plan,
        )
    )

    window.show_preview_rows_dialog()
    assert window.preview_rows_dialog is not None
    table = window.preview_rows_dialog.findChild(QTableWidget, "preview_rows_table")
    assert table is not None
    assert table.rowCount() == 1
    assert table.item(0, 5).text() == "No"
    assert "create_required_identity" in table.item(0, 9).text()
    window.preview_rows_dialog.close()


def test_inventory_preview_rows_dialog_shows_create_device_type_suggestions(
    qtbot, tmp_path, pool
):
    window = MainWindow(tmp_path / "config.toml", pool, open_first_run=False)
    qtbot.addWidget(window)
    window.show()

    netbox = InventorySnapshot(
        source=InventorySource.NETBOX,
        captured_at="2026-11-01T10:00:00+00:00",
        devices=(),
        device_types=(
            InventoryDeviceType(
                source_id="101",
                manufacturer="Ubiquiti",
                model="USW-Pro-24",
            ),
        ),
    )
    unifi = InventorySnapshot(
        source=InventorySource.UNIFI_NETWORK,
        captured_at="2026-11-01T10:00:00+00:00",
        devices=(
            InventoryDevice(
                source_id="a",
                name="switch-a",
                manufacturer="Ubiquiti",
                model="USW-Pro-24",
                site="HQ",
            ),
        ),
    )
    dedup = deduplicate_inventory(netbox, unifi)
    diff = build_difference_preview(netbox, unifi, dedup)
    change = build_change_preview(diff)
    plan = build_write_plan(diff, change)

    window.inventory_preview_finished(
        InventoryPreviewResult(
            status="Ready",
            details="Synthetic summary.",
            rows=_preview_rows(
                diff,
                change,
                plan,
                suggestions=suggest_device_types_for_unmatched(dedup, netbox, unifi),
            ),
            difference_preview=diff,
            write_plan=plan,
        )
    )

    window.show_preview_rows_dialog()
    assert window.preview_rows_dialog is not None
    table = window.preview_rows_dialog.findChild(QTableWidget, "preview_rows_table")
    assert table is not None
    assert table.rowCount() == 1
    assert "Ubiquiti USW-Pro-24" in table.item(0, 10).text()
    window.preview_rows_dialog.close()


def test_inventory_preview_rows_dialog_shows_role_dropdown_for_create_rows(
    qtbot, tmp_path, pool
):
    window = MainWindow(tmp_path / "config.toml", pool, open_first_run=False)
    qtbot.addWidget(window)
    window.show()

    window.inventory_preview_finished(
        InventoryPreviewResult(
            status="Ready",
            details="Synthetic summary.",
            rows=(
                InventoryPreviewRow(
                    device_key="create:unifi:a",
                    action="create",
                    source_label="switch-a",
                    target_label="",
                    selected_fields="name, site",
                    executable="Yes",
                ),
            ),
            netbox_device_statuses=("active", "planned"),
            netbox_device_roles=("Network Device", "Wireless"),
            netbox_sites=("HQ", "Branch"),
        )
    )

    window.show_preview_rows_dialog()
    assert window.preview_rows_dialog is not None
    table = window.preview_rows_dialog.findChild(QTableWidget, "preview_rows_table")
    assert table is not None

    status_widget = table.cellWidget(0, 6)
    assert isinstance(status_widget, QComboBox)
    assert status_widget.count() == 2
    assert status_widget.itemText(0) == "active"
    assert status_widget.itemText(1) == "planned"

    site_widget = table.cellWidget(0, 7)
    assert isinstance(site_widget, QComboBox)
    assert site_widget.count() == 2
    assert site_widget.itemText(0) == "HQ"
    assert site_widget.itemText(1) == "Branch"

    role_widget = table.cellWidget(0, 8)
    assert isinstance(role_widget, QComboBox)
    assert role_widget.count() == 2
    assert role_widget.itemText(0) == "Network Device"
    assert role_widget.itemText(1) == "Wireless"
    window.preview_rows_dialog.close()


def test_inventory_preview_rows_dialog_execute_selected_row(
    qtbot, tmp_path, pool, monkeypatch
):
    window = MainWindow(tmp_path / "config.toml", pool, open_first_run=False)
    qtbot.addWidget(window)
    window.show()

    netbox = InventorySnapshot(
        source=InventorySource.NETBOX,
        captured_at="2026-11-01T10:00:00+00:00",
        devices=(
            InventoryDevice(source_id="1", name="switch-a", serial="S1", site="HQ"),
        ),
    )
    unifi = InventorySnapshot(
        source=InventorySource.UNIFI_NETWORK,
        captured_at="2026-11-01T10:00:00+00:00",
        devices=(
            InventoryDevice(source_id="a", name="switch-a", serial="S1-new", site="HQ"),
            InventoryDevice(source_id="b", name="switch-b", site="HQ"),
        ),
    )
    dedup = deduplicate_inventory(netbox, unifi)
    diff = build_difference_preview(netbox, unifi, dedup)
    change = build_change_preview(diff)
    plan = build_write_plan(diff, change)

    window.inventory_preview_finished(
        InventoryPreviewResult(
            status="Ready",
            details="Synthetic summary.",
            rows=_preview_rows(diff, change, plan),
            difference_preview=diff,
            write_plan=plan,
        )
    )

    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    started = {}

    def fake_start(
        netbox_config,
        behavior,
        difference_preview,
        write_plan,
        role_overrides,
        site_overrides,
        status_overrides,
        *,
        dry_run,
    ):
        started["called"] = True
        started["count"] = len(write_plan.operations)
        started["device_key"] = write_plan.operations[0].device_key
        started["role_overrides"] = role_overrides
        started["site_overrides"] = site_overrides
        started["status_overrides"] = status_overrides
        return True

    monkeypatch.setattr(window.write_runner, "start", fake_start)

    window.show_preview_rows_dialog()
    assert window.preview_rows_dialog is not None
    table = window.preview_rows_dialog.findChild(QTableWidget, "preview_rows_table")
    execute_button = window.preview_rows_dialog.findChild(
        QPushButton, "preview_rows_execute_selected"
    )
    assert table is not None
    assert execute_button is not None

    # Select first executable row and trigger single-row execution.
    table.setCurrentCell(0, 0)
    execute_button.click()

    assert started["called"] is True
    assert started["count"] == 1
    assert started["device_key"] == table.item(0, 0).text()
    assert isinstance(started["role_overrides"], dict)
    assert isinstance(started["site_overrides"], dict)
    assert isinstance(started["status_overrides"], dict)
    window.preview_rows_dialog.close()


def test_preview_rows_uses_change_executable_state_without_plan_devices():
    netbox = InventorySnapshot(
        source=InventorySource.NETBOX,
        captured_at="2026-11-01T10:00:00+00:00",
        devices=(),
    )
    unifi = InventorySnapshot(
        source=InventorySource.UNIFI_NETWORK,
        captured_at="2026-11-01T10:00:00+00:00",
        devices=(InventoryDevice(source_id="a", name="switch-a", site="HQ"),),
    )

    dedup = deduplicate_inventory(netbox, unifi)
    diff = build_difference_preview(netbox, unifi, dedup)
    change = build_change_preview(diff)
    plan = build_write_plan(diff, change)

    rows = _preview_rows(diff, change, plan)

    assert len(rows) == 1
    assert rows[0].action == "create"
    assert rows[0].executable == "Yes"


def test_delete_scope_filters_unmatched_netbox_by_unifi_site_by_default():
    netbox = InventorySnapshot(
        source=InventorySource.NETBOX,
        captured_at="2026-11-01T10:00:00+00:00",
        devices=(
            InventoryDevice(source_id="1", name="nb-hq", site="HQ"),
            InventoryDevice(source_id="2", name="nb-branch", site="Branch"),
        ),
    )
    unifi = InventorySnapshot(
        source=InventorySource.UNIFI_NETWORK,
        captured_at="2026-11-01T10:00:00+00:00",
        devices=(InventoryDevice(source_id="a", name="uf-a", site="HQ"),),
    )

    dedup = deduplicate_inventory(netbox, unifi)
    scoped, hidden = _scope_unmatched_netbox_for_delete(
        dedup,
        netbox,
        unifi,
        include_all_netbox_delete_candidates=False,
    )

    assert len(dedup.unmatched_netbox) == 2
    assert scoped.unmatched_netbox == ("netbox:1",)
    assert hidden == 1


def test_delete_scope_can_include_all_unmatched_netbox_devices():
    netbox = InventorySnapshot(
        source=InventorySource.NETBOX,
        captured_at="2026-11-01T10:00:00+00:00",
        devices=(
            InventoryDevice(source_id="1", name="nb-hq", site="HQ"),
            InventoryDevice(source_id="2", name="nb-branch", site="Branch"),
        ),
    )
    unifi = InventorySnapshot(
        source=InventorySource.UNIFI_NETWORK,
        captured_at="2026-11-01T10:00:00+00:00",
        devices=(InventoryDevice(source_id="a", name="uf-a", site="HQ"),),
    )

    dedup = deduplicate_inventory(netbox, unifi)
    scoped, hidden = _scope_unmatched_netbox_for_delete(
        dedup,
        netbox,
        unifi,
        include_all_netbox_delete_candidates=True,
    )

    assert scoped.unmatched_netbox == dedup.unmatched_netbox
    assert hidden == 0


def test_single_main_check_action_checks_both_services(qtbot, tmp_path, pool):
    checked = []

    def netbox_check(config):
        checked.append("netbox")
        return online(config)

    def unifi_check(config):
        checked.append("unifi")
        return unifi_online(config)

    window = MainWindow(
        tmp_path / "config.toml",
        pool,
        netbox_check,
        open_first_run=False,
        unifi_checker=unifi_check,
    )
    qtbot.addWidget(window)
    toolbar = window.findChild(QToolBar)
    assert [action.text() for action in toolbar.actions()] == [
        "Check Connections",
        "Refresh Inventory Preview",
        "Settings",
    ]
    window.check_action.trigger()
    assert not window.check_action.isEnabled()
    qtbot.waitUntil(lambda: window.check_action.isEnabled())
    assert sorted(checked) == ["netbox", "unifi"]


def test_unified_settings_action_saves_and_rechecks_both(
    qtbot, tmp_path, pool, monkeypatch
):
    path = tmp_path / "config.toml"
    checked = []

    def checker(config):
        checked.append(config)
        return (
            unifi_online(config) if isinstance(config, UniFiConfig) else online(config)
        )

    class AcceptedSettings(SettingsDialog):
        def exec(self):
            self.netbox.url.setText("https://netbox.invalid")
            self.netbox.token.setText("new-netbox-synthetic")
            self.unifi.url.setText("https://console.invalid")
            self.unifi.token.setText("new-unifi-synthetic")
            self.save()
            return self.result()

    monkeypatch.setattr("unifi2netbox.gui.SettingsDialog", AcceptedSettings)
    window = MainWindow(
        path, pool, checker, open_first_run=False, unifi_checker=checker
    )
    qtbot.addWidget(window)
    window.settings_action.trigger()
    qtbot.waitUntil(lambda: len(checked) == 2 and window.check_action.isEnabled())
    assert load_config(path).token == "new-netbox-synthetic"
    assert load_unifi_config(path).token == "new-unifi-synthetic"
    assert window.netbox.state.text() == "Online"
    assert window.unifi.state.text() == "Online"


def test_unified_settings_checks_both_unsaved_values(qtbot, tmp_path, pool):
    received = []

    def netbox_check(config):
        received.append(config)
        return ConnectionResult(ConnectionState.OFFLINE, "Synthetic failure.")

    def unifi_check(config):
        received.append(config)
        return unifi_online(config)

    path = tmp_path / "config.toml"
    widget = SettingsDialog(
        path, NetBoxConfig(), pool, netbox_check, unifi_checker=unifi_check
    )
    qtbot.addWidget(widget)
    widget.netbox.url.setText("https://netbox.invalid")
    widget.netbox.token.setText("unsaved-netbox-synthetic")
    widget.unifi.url.setText("https://console.invalid")
    widget.unifi.token.setText("unsaved-unifi-synthetic")
    widget.test_button.click()
    qtbot.waitUntil(lambda: not widget.busy)
    assert {config.token for config in received} == {
        "unsaved-netbox-synthetic",
        "unsaved-unifi-synthetic",
    }
    assert "NetBox: Offline" in widget.outcome.text()
    assert "UniFi Network: Online" in widget.outcome.text()
    assert not path.exists()


def test_invalid_unifi_settings_prevent_either_section_from_saving(
    qtbot, tmp_path, pool
):
    path = tmp_path / "config.toml"
    netbox = NetBoxConfig("https://netbox.invalid", "old-netbox-synthetic")
    unifi = UniFiConfig("https://console.invalid", "old-unifi-synthetic")
    save_config(path, netbox)
    save_unifi_config(path, unifi)
    previous = path.read_bytes()
    widget = SettingsDialog(
        path, netbox, pool, online, unifi_config=unifi, unifi_checker=unifi_online
    )
    qtbot.addWidget(widget)
    widget.netbox.token.setText("replacement-netbox-synthetic")
    widget.unifi.url.setText("invalid")
    widget.save()
    assert widget.saved_config is None
    assert widget.saved_unifi_config is None
    assert "explicit" in widget.outcome.text()
    assert path.read_bytes() == previous


def test_settings_validation_failure_does_not_skip_other_check(qtbot, tmp_path, pool):
    called = []

    def netbox_check(config):
        called.append("netbox")
        return online(config)

    def unifi_check(config):
        called.append("unifi")
        return unifi_online(config)

    widget = SettingsDialog(
        tmp_path / "config.toml",
        NetBoxConfig(),
        pool,
        netbox_check,
        unifi_checker=unifi_check,
    )
    qtbot.addWidget(widget)
    widget.netbox.url.setText("invalid")
    widget.unifi.url.setText("https://console.invalid")
    widget.unifi.token.setText("synthetic-unifi")
    widget.test_connections()
    qtbot.waitUntil(lambda: not widget.busy)
    assert called == ["unifi"]
    assert "NetBox: Error" in widget.outcome.text()
    assert "UniFi Network: Online" in widget.outcome.text()


def test_unified_settings_close_waits_for_both_checks(qtbot, tmp_path, pool):
    release_netbox = Event()
    release_unifi = Event()
    started_netbox = Event()
    started_unifi = Event()

    def netbox_check(config):
        started_netbox.set()
        assert release_netbox.wait(5)
        return online(config)

    def unifi_check(config):
        started_unifi.set()
        assert release_unifi.wait(5)
        return unifi_online(config)

    widget = SettingsDialog(
        tmp_path / "config.toml",
        NetBoxConfig(),
        pool,
        netbox_check,
        unifi_checker=unifi_check,
    )
    qtbot.addWidget(widget)
    widget.show()
    try:
        widget.test_connections()
        qtbot.waitUntil(lambda: started_netbox.is_set() and started_unifi.is_set())
        assert not widget.buttons.isEnabled()
        assert not widget.tabs.isEnabled()
        widget.reject()
        release_netbox.set()
        qtbot.waitUntil(lambda: not widget.netbox.runner.busy)
        assert widget.isVisible()
        assert not widget.buttons.isEnabled()
    finally:
        release_netbox.set()
        release_unifi.set()
    qtbot.waitUntil(lambda: not widget.isVisible())
