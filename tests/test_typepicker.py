"""Device type picker dialog and its use for create rows (M12 slice 5)."""

from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import QCheckBox, QDialog, QLabel, QPushButton

from unifi2netbox.devicetypes import LocalTypeStore, new_document
from unifi2netbox.gui_typepicker import DeviceTypePicker, candidate_line
from unifi2netbox.inventory import InventoryDeviceType
from unifi2netbox.library import LibraryEntry, LibraryIndex
from unifi2netbox.typesearch import (
    TypeCandidate,
    from_document,
    library_candidates,
    netbox_candidates,
)

FIXTURES = Path(__file__).parent / "fixtures" / "devicetype-library" / "device-types"


def candidates():
    local = new_document("Ubiquiti", "Access Intercom")
    local["part_number"] = "UA-Intercom"
    local["interfaces"] = [{"name": "eth0", "type": "1000base-t", "poe_mode": "pd"}]
    index = LibraryIndex(
        "netbox-community/devicetype-library",
        "master",
        "2026-11-16T10:00:00+00:00",
        (LibraryEntry("Ubiquiti", "USW-Pro-24", "Ubiquiti/USW-Pro-24.yaml", "b" * 40),),
    )
    return (
        netbox_candidates(
            [
                InventoryDeviceType("11", "Ubiquiti", "U6 Lite", "U6-Lite"),
                InventoryDeviceType("12", "Cisco", "Catalyst 9300-24P", "C9300-24P"),
            ]
        )
        + [from_document(local, "local", "C:/types/UA-Intercom.yaml")]
        + library_candidates(index)
    )


def titles(picker):
    return [
        picker.results.item(i).toolTip().split("\n")[0]
        for i in range(picker.results.count())
    ]


@pytest.fixture
def picker(qtbot):
    dialog = DeviceTypePicker(
        candidates(),
        hint="USW Pro 24",
        hint_manufacturer="Ubiquiti",
        pool=QThreadPool(),
    )
    qtbot.addWidget(dialog)
    return dialog


def test_default_filters_and_ranked_results(picker):
    checked = [
        picker.criteria.item(i).text()
        for i in range(picker.criteria.count())
        if picker.criteria.item(i).checkState() == Qt.CheckState.Checked
    ]
    assert checked == ["Search", "Manufacturer", "Source"]
    assert picker.rows["manufacturer"].value.currentText() == "Ubiquiti"
    # The UniFi model's library match comes first; Cisco is filtered out.
    assert titles(picker) == ["USW-Pro-24", "U6 Lite", "Access Intercom"]
    assert "matches the UniFi model" in picker.results.item(0).toolTip()
    assert "imported into NetBox on apply" in picker.results.item(0).toolTip()


def test_criteria_add_rows_and_filter(picker):
    picker.set_filter("manufacturer", "")
    picker.set_filter("poe", "yes")
    assert "poe" in picker.rows
    picker.run_search()
    assert titles(picker) == ["Access Intercom"]
    assert "could not be checked" in picker.note.text()

    picker.criteria.item(7).setCheckState(Qt.CheckState.Unchecked)  # Has interfaces
    picker.set_filter("source", "netbox", "is not")
    picker.set_filter("search", "intercom")
    picker.run_search()
    assert titles(picker) == ["Access Intercom"]

    picker.set_filter("search", "nothing like this")
    picker.run_search()
    assert titles(picker) == [] and "Use New" in picker.note.text()
    assert not picker.select_button.isEnabled()


def test_select_and_new(picker):
    picker.results.setCurrentRow(1)
    picker.accept_current()
    assert picker.result() == QDialog.DialogCode.Accepted
    assert picker.selected.netbox_id == "11"

    picker.new_button.click()
    assert picker.new_requested


def test_candidate_line():
    item = TypeCandidate("netbox", "Ubiquiti", "U6 Lite", "U6-Lite", netbox_id="1")
    assert candidate_line(item, "U6 Lite") == (
        "Ubiquiti · U6-Lite · NetBox · matches the UniFi model"
    )


