"""Backup and restore dialogs (M15 slice 4)."""

from netbox_mem import MemNetBox, sample
from PySide6.QtCore import QThreadPool

from unifi2netbox.config import NetBoxConfig
from unifi2netbox.gui_backup import BackupDialog, RestoreDialog
from unifi2netbox.journal_store import JournalStore
from unifi2netbox.netbox_backup import create_backup, read_backup

CONFIG = NetBoxConfig(url="https://mem.example.com", token="t")


def backup_fn_for(nb):
    def run(config, **kwargs):
        return create_backup(config, session_factory=lambda c: nb, **kwargs)

    return run


def write_sample_backup(qtbot, tmp_path, source):
    dialog = BackupDialog(
        CONFIG, QThreadPool(), folder=tmp_path, backup_fn=backup_fn_for(source)
    )
    qtbot.addWidget(dialog)
    assert dialog.path_edit.text().endswith(".json")
    path = tmp_path / "netbox.json"
    dialog.path_edit.setText(str(path))
    with qtbot.waitSignal(dialog.runner.finished, timeout=10000):
        dialog.start()
    return dialog, path


def test_backup_dialog_writes_the_file(qtbot, tmp_path):
    dialog, path = write_sample_backup(qtbot, tmp_path, sample())
    assert path.is_file() and read_backup(path).total() > 10
    assert "Saved" in dialog.message.text() and "2 images" in dialog.message.text()
    assert dialog.bar.value() == dialog.bar.maximum()


def restore_dialog(qtbot, tmp_path, target, source=None):
    dialog = RestoreDialog(
        CONFIG,
        QThreadPool(),
        journal_path=tmp_path / "write-journal.sqlite3",
        backend_factory=lambda config: target,
        backup_fn=backup_fn_for(source or target),
    )
    qtbot.addWidget(dialog)
    return dialog


def test_restore_dialog_checks_then_restores_into_the_chosen_target(qtbot, tmp_path):
    source = sample()
    _backup, path = write_sample_backup(qtbot, tmp_path, source)
    target = MemNetBox()
    dialog = restore_dialog(qtbot, tmp_path, target)
    dialog.load(path)
    assert "mem.example.com" in dialog.summary.text()
    assert dialog.url.text() == CONFIG.url and dialog.token.text() == "t"
    assert not dialog.restore_button.isEnabled()

    with qtbot.waitSignal(dialog.runner.finished, timeout=10000):
        dialog.check()
    assert target.writes == []
    assert dialog.restore_button.isEnabled()
    assert dialog.results.rowCount() > 5 and "to create" in dialog.message.text()

    dialog.verify.setChecked(not dialog.verify.isChecked())  # settings changed
    assert not dialog.restore_button.isEnabled()
    dialog.verify.setChecked(not dialog.verify.isChecked())
    with qtbot.waitSignal(dialog.runner.finished, timeout=10000):
        dialog.check()

    asked = []
    dialog.confirm = lambda text: asked.append(text) or True
    with qtbot.waitSignal(dialog.runner.finished, timeout=10000):
        dialog.run()
    assert "Mode: Create missing objects" in asked[0]
    assert target.canon() == source.canon()
    assert "Read-back: verified" in dialog.message.text()
    (run,) = JournalStore(tmp_path / "write-journal.sqlite3").recent()
    assert {o.operation_type for o in run.outcomes} == {"restore_netbox"}


def test_update_mode_lists_objects_and_skips_unchecked_ones(qtbot, tmp_path):
    source = sample()
    _backup, path = write_sample_backup(qtbot, tmp_path, source)
    target = MemNetBox()
    dialog = restore_dialog(qtbot, tmp_path, target)
    dialog.load(path)
    dialog.confirm = lambda text: True
    with qtbot.waitSignal(dialog.runner.finished, timeout=10000):
        dialog.check()
    with qtbot.waitSignal(dialog.runner.finished, timeout=10000):
        dialog.run()
    site = next(iter(target.data["dcim/sites"]))
    target.data["dcim/sites"][site]["status"] = "planned"

    dialog.findChild(type(dialog.modes.buttons()[0]), "restoreMode_update").setChecked(
        True
    )
    with qtbot.waitSignal(dialog.runner.finished, timeout=10000):
        dialog.check()
    assert dialog.changes.isVisible() or dialog.changes.topLevelItemCount() == 1
    node = dialog.changes.topLevelItem(0)
    assert node.text(0) == "dcim/sites" and node.child(0).text(1) == "status"
    from PySide6.QtCore import Qt

    node.child(0).setCheckState(0, Qt.CheckState.Unchecked)  # keep "planned"
    with qtbot.waitSignal(dialog.runner.finished, timeout=10000):
        dialog.run()
    assert target.data["dcim/sites"][site]["status"] == "planned"


def test_replace_needs_the_host_name_and_backs_up_the_target(qtbot, tmp_path):
    source = sample()
    _backup, path = write_sample_backup(qtbot, tmp_path, source)
    target = MemNetBox()
    target.add("dcim/sites", name="Old", slug="old")
    dialog = restore_dialog(qtbot, tmp_path, target)
    dialog.load(path)
    dialog.findChild(type(dialog.modes.buttons()[0]), "restoreMode_replace").setChecked(
        True
    )
    with qtbot.waitSignal(dialog.runner.finished, timeout=10000):
        dialog.check()

    dialog.confirm_host = lambda text, host: "wrong"
    dialog.run()
    assert "did not match" in dialog.message.text() and target.writes == []

    shown = []
    dialog.confirm_host = lambda text, host: shown.append(text) or host
    with qtbot.waitSignal(dialog.runner.finished, timeout=10000):
        dialog.run()
    assert "objects are deleted" in shown[0]
    autos = list(tmp_path.glob("netbox-backup-mem.example.com-before-restore-*.json"))
    assert len(autos) == 1 and read_backup(autos[0]).counts()["dcim/sites"] == 1
    assert target.canon() == source.canon()


def test_main_window_offers_backup_and_restore(qtbot, tmp_path):
    from unifi2netbox.gui import MainWindow

    window = MainWindow(tmp_path / "config.toml", QThreadPool(), open_first_run=False)
    qtbot.addWidget(window)
    assert window.backup_action.text() == "Backup NetBox..."
    assert window.restore_action.text() == "Restore NetBox..."
    window.show_backup()  # not configured: nothing opens
    assert "Configure NetBox" in window.statusBar().currentMessage()
