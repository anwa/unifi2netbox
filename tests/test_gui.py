from threading import Event

import pytest
from PySide6.QtCore import QThreadPool, QTimer
from PySide6.QtWidgets import QDialog, QLineEdit

from unifi2netbox.config import NetBoxConfig, load_config, save_config
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
