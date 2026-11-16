"""Device type editor window (M12 slice 4)."""

import shutil
from pathlib import Path

import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QComboBox, QMessageBox

from unifi2netbox.config import DeviceTypesConfig
from unifi2netbox.devicetypes import LocalTypeStore, load_yaml, new_document
from unifi2netbox.gui_typeeditor import DeviceTypeEditor, text_value, value_text
from unifi2netbox.techspecs import SpecPorts, TechSpec

LIBRARY = Path(__file__).parent / "fixtures" / "devicetype-library"


@pytest.fixture
def store(tmp_path):
    shutil.copytree(
        LIBRARY / "device-types" / "Ubiquiti", tmp_path / "device-types" / "Ubiquiti"
    )
    return LocalTypeStore(tmp_path)


@pytest.fixture
def editor(qtbot, store):
    window = DeviceTypeEditor(store, DeviceTypesConfig(), QThreadPool())
    qtbot.addWidget(window)
    return window


def answer(monkeypatch, button):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: button)


def tree_names(editor):
    folder = editor.tree.topLevelItem(0)
    return folder.text(0), [folder.child(i).text(0) for i in range(folder.childCount())]


def test_tree_lists_the_local_folder_and_opens_files(editor, store):
    assert tree_names(editor) == ("Ubiquiti", ["U6+", "U6-Lite", "UNVR", "USW-Pro-24"])
    path = store.folder / "Ubiquiti" / "USW-Pro-24.yaml"

    assert editor.open_path(path)
    assert editor.title.text() == "UniFi Switch 24 Pro"
    assert editor.table_view.sections["interfaces"].table.rowCount() == 26
    assert editor.issues.item(0).text() == "No problems found."
    assert editor.tree.currentItem().text(0) == "USW-Pro-24"


def test_table_and_yaml_views_edit_the_same_document(editor, store):
    path = store.folder / "Ubiquiti" / "U6-Lite.yaml"
    original = path.read_text(encoding="utf-8")
    editor.open_path(path)

    editor.set_mode("yaml")
    assert editor.yaml_view.toPlainText() == original
    editor.yaml_view.setPlainText(original.replace("U6 Lite", "U6 Lite Test"))
    assert editor.dirty
    editor.set_mode("table")
    assert editor.table_view.document()["model"] == "U6 Lite Test"

    editor.yaml_view.setPlainText("manufacturer: [broken")
    editor.mode = "yaml"
    editor.set_mode("table")
    assert editor.mode == "yaml" and "Invalid YAML" in editor.issues.item(0).text()


def test_table_cells_are_typed():
    assert text_value(None, "u_height", "1") == 1
    assert text_value(None, "u_height", "0.5") == 0.5
    assert text_value(None, "weight", "3,6") == 3.6
    assert text_value(None, "is_full_depth", "false") is False
    assert text_value("interfaces", "mgmt_only", "true") is True
    assert text_value(None, "u_height", "abc") == "abc"
    assert text_value(None, "model", "  ") is None
    assert value_text(2.0) == "2" and value_text(True) == "true"


def test_new_type_from_table_is_validated_and_saved(editor, store, monkeypatch):
    editor.open_new(new_document("Acme", "Box 1"), ("Draft note",))
    assert (
        editor.subtitle.text() == "Not saved yet"
        and editor.notes.text() == "Draft note"
    )
    assert not editor.lookup_row.isVisibleTo(editor)

    interfaces = editor.table_view.sections["interfaces"]
    interfaces.add_row()
    interfaces.table.item(0, 0).setText("eth0")
    type_box = interfaces.table.cellWidget(0, interfaces.columns.index("type"))
    assert isinstance(type_box, QComboBox)
    type_box.setCurrentText("1000base-t")
    editor.table_view.comments.setPlainText("Made by hand")

    answer(monkeypatch, QMessageBox.StandardButton.No)
    assert editor.save()
    saved = store.folder / "Acme" / "Box 1.yaml"
    assert saved.read_text(encoding="utf-8") == (
        "---\n"
        "manufacturer: Acme\n"
        "model: Box 1\n"
        "slug: acme-box-1\n"
        "u_height: 0\n"
        "is_full_depth: false\n"
        "comments: Made by hand\n"
        "interfaces:\n"
        "  - name: eth0\n"
        "    type: 1000base-t\n"
    )
    assert editor.path == saved.resolve() and not editor.dirty
    assert "Acme" in [editor.tree.topLevelItem(i).text(0) for i in range(2)]


