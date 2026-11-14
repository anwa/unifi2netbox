import json
from threading import Event

import pytest
from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QLabel,
    QLineEdit,
    QPushButton,
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
    MainWindow,
    SettingsDialog,
    _find_unifi_raw_device,
    _unifi_source_id_from_device_key,
)
from unifi2netbox.gui_review import ConfirmDialog
from unifi2netbox.inventory import (
    InventoryDevice,
    InventoryDeviceRole,
    InventoryDeviceType,
    InventorySite,
    InventorySnapshot,
    InventorySource,
)
from unifi2netbox.matching import (
    deduplicate_inventory,
    suggest_device_types_for_unmatched,
)
from unifi2netbox.netbox import ConnectionResult, ConnectionState
from unifi2netbox.pipeline import (
    InventoryPreviewResult,
    WriteExecutionReport,
    WriteOutcome,
    preview_rows,
    scope_unmatched_netbox_for_delete,
)
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
    widget.netbox_site_name.setText("Home")
    widget.save()

    assert widget.result() == QDialog.DialogCode.Accepted
    assert widget.saved_behavior_config == BehaviorConfig(
        include_all_netbox_delete_candidates=True,
        default_device_role_name="Network Device",
        netbox_site_name="Home",
    )
    assert load_behavior_config(path) == BehaviorConfig(
        include_all_netbox_delete_candidates=True,
        default_device_role_name="Network Device",
        netbox_site_name="Home",
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


def preview_result(role_catalog=("Access Point", "Switch")):
    netbox = InventorySnapshot(
        source=InventorySource.NETBOX,
        captured_at="2026-11-14T10:00:00+00:00",
        devices=(
            InventoryDevice(source_id="1", name="sw-a", serial="OLD", site="Home"),
            InventoryDevice(source_id="2", name="sw-b", serial="S2", site="Home"),
        ),
        device_types=(
            InventoryDeviceType("101", "Ubiquiti", "U6 Lite", "U6-Lite"),
            InventoryDeviceType("102", "Ubiquiti", "AC Professional", "UAP-AC-PRO"),
        ),
        device_roles=tuple(
            InventoryDeviceRole(str(i), name) for i, name in enumerate(role_catalog)
        ),
        sites=(InventorySite("7", "Home"),),
    )
    unifi = InventorySnapshot(
        source=InventorySource.UNIFI_NETWORK,
        captured_at="2026-11-14T10:00:00+00:00",
        devices=(
            InventoryDevice(source_id="a", name="sw-a", serial="NEW", site="Home"),
            InventoryDevice(source_id="b", name="sw-b", serial="S2", site="Home"),
            InventoryDevice(
                source_id="c",
                name="ap-1",
                manufacturer="Ubiquiti",
                model="U6 Lite",
                site="Home",
            ),
            InventoryDevice(
                source_id="d",
                name="ap-2",
                manufacturer="Ubiquiti",
                model="AC Pro",
                site="Home",
            ),
        ),
        unifi_raw_devices=({"id": "c", "name": "ap-1"},),
    )
    dedup = deduplicate_inventory(netbox, unifi)
    suggestions = suggest_device_types_for_unmatched(dedup, netbox, unifi)
    sites = frozenset({"Home"})
    diff = build_difference_preview(netbox, unifi, dedup, netbox_sites=sites)
    change = build_change_preview(diff)
    plan = build_write_plan(diff, change, netbox_sites=sites)
    return InventoryPreviewResult(
        status="Ready",
        details="NetBox refresh succeeded.",
        last_updated="2026-11-14T10:00:05+00:00",
        detail_lines=("Unmatched UniFi observations: 2",),
        rows=preview_rows(diff, change, plan, suggestions=suggestions),
        netbox_device_types=(
            ("101", "Ubiquiti", "U6 Lite"),
            ("102", "Ubiquiti", "AC Professional"),
        ),
        netbox_device_roles=tuple(role_catalog),
        netbox_sites=("Home",),
        netbox_device_statuses=("active", "planned"),
        unifi_api_feedback=({"endpoint": "info", "params": {}, "payload": {}},),
        unifi_raw_devices=unifi.unifi_raw_devices,
        difference_preview=diff,
        write_plan=plan,
    )


def review_window(qtbot, tmp_path, pool, result=None):
    window = MainWindow(tmp_path / "config.toml", pool, open_first_run=False)
    qtbot.addWidget(window)
    window.show()
    window.inventory_preview_finished(result or preview_result())
    return window


def table_names(window):
    model = window.table_model
    return [model.data(model.index(row, 1)) for row in range(model.rowCount())]


def select_row(window, name):
    row = table_names(window).index(name)
    window.table.selectRow(row)
    return window.table_model.key_at(row)


def fake_runner(monkeypatch, window):
    started = {}

    def fake_start(
        netbox_config,
        behavior,
        difference_preview,
        write_plan,
        role_overrides,
        site_overrides,
        status_overrides,
        device_type_overrides,
        *,
        dry_run,
    ):
        started.update(
            plan=write_plan,
            dry_run=dry_run,
            role=role_overrides,
            site=site_overrides,
            status=status_overrides,
            type=device_type_overrides,
        )
        return True

    monkeypatch.setattr(window.write_runner, "start", fake_start)
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    return started


def test_refresh_requires_configured_connections(qtbot, tmp_path, pool):
    window = MainWindow(tmp_path / "config.toml", pool, open_first_run=False)
    qtbot.addWidget(window)
    window.show()

    window.refresh_inventory_preview()

    assert "Configure NetBox and UniFi Network" in window.banner_text()
    assert window.pages.currentIndex() == 0
    assert window.empty_button.text() == "Open settings"


def test_preview_shows_cards_filters_table_and_detail(qtbot, tmp_path, pool):
    window = review_window(qtbot, tmp_path, pool)

    assert window.pages.currentIndex() == 1
    assert window.cards["create"].count == 2
    assert window.cards["update"].count == 1
    assert window.cards["in_sync"].count == 1
    assert window.segments["all"].text() == "All 4"
    assert table_names(window) == ["sw-a", "sw-b", "ap-1", "ap-2"]
    title = window.detail.findChild(QLabel, "detailTitle")
    assert title is not None and title.text() == "sw-a"
    assert window.apply_bar.isVisible()
    assert "Last refresh" in window.statusBar().currentMessage()


def test_cards_and_search_filter_the_table(qtbot, tmp_path, pool):
    window = review_window(qtbot, tmp_path, pool)

    window.cards["create"].click()
    assert table_names(window) == ["ap-1", "ap-2"]
    assert window.segments["create"].isChecked()

    window.search.setText("ap-2")
    assert table_names(window) == ["ap-2"]

    window.search.clear()
    window.set_filter("in_sync")
    assert table_names(window) == ["sw-b"]


def test_row_checkbox_updates_selection_and_apply_button(qtbot, tmp_path, pool):
    window = review_window(qtbot, tmp_path, pool)
    assert window.execute_plan_button.text() == "Apply 3 changes..."
    assert window.selection_label.text() == "3 of 3 devices selected"

    row = table_names(window).index("ap-1")
    index = window.table_model.index(row, 0)
    window.table_model.setData(
        index, Qt.CheckState.Unchecked.value, Qt.ItemDataRole.CheckStateRole
    )

    assert window.execute_plan_button.text() == "Apply 2 changes..."
    assert window.selection_label.text() == "2 of 3 devices selected"
    window.select_none_button.click()
    assert not window.execute_plan_button.isEnabled()
    window.select_all_button.click()
    assert window.execute_plan_button.text() == "Apply 3 changes..."


def test_dry_run_changes_apply_button_text(qtbot, tmp_path, pool):
    window = review_window(qtbot, tmp_path, pool)

    window.dry_run_only.setChecked(True)

    assert window.execute_plan_button.text() == "Dry run 3 changes..."


def test_detail_field_checkbox_controls_update(qtbot, tmp_path, pool):
    window = review_window(qtbot, tmp_path, pool)
    key = select_row(window, "sw-a")

    box = window.detail.findChild(QCheckBox, "field_serial")
    assert box is not None and box.isChecked()
    box.setChecked(False)

    assert key not in {op.device_key for op in window.review.plan.operations}
    assert window.execute_plan_button.text() == "Apply 2 changes..."


def test_detail_create_choices_update_review_state(qtbot, tmp_path, pool):
    window = review_window(qtbot, tmp_path, pool)
    key = select_row(window, "ap-1")

    assert window.review.type_by_key[key] == "101"
    assert window.create_device_type_by_device_key[key] == "101"
    role = window.detail.findChild(QComboBox, "choiceRole")
    assert role is not None
    role.setCurrentText("Switch")
    assert window.review.role_by_key[key] == "Switch"

    type_combo = window.detail.findChild(QComboBox, "choiceType")
    type_combo.setCurrentIndex(type_combo.findData("102"))
    assert window.review.type_by_key[key] == "102"
    row = table_names(window).index("ap-1")
    assert window.table_model.data(window.table_model.index(row, 4)) == (
        "AC Professional"
    )


def test_apply_runs_selected_plan_with_create_choices(
    qtbot, tmp_path, pool, monkeypatch
):
    window = review_window(qtbot, tmp_path, pool)
    started = fake_runner(monkeypatch, window)
    window.dry_run_only.setChecked(True)

    window.execute_plan_button.click()

    assert started["dry_run"] is True
    assert len(started["plan"].operations) == 3
    assert set(started["type"].values()) == {"101", "102"}
    assert set(started["role"].values()) == {"Access Point"}
    assert "Running dry run" in window.banner_text()


def test_apply_this_device_runs_single_operation(qtbot, tmp_path, pool, monkeypatch):
    window = review_window(qtbot, tmp_path, pool)
    started = fake_runner(monkeypatch, window)
    key = select_row(window, "ap-2")

    window.detail.findChild(QPushButton, "detailApply").click()

    assert [op.device_key for op in started["plan"].operations] == [key]
    assert started["dry_run"] is False


def test_confirm_dialog_blocks_creates_without_role(qtbot, tmp_path, pool):
    window = review_window(qtbot, tmp_path, pool, preview_result(role_catalog=()))

    confirm = ConfirmDialog(window.review, window.review.plan, dry_run=False)
    qtbot.addWidget(confirm)

    assert not confirm.confirm_button.isEnabled()
    assert any("device role" in reason for reason in confirm.blockers)
    assert window.cards["attention"].count == 2


def test_write_results_are_shown_per_row(qtbot, tmp_path, pool):
    window = review_window(qtbot, tmp_path, pool)
    key = select_row(window, "ap-1")

    window.write_execution_finished(
        WriteExecutionReport(
            status="Applied",
            details="Write execution finished: 1 success, 0 failed, 0 skipped.",
            outcomes=(WriteOutcome(key, "success", "Created device in NetBox."),),
        )
    )

    assert "1 success" in window.banner_text()
    assert "Refresh to compare" in window.banner_text()
    assert window.findChild(QPushButton, "bannerRefresh") is not None
    row = table_names(window).index("ap-1")
    assert window.table_model.data(window.table_model.index(row, 5)) == "Written"


def test_partial_refresh_without_preview_shows_banner(qtbot, tmp_path, pool):
    window = MainWindow(tmp_path / "config.toml", pool, open_first_run=False)
    qtbot.addWidget(window)
    window.show()

    window.inventory_preview_finished(
        InventoryPreviewResult(
            status="Partial",
            details="UniFi refresh failed.",
            detail_lines=("UniFi refresh failed; showing cached NetBox data.",),
        )
    )

    assert window.pages.currentIndex() == 0
    assert "Partial: UniFi refresh failed; showing cached" in window.banner_text()


def test_copy_device_details_and_summary(qtbot, tmp_path, pool):
    window = review_window(qtbot, tmp_path, pool)
    select_row(window, "sw-a")

    window.detail.findChild(QPushButton, "detailCopy").click()
    copied = QApplication.clipboard().text()
    assert copied.startswith("sw-a")
    assert "Serial number: NetBox=OLD UniFi=NEW" in copied

    window.copy_summary_action.trigger()
    summary = QApplication.clipboard().text()
    assert "New devices: 2" in summary
    assert "Unmatched UniFi observations: 2" in summary


def test_unifi_exports_write_json(qtbot, tmp_path, pool, monkeypatch):
    window = review_window(qtbot, tmp_path, pool)
    target = tmp_path / "dump.json"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(target), "")
    )

    window.export_action.trigger()
    assert json.loads(target.read_text(encoding="utf-8"))["api_feedback"]

    select_row(window, "ap-1")
    window.detail.findChild(QPushButton, "detailExport").click()
    assert json.loads(target.read_text(encoding="utf-8"))["raw_device"]["id"] == "c"


