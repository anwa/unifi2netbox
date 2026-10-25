from threading import Event

import pytest
from PySide6.QtCore import QThreadPool, QTimer
from PySide6.QtWidgets import QDialog, QLineEdit

from unifi2netbox.config import (
    NetBoxConfig,
    UniFiConfig,
    load_config,
    load_unifi_config,
    save_config,
    save_unifi_config,
)
from unifi2netbox.connections import ConnectionRunner
from unifi2netbox.gui import MainWindow, SettingsDialog
from unifi2netbox.netbox import ConnectionResult, ConnectionState


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
    assert widget.token.echoMode() == QLineEdit.EchoMode.Password
    widget.url.setText("https://netbox.invalid/")
    widget.token.setText("synthetic-token")
    widget.verify_tls.setChecked(False)
    assert "disabled" in widget.warning.text()
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
    widget.token.setText("unsaved-token")
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
    widget.show_token.setChecked(True)
    assert widget.token.echoMode() == QLineEdit.EchoMode.Normal
    widget.show_token.setChecked(False)
    assert widget.token.echoMode() == QLineEdit.EchoMode.Password


def test_validation_and_save_errors_stay_in_dialog(qtbot, tmp_path, pool, monkeypatch):
    widget = dialog(qtbot, tmp_path, pool)
    widget.url.setText("invalid")
    widget.save()
    assert "explicit" in widget.outcome.text()
    assert widget.saved_config is None
    widget.url.setText("https://netbox.invalid")

    def fail(*args):
        from unifi2netbox.config import ConfigError

        raise ConfigError("Cannot save configuration.")

    monkeypatch.setattr("unifi2netbox.gui.save_config", fail)
    widget.save()
    assert "Cannot save" in widget.outcome.text()
    assert widget.isVisible()


def test_test_connection_uses_unsaved_values(qtbot, tmp_path, pool):
    received = []

    def checker(config):
        received.append(config)
        return online(config)

    widget = dialog(qtbot, tmp_path, pool, checker)
    widget.url.setText("https://netbox.invalid")
    widget.token.setText("unsaved-token")
    with qtbot.waitSignal(widget.runner.finished):
        widget.test_connection()
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
        widget.test_connection()
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
    widget = SettingsDialog(path, UniFiConfig(), pool, unifi_online, unifi=True)
    qtbot.addWidget(widget)
    widget.url.setText("https://console.invalid")
    widget.token.setText("unifi-synthetic")
    widget.verify_tls.setChecked(False)
    widget.site.setEditText("default")
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
    widget = SettingsDialog(path, config, pool, discover, unifi=True)
    qtbot.addWidget(widget)
    with qtbot.waitSignal(widget.runner.finished):
        widget.test_connection()
    assert not path.exists()
    assert widget.site.count() == 3
    assert widget.token.echoMode() == QLineEdit.EchoMode.Password
    widget.site.setCurrentIndex(widget.site.findData("site-two"))
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
    assert window.netbox.check_action.isEnabled()
    assert window.unifi.check_action.isEnabled()


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
    widget = SettingsDialog(path, config, pool, unifi_online, unifi=True)
    qtbot.addWidget(widget)
    widget.token.setText("unsaved-synthetic")
    widget.reject()
    assert load_unifi_config(path) == config


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