def test_main_window_uses_the_picker_and_new_drafts(qtbot, tmp_path, monkeypatch):
    from test_gui import review_window, select_row

    from unifi2netbox import gui as gui_module

    window = review_window(qtbot, tmp_path, QThreadPool())
    key = select_row(window, "ap-2")

    store = LocalTypeStore(tmp_path / "devicetype-library")
    doc = new_document("Ubiquiti", "AC Pro Local")
    doc["part_number"] = "UAP-AC-PRO-L"
    saved = store.write(doc)

    class Pick:
        def __init__(self, candidates, **kwargs):
            self.kwargs = kwargs
            self.candidates = candidates
            self.new_requested = False
            self.selected = next(c for c in candidates if c.source == "local")

        def exec(self):
            return QDialog.DialogCode.Accepted

        def deleteLater(self):
            pass

    monkeypatch.setattr(gui_module, "DeviceTypePicker", Pick)
    window.detail.findChild(QPushButton, "choiceTypeButton").click()

    value = window.review.type_by_key[key]
    assert value == f"local:{saved}"
    assert window.detail.findChild(QLabel, "choiceTypeText").text() == (
        "Ubiquiti AC Pro Local (local, imported on apply)"
    )
    assert window.review.row(key).attention

    class New(Pick):
        def __init__(self, candidates, **kwargs):
            super().__init__(candidates, **kwargs)
            self.new_requested = True

    monkeypatch.setattr(gui_module, "DeviceTypePicker", New)
    monkeypatch.setattr(
        window,
        "device_types_config",
        window.device_types_config.__class__(use_techspecs=False),
    )
    window.detail.findChild(QPushButton, "choiceTypeButton").click()
    editor = window.type_editor
    assert editor is not None and editor.dirty
    assert editor.current_document()["model"] == "AC Pro"
    assert window.pending_type_key == key

    editor.table_view.cells.put(2, 1, None, "slug", "ubiquiti-ac-pro", lambda: None)
    monkeypatch.setattr(
        "PySide6.QtWidgets.QMessageBox.question",
        lambda *a, **k: (
            __import__("PySide6.QtWidgets").QtWidgets.QMessageBox.StandardButton.Yes
        ),
    )
    assert editor.save()
    assert window.review.type_by_key[key].startswith("local:")
    assert window.review.type_by_key[key].endswith("AC-Pro.yaml")
    assert window.pending_type_key == ""


def test_imported_type_is_ready_counted_and_passed_to_the_job(
    qtbot, tmp_path, monkeypatch
):
    from dataclasses import replace

    from test_gui import fake_runner, preview_result, review_window, select_row

    from unifi2netbox.inventory import InventoryManufacturer

    result = replace(
        preview_result(),
        netbox_manufacturers=(InventoryManufacturer("41", "Ubiquiti"),),
    )
    window = review_window(qtbot, tmp_path, QThreadPool(), result)
    key = select_row(window, "ap-2")
    store = LocalTypeStore(tmp_path / "devicetype-library")
    doc = new_document("Ubiquiti", "AC Pro Local")
    doc["part_number"] = "UAP-AC-PRO-L"
    doc["interfaces"] = [{"name": "eth0", "type": "1000base-t"}]
    path = store.write(doc)

    window.set_device_type_choice(key, from_document(doc, "local", str(path)))

    assert not window.review.row(key).attention
    box = window.detail.findChild(QCheckBox, "typeImport")
    assert box is not None and box.isChecked()
    assert (
        "imported into NetBox on apply"
        in window.detail.findChild(QLabel, "typeImportStatus").text()
    )
    assert "1 device type" in window.selection_label.text()

    started = fake_runner(monkeypatch, window)
    window.execute_plan_button.click()
    plan = started["type_import_plan"]
    assert plan.operation_count == 1 and plan.rows[0].device_keys == (key,)
    assert key not in started["type"]

    box.setChecked(False)
    assert window.review.row(key).attention
    assert "not selected" in window.review.row(key).note