def test_connection_chips_show_state(qtbot, tmp_path, pool):
    window = MainWindow(tmp_path / "config.toml", pool, open_first_run=False)
    qtbot.addWidget(window)

    window.netbox.show_result(online(None))

    assert "NetBox 4.7.3" in window.netbox_chip.text()
    assert window.netbox_chip.property("chip") == "success"
    window.netbox_chip.click()
    assert window.netbox_chip.popup.isVisible()
    window.netbox_chip.popup.hide()


def test_theme_follows_forced_scheme(qapp):
    from unifi2netbox import theme

    theme.apply_theme(qapp, dark=True)
    try:
        assert qapp.palette().window().color().name() == theme.DARK.window
        assert theme.tone_colors("success") == (
            theme.DARK.success,
            theme.DARK.success_soft,
        )
    finally:
        theme.apply_theme(qapp, dark=False)
    assert qapp.palette().window().color().name() == theme.LIGHT.window


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

    rows = preview_rows(diff, change, plan)

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
    scoped, hidden = scope_unmatched_netbox_for_delete(
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
    scoped, hidden = scope_unmatched_netbox_for_delete(
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
    assert window.check_action.text() == "Check connections"
    assert window.preview_action.text() == "Refresh"
    assert window.settings_action.text() == "Settings"
    window.check_action.trigger()
    assert not window.check_action.isEnabled()
    qtbot.waitUntil(lambda: window.check_action.isEnabled())


def test_unifi_source_id_is_extracted_from_preview_device_keys():
    assert _unifi_source_id_from_device_key("create:unifi_network:dev-1") == "dev-1"
    assert _unifi_source_id_from_device_key("unifi_network:dev-2->netbox:42") == "dev-2"
    assert _unifi_source_id_from_device_key("target-only:netbox:42") == ""


def test_find_unifi_raw_device_matches_id_and__id_fields():
    rows = (
        {"id": "dev-1", "name": "switch-1"},
        {"_id": "dev-2", "name": "ap-2"},
    )
    assert _find_unifi_raw_device(rows, "dev-1") == rows[0]
    assert _find_unifi_raw_device(rows, "dev-2") == rows[1]
    assert _find_unifi_raw_device(rows, "missing") is None


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


def test_theme_button_toggles_and_saves_choice(qtbot, qapp, tmp_path, pool):
    from unifi2netbox import theme
    from unifi2netbox.config import load_ui_config

    theme.apply_theme(qapp, dark=False)
    window = MainWindow(tmp_path / "config.toml", pool, open_first_run=False)
    qtbot.addWidget(window)
    try:
        assert window.theme_button.toolTip() == "Switch to dark mode"

        window.theme_button.click()
        assert theme.is_dark()
        assert qapp.palette().window().color().name() == theme.DARK.window
        assert load_ui_config(tmp_path / "config.toml").theme == "dark"
        assert window.theme_button.toolTip() == "Switch to light mode"
        assert window.theme_actions["dark"].isChecked()

        window.theme_button.click()
        assert not theme.is_dark()
        assert load_ui_config(tmp_path / "config.toml").theme == "light"

        window.theme_actions["system"].trigger()
        assert load_ui_config(tmp_path / "config.toml").theme == "system"
        assert window.theme_actions["system"].isChecked()
    finally:
        theme.apply_theme(qapp, dark=False)