def test_save_with_errors_asks_first(editor, monkeypatch):
    editor.open_new(new_document("Acme", "Bad"))
    editor.set_mode("yaml")
    editor.yaml_view.setPlainText("---\nmanufacturer: Acme\nmodel: Bad\nslug: wrong\n")

    answer(monkeypatch, QMessageBox.StandardButton.No)
    assert not editor.save()
    assert any(
        "slug" in editor.issues.item(i).text() for i in range(editor.issues.count())
    )


def test_unsaved_changes_are_protected_and_files_deleted(editor, store, monkeypatch):
    editor.open_path(store.folder / "Ubiquiti" / "UNVR.yaml")
    editor.table_view.comments.setPlainText("changed")
    answer(monkeypatch, QMessageBox.StandardButton.No)
    assert not editor.open_path(store.folder / "Ubiquiti" / "U6+.yaml")
    assert editor.path.name == "UNVR.yaml"

    answer(monkeypatch, QMessageBox.StandardButton.Yes)
    editor.revert()
    assert not editor.dirty
    editor.delete()
    assert not (store.folder / "Ubiquiti" / "UNVR.yaml").exists()
    assert "UNVR" not in tree_names(editor)[1]


def test_techspecs_lookup_fills_gaps(editor, qtbot, monkeypatch):
    from unifi2netbox import gui_typeeditor

    spec = TechSpec(
        url="https://techspecs.ui.com/unifi/door-access/ua-intercom",
        slug="ua-intercom",
        sku="UA-Intercom",
        title="Access Intercom",
        weight=965.0,
        weight_unit="g",
        poe_powered=True,
        ports=(SpecPorts(1, "RJ45", 1000),),
    )
    seen = []
    monkeypatch.setattr(
        gui_typeeditor, "lookup", lambda model, part, http: seen.append(model) or spec
    )
    editor.open_new(new_document("Ubiquiti", "UA Intercom"))
    assert editor.lookup_row.isVisibleTo(editor)

    with qtbot.waitSignal(editor.runner.finished, timeout=5000):
        editor.look_up_specs()

    doc = editor.current_document()
    assert seen == ["UA Intercom"]
    assert doc["part_number"] == "UA-Intercom" and doc["weight"] == 965.0
    assert doc["interfaces"][0]["poe_mode"] == "pd"
    assert (
        "Techspecs](https://techspecs.ui.com/unifi/door-access/ua-intercom)"
        in doc["comments"]
    )
    assert editor.notes.text().startswith("Found Access Intercom (UA-Intercom).")

    monkeypatch.setattr(gui_typeeditor, "lookup", lambda *a: None)
    with qtbot.waitSignal(editor.runner.finished, timeout=5000):
        editor.look_up_specs()
    assert "No techspecs page found" in editor.notes.text()


def test_main_window_opens_the_editor_on_the_configured_folder(qtbot, tmp_path):
    from unifi2netbox.gui import MainWindow

    window = MainWindow(tmp_path / "config.toml", QThreadPool(), open_first_run=False)
    qtbot.addWidget(window)
    window.types_button.click()

    editor = window.type_editor
    assert editor is not None and editor.isVisible()
    assert editor.store.root == tmp_path / "devicetype-library"
    assert load_yaml("---\na: 1\n")["a"] == 1


def test_header_turns_compact_when_narrow(qtbot, tmp_path):
    from unifi2netbox.gui import MainWindow

    window = MainWindow(tmp_path / "config.toml", QThreadPool(), open_first_run=False)
    qtbot.addWidget(window)
    window.show()
    window.resize(1600, 700)
    window.update_header_mode()
    assert window.manual_button.text() == "Manual" and not window.netbox_chip.compact

    window.resize(500, 700)
    window.update_header_mode()
    assert window.manual_button.text() == "" and window.types_button.text() == ""
    assert window.netbox_chip.compact and not window.app_title.isVisible()
    assert window.netbox_chip.text() == "●  NetBox"
    assert window.netbox_chip.toolTip().startswith("NetBox · Not set")
