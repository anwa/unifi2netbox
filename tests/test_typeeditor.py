"""Device type editor window (M12 slice 4)."""

import shutil
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool
from PySide6.QtWidgets import QComboBox, QListWidget, QMessageBox, QPushButton

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
    yield window
    # Delete the window now: hundreds of closed but living windows make
    # later style changes (theme tests) fragile.
    window.dirty = False
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


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


def test_editor_remembers_window_and_section_sizes(qtbot, store, tmp_path):
    from unifi2netbox.config import UiConfig, load_ui_config, save_ui_config

    path = tmp_path / "config.toml"
    save_ui_config(path, UiConfig(theme="dark"))
    first = DeviceTypeEditor(
        store, DeviceTypesConfig(), QThreadPool(), settings_path=path
    )
    qtbot.addWidget(first)
    first.show()
    first.resize(700, 520)
    first.table_view.splitter.setSizes([120, 300, 200])
    first.right_splitter.setSizes([400, 220])
    sizes = first.table_view.splitter.sizes()
    size = (first.width(), first.height())
    first.close()

    ui = load_ui_config(path)
    assert ui.theme == "dark"
    assert ui.type_editor_geometry and ui.type_editor_splitters.count(",") == 2

    second = DeviceTypeEditor(
        store, DeviceTypesConfig(), QThreadPool(), settings_path=path
    )
    qtbot.addWidget(second)
    second.show()
    assert (second.width(), second.height()) == size
    assert second.table_view.splitter.sizes() == sizes
    assert second.right_splitter.sizes()[1] == first.right_splitter.sizes()[1]


def test_sections_are_resizable_splitters(editor):
    from PySide6.QtWidgets import QSplitter

    assert editor.table_view.splitter.count() == 4
    assert not editor.table_view.splitter.childrenCollapsible()
    assert isinstance(editor.right_splitter, QSplitter)
    assert editor.right_splitter.widget(1).findChild(QListWidget, "typeIssues")


def test_saved_layout_is_validated():
    from unifi2netbox.config import ConfigError, UiConfig

    with pytest.raises(ConfigError, match="layout"):
        UiConfig(type_editor_geometry="not base64!")


# -- M13 slice 3: NetBox fields ------------------------------------------------

from unifi2netbox.gui_typeeditor import _TABLE_ATTRIBUTES  # noqa: E402
from unifi2netbox.gui_typefields import ChoiceCell  # noqa: E402
from unifi2netbox.netbox_catalog import (  # noqa: E402
    CatalogObject,
    CustomFieldDef,
    NetBoxCatalog,
)

CATALOG = NetBoxCatalog(
    {
        "manufacturers": (CatalogObject("1", "Ubiquiti", "ubiquiti"),),
        "owners": (CatalogObject("4", "Network team", detail="IT"),),
        "platforms": (CatalogObject("6", "UniFi OS", "unifi-os"),),
        "tags": (CatalogObject("7", "Core", "core"), CatalogObject("8", "Lab", "lab")),
        "inventory_item_roles": (CatalogObject("9", "Power supply", "psu"),),
    },
    (
        CustomFieldDef("support", "Support", "select", choices=("gold", "silver")),
        CustomFieldDef("warranty_years", "Warranty", "integer"),
    ),
    loaded=True,
)


def attribute_cell(editor, name):
    return editor.table_view.attributes.cellWidget(_TABLE_ATTRIBUTES.index(name), 1)


def component_cell(editor, section, row, column):
    table = editor.table_view.sections[section]
    return table.table.cellWidget(row, table.columns.index(column))


def test_references_are_drop_downs_of_the_catalog_and_own_components(editor):
    doc = load_yaml(
        "---\nmanufacturer: Ubiquiti\nmodel: Box\nslug: ubiquiti-box\n"
        "owner: Facilities\n"
        "power-ports:\n  - name: PSU 1\n    type: iec-60320-c14\n"
        "power-outlets:\n  - name: Out 1\n    type: iec-60320-c13\n"
        "    power_port: PSU 1\n"
    )
    editor.set_catalog(CATALOG)
    editor.open_new(doc)

    manufacturer = attribute_cell(editor, "manufacturer")
    assert isinstance(manufacturer, ChoiceCell)
    assert manufacturer.options() == ("Ubiquiti",) and manufacturer.text() == "Ubiquiti"
    assert attribute_cell(editor, "default_platform").options() == ("UniFi OS",)
    feed = component_cell(editor, "power-outlets", 0, "power_port")
    assert feed.options() == ("PSU 1",) and feed.text() == "PSU 1"

    ports = editor.table_view.sections["power-ports"]
    ports.add_row()
    ports.table.item(1, ports.columns.index("name")).setText("PSU 2")
    assert feed.options() == ("PSU 1", "PSU 2")

    editor.run_validation()
    texts = [editor.issues.item(i).text() for i in range(editor.issues.count())]
    assert any("Owner 'Facilities' is not in NetBox" in text for text in texts)


def test_tags_custom_fields_and_unchanged_files(editor, store):
    path = store.folder / "Ubiquiti" / "U6-Lite.yaml"
    original = path.read_text(encoding="utf-8")
    editor.set_catalog(CATALOG)
    editor.open_path(path)
    from unifi2netbox.devicetypes import dump_yaml

    assert dump_yaml(editor.table_view.document()) == original

    tags = editor.table_view.tags
    tags.picker.setCurrentText("core")
    tags.add_current()
    tags.add_tag("lab")
    tags.remove_tag("core")
    custom = editor.table_view.custom_fields
    custom.cellWidget(0, 1).setCurrentText("gold")
    custom.item(1, 1).setText("5")

    doc = editor.table_view.document()
    assert doc["tags"] == ["lab"]
    assert dict(doc["custom_fields"]) == {"support": "gold", "warranty_years": 5}
    assert editor.dirty

    editor.set_catalog(CATALOG)  # reloading keeps edited values
    assert editor.table_view.document()["custom_fields"]["warranty_years"] == 5


def test_images_are_copied_on_save_and_removed(editor, store, tmp_path):
    from unifi2netbox.devicetypes import find_image

    image = tmp_path / "front.png"
    image.write_bytes(b"\x89PNG fake")
    path = store.folder / "Ubiquiti" / "U6-Lite.yaml"
    editor.open_path(path)
    slug = str(editor.doc["slug"])

    editor.table_view.images.set_pending("front", image)
    assert editor.table_view.document()["front_image"] is True
    assert editor.save()
    saved = find_image(store, "Ubiquiti", slug, "front")
    assert saved is not None and saved.name == f"{slug}.front.png"
    assert saved.read_bytes() == b"\x89PNG fake"
    assert editor.table_view.images.labels["front"].text() == saved.name

    editor.table_view.images.set_pending("front", "remove")
    assert "front_image" not in editor.table_view.document()
    assert editor.save()
    assert find_image(store, "Ubiquiti", slug, "front") is None


def test_new_button_creates_the_object_and_selects_it(qtbot, store, monkeypatch):
    import unifi2netbox.gui_typeeditor as module

    class FakeDialog:
        def __init__(self, kind, catalog, creator, pool, parent, name=""):
            self.created = CatalogObject("11", name or "Ops", "ops")
            self.catalog = catalog.with_object(kind, self.created)
            seen.append((kind, name))

        def exec(self):
            return module.QDialog.DialogCode.Accepted

    seen = []
    monkeypatch.setattr(module, "NewObjectDialog", FakeDialog)
    editor = DeviceTypeEditor(
        store, DeviceTypesConfig(), QThreadPool(), creator=lambda *a: None
    )
    qtbot.addWidget(editor)
    editor.set_catalog(CATALOG)
    editor.open_new(new_document("Ubiquiti", "Box"))

    owner = attribute_cell(editor, "owner")
    owner.set_text("Ops")
    owner.new_button.click()
    assert seen == [("owners", "Ops")]
    assert owner.text() == "Ops" and "Ops" in owner.options()
    assert editor.catalog.find("owners", "Ops") is not None

    tags = editor.table_view.tags
    tags.picker.setCurrentText("wifi")
    editor.table_view.findChild(module.QWidget, "new_tags").click()
    assert tags.tags == ["ops"]  # tags store the created slug


def test_editor_without_creator_has_no_new_buttons(editor):
    editor.open_new(new_document("Ubiquiti", "Box"))
    assert attribute_cell(editor, "owner").new_button is None
    assert editor.catalog_status.text() == "NetBox not configured."
    assert not editor.buttons["catalog"].isEnabled()


def test_catalog_is_read_in_the_background_when_shown(qtbot, store):
    editor = DeviceTypeEditor(
        store, DeviceTypesConfig(), QThreadPool(), catalog_loader=lambda: CATALOG
    )
    qtbot.addWidget(editor)
    with qtbot.waitSignal(editor.catalog_runner.finished, timeout=5000):
        editor.show()
    assert editor.catalog is CATALOG
    assert "1 manufacturers" in editor.catalog_status.text()
    assert "2 custom fields" in editor.catalog_status.text()


# -- M14 slice 1: tree refresh ---------------------------------------------------


def test_files_copied_by_hand_appear_after_refresh_reopen_and_watch(
    qtbot, editor, store
):
    copy = store.folder / "Ubiquiti" / "U6-Copy.yaml"
    copy.write_text(
        (store.folder / "Ubiquiti" / "U6-Lite.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    editor.buttons["refresh"].click()
    assert "U6-Copy" in tree_names(editor)[1]

    editor.show()
    editor.hide()
    copy.unlink()
    editor.show()  # reopening re-reads the folder
    assert "U6-Copy" not in tree_names(editor)[1]

    (store.folder / "Cisco").mkdir()
    shutil.copy(
        LIBRARY / "device-types" / "Cisco" / "C9300-24P.yaml", store.folder / "Cisco"
    )
    qtbot.waitUntil(lambda: editor.tree.topLevelItemCount() == 2, timeout=5000)
    editor.hide()


def test_open_file_changed_on_disk_is_reloaded_or_asks_when_edited(
    editor, store, monkeypatch
):
    path = store.folder / "Ubiquiti" / "U6-Lite.yaml"
    editor.open_path(path)
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("U6 Lite", "U6 Lite Disk"), encoding="utf-8")
    editor.refresh_tree()
    assert editor.title.text() == "U6 Lite Disk"

    editor.set_mode("yaml")
    editor.yaml_view.setPlainText(
        editor.yaml_view.toPlainText().replace("U6 Lite Disk", "Mine")
    )
    assert editor.dirty
    path.write_text(text, encoding="utf-8")
    answer(monkeypatch, QMessageBox.StandardButton.No)
    editor.refresh_tree()
    assert editor.dirty and "Mine" in editor.yaml_view.toPlainText()

    editor.dirty = False
    path.unlink()
    editor.refresh_tree()
    assert editor.path is None and "removed" in editor.notes.text()


# -- M14 slice 3: NetBox status and values ----------------------------------------

from unifi2netbox.gui_typediff import cell_mark  # noqa: E402
from unifi2netbox.gui_typeeditor import STATUS_ROLE  # noqa: E402
from unifi2netbox.netbox_types import NetBoxType, NetBoxTypes  # noqa: E402


def netbox_types(store):
    lite = store.read(store.folder / "Ubiquiti" / "U6-Lite.yaml")
    lite["weight"] = 310
    lite["interfaces"][0]["poe_type"] = "type2-ieee802.3at"
    del lite["interfaces"][2]  # wlan1 is only local
    lite["interfaces"].append({"name": "eth9", "type": "1000base-t"})
    pro = store.read(store.folder / "Ubiquiti" / "USW-Pro-24.yaml")
    return NetBoxTypes((NetBoxType("5", lite, 2), NetBoxType("6", pro, 0)), loaded=True)


@pytest.fixture
def synced(qtbot, store):
    types = netbox_types(store)
    window = DeviceTypeEditor(
        store, DeviceTypesConfig(), QThreadPool(), types_loader=lambda: types
    )
    # Not qtbot.addWidget: it closes (and would ask) before this teardown.
    with qtbot.waitSignal(window.status_runner.finished, timeout=5000):
        window.show()
    yield window
    window.dirty = False
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


def test_tree_shows_equal_differing_and_missing_types(synced):
    from unifi2netbox import theme

    folder = synced.tree.topLevelItem(0)
    states = {
        folder.child(i).text(0): folder.child(i).data(0, STATUS_ROLE)
        for i in range(folder.childCount())
    }
    assert states == {
        "U6+": "missing",
        "U6-Lite": "differs",
        "UNVR": "missing",
        "USW-Pro-24": "same",
    }
    lite = next(
        folder.child(i) for i in range(4) if folder.child(i).text(0) == "U6-Lite"
    )
    assert lite.foreground(0).color() == theme.tone_qcolor("warning")
    assert "Differs from NetBox" in lite.toolTip(0)
    assert folder.foreground(0).color() == theme.tone_qcolor("danger")
    assert "377" not in synced.catalog_status.text()
    assert "2 NetBox device types." in synced.catalog_status.text()


def test_editor_marks_netbox_values_and_takes_them_over(synced, store):
    from unifi2netbox.gui_typeeditor import _TABLE_ATTRIBUTES

    synced.open_path(store.folder / "Ubiquiti" / "U6-Lite.yaml")
    view = synced.table_view
    row = _TABLE_ATTRIBUTES.index("weight")
    assert cell_mark(view.attributes, row, 1) == "warning"
    assert "NetBox: 310" in view.attributes.item(row, 1).toolTip()
    assert "Differs from NetBox" in synced.netbox_note.text()

    interfaces = view.sections["interfaces"]
    columns = interfaces.columns
    assert cell_mark(interfaces.table, 0, columns.index("poe_type")) == "warning"
    assert cell_mark(interfaces.table, 2, 0) == "danger"  # wlan1: only local
    assert interfaces.real_rows() == 3 and interfaces.table.rowCount() == 4
    assert interfaces.table.verticalHeaderItem(3).text() == "NetBox"
    assert [i["name"] for i in view.document()["interfaces"]] == [
        "lan0",
        "wlan0",
        "wlan1",
    ]
    assert "●" in view.tabs.tabText(view.tabs.indexOf(interfaces))

    view.use_netbox_attribute("weight")
    interfaces.use_netbox(0, ["poe_type"])
    interfaces.use_netbox(3)  # adds eth9
    doc = synced.table_view.document()
    assert doc["weight"] == 310
    assert doc["interfaces"][0]["poe_type"] == "type2-ieee802.3at"
    assert [i["name"] for i in doc["interfaces"]] == ["lan0", "wlan0", "wlan1", "eth9"]
    assert synced.dirty
    assert cell_mark(view.attributes, row, 1) == ""
    assert interfaces.table.rowCount() == 4  # no NetBox-only row left


def test_copy_yaml_puts_the_definition_on_the_clipboard(editor, store):
    from PySide6.QtGui import QGuiApplication

    from unifi2netbox.devicetypes import dump_yaml

    path = store.folder / "Ubiquiti" / "U6-Lite.yaml"
    editor.open_path(path)
    editor.buttons["copy"].click()
    assert QGuiApplication.clipboard().text() == path.read_text(encoding="utf-8")
    assert dump_yaml(editor.doc) == path.read_text(encoding="utf-8")
    assert "clipboard" in editor.notes.text()


# -- M14 slice 4: New from NetBox, the library or by hand --------------------------

from unifi2netbox.typesearch import TypeCandidate  # noqa: E402


def choose(window, monkeypatch, wanted):
    seen = []

    def exec_picker(picker):
        seen.append(picker)
        assert picker.new_button.isHidden()
        picker.selected = next(c for c in picker.candidates if wanted(c))
        return True

    monkeypatch.setattr(window, "exec_picker", exec_picker)
    return seen


def test_new_menu_offers_netbox_library_and_manual(editor):
    menu = editor.buttons["new"].menu()
    assert [a.text() for a in menu.actions()] == [
        "From NetBox...",
        "From the devicetype-library...",
        "Manual",
    ]
    editor.new_from("manual")
    assert editor.path is None and editor.dirty
    editor.new_from("netbox")
    assert "not loaded" in editor.notes.text()


def test_new_from_netbox_opens_the_netbox_definition(synced, monkeypatch):
    seen = choose(synced, monkeypatch, lambda c: c.model == "U6 Lite")
    synced.new_from("netbox")
    assert {c.source for c in seen[0].candidates} == {"netbox"}
    assert synced.path is None and synced.dirty
    assert synced.doc["weight"] == 310
    assert "From NetBox (device type 5, used by 2 devices)" in synced.notes.text()


def test_new_from_the_library_downloads_in_the_background(qtbot, store, monkeypatch):
    text = (store.folder / "Ubiquiti" / "UNVR.yaml").read_text(encoding="utf-8")
    fetched = []

    class Library:
        def candidates(self):
            return [
                TypeCandidate("library", "Ubiquiti", "UNVR", path="Ubiquiti/UNVR.yaml"),
                TypeCandidate("netbox", "Ubiquiti", "Other", netbox_id="1"),
            ], ""

        def refresh(self):
            return []

        def fetch(self, candidate):
            fetched.append(candidate.path)
            return text

    window = DeviceTypeEditor(
        store, DeviceTypesConfig(), QThreadPool(), library=Library()
    )
    qtbot.addWidget(window)
    seen = choose(window, monkeypatch, lambda c: c.model == "UNVR")
    with qtbot.waitSignal(window.fetch_runner.finished, timeout=5000):
        window.new_from("library")
    assert [c.source for c in seen[0].candidates] == ["library"]
    assert fetched == ["Ubiquiti/UNVR.yaml"]
    assert window.doc.get("model") and window.dirty
    assert "devicetype-library (Ubiquiti/UNVR.yaml)" in window.notes.text()
    window.dirty = False


# -- M14 slice 5: sync from the editor ----------------------------------------------


def test_sync_buttons_open_the_right_dialog_and_save_netbox_values(
    qtbot, store, monkeypatch
):
    from types import SimpleNamespace

    from unifi2netbox.gui_typesync import SyncAllDialog, SyncDialog

    types = netbox_types(store)
    window = DeviceTypeEditor(
        store,
        DeviceTypesConfig(),
        QThreadPool(),
        types_loader=lambda: types,
        sync=object(),
    )
    opened = []
    monkeypatch.setattr(window, "exec_dialog", lambda d: opened.append(d))
    with qtbot.waitSignal(window.types_runner.finished, timeout=5000):
        window.load_types()

    window.open_path(store.folder / "Ubiquiti" / "U6-Lite.yaml")
    window.open_sync()
    assert isinstance(opened[-1], SyncDialog)
    assert opened[-1].comparison.status == "differs"

    window.open_path(store.folder / "Ubiquiti" / "UNVR.yaml")
    window.open_sync()
    assert isinstance(opened[-1], SyncAllDialog)
    assert opened[-1].targets[0].status == "missing"

    window.open_sync_all()
    labels = [t.label for t in opened[-1].targets]
    assert labels == ["Ubiquiti U6+", "Ubiquiti U6-Lite", "Ubiquiti UNVR"]

    # NetBox values chosen in the dialog are written to the local file.
    window.open_path(store.folder / "Ubiquiti" / "U6-Lite.yaml")
    doc = window.store.read(window.path)
    doc["weight"] = 310
    outcome = SimpleNamespace(status="success")
    with qtbot.waitSignal(window.types_runner.finished, timeout=5000):
        window._synced(SimpleNamespace(local_doc=doc, outcome=outcome))
    assert "weight: 310" in window.path.read_text(encoding="utf-8")
    assert not window.dirty and "Synced." in window.notes.text()
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


# -- usability fixes (2026-11-18) ------------------------------------------------------


def test_remove_selected_works_on_rows_of_drop_downs(editor, store):
    editor.open_path(store.folder / "Ubiquiti" / "U6-Lite.yaml")
    interfaces = editor.table_view.sections["interfaces"]
    table = interfaces.table
    # Clicking a drop-down does not select the row; the current cell counts.
    table.clearSelection()
    table.setCurrentCell(1, 0)
    table.clearSelection()
    editor.findChild(QPushButton, "remove_interfaces").click()
    assert [i["name"] for i in editor.table_view.document()["interfaces"]] == [
        "lan0",
        "wlan1",
    ]
    table.selectRow(0)
    interfaces.remove_rows()
    assert [i["name"] for i in editor.table_view.document()["interfaces"]] == ["wlan1"]
    assert editor.dirty


def test_rows_are_high_enough_for_drop_downs(editor, store):
    from unifi2netbox.gui_typefields import ChoiceCell

    editor.open_path(store.folder / "Ubiquiti" / "U6-Lite.yaml")
    table = editor.table_view.sections["interfaces"].table
    cell = next(
        table.cellWidget(0, c)
        for c in range(table.columnCount())
        if isinstance(table.cellWidget(0, c), ChoiceCell)
    )
    assert table.rowHeight(0) >= cell.sizeHint().height()
    attributes = editor.table_view.attributes
    assert attributes.verticalHeader().defaultSectionSize() == table.rowHeight(0)


def test_right_click_on_a_drop_down_opens_the_table_menu(editor, store, monkeypatch):
    from PySide6.QtCore import QPoint

    import unifi2netbox.gui_typeeditor as module

    actions = []

    class Menu:  # records the entries instead of opening a modal menu
        def __init__(self, *_a):
            pass

        def addAction(self, text, *_a):  # noqa: N802 - Qt name
            actions.append(text)
            return type("A", (), {"setEnabled": lambda *a: None})()

        def addSeparator(self):  # noqa: N802 - Qt name
            pass

        def exec(self, *_a):
            pass

    monkeypatch.setattr(module, "QMenu", Menu)
    editor.open_path(store.folder / "Ubiquiti" / "U6-Lite.yaml")
    table = editor.table_view.sections["interfaces"].table
    seen = []
    table.customContextMenuRequested.connect(lambda pos: seen.append(pos))
    combo = table.cellWidget(0, 2)  # type
    combo.customContextMenuRequested.emit(QPoint(2, 2))
    assert seen and table.indexAt(seen[0]).row() == 0
    assert "Remove this row" in actions


def test_sections_fold_away_and_are_remembered(qtbot, store, tmp_path):
    from unifi2netbox.config import UiConfig, load_ui_config, save_ui_config

    settings = tmp_path / "config.toml"
    save_ui_config(settings, UiConfig())
    first = DeviceTypeEditor(
        store, DeviceTypesConfig(), QThreadPool(), settings_path=settings
    )
    qtbot.addWidget(first)
    first.resize(1100, 700)
    first.show()
    view = first.table_view
    before = view.splitter.sizes()[0]
    for key in ("comments", "netbox", "components"):
        view.folds[key].header.click()
    first.validation_fold.header.click()
    qtbot.wait(10)
    sizes = view.splitter.sizes()
    assert view.folds["comments"].collapsed and not view.comments.isVisible()
    assert sizes[1] <= view.folds["comments"].folded_height()
    assert sizes[0] > before  # the attributes got the room
    first.hide()
    assert load_ui_config(settings).type_editor_collapsed == (
        "comments,netbox,components,validation"
    )

    second = DeviceTypeEditor(
        store, DeviceTypesConfig(), QThreadPool(), settings_path=settings
    )
    qtbot.addWidget(second)
    second.show()
    assert second.table_view.folds["netbox"].collapsed
    second.table_view.folds["netbox"].header.click()
    assert not second.table_view.folds["netbox"].collapsed
    assert second.table_view.splitter.sizes()[2] >= 100
    second.hide()


def test_dates_are_picked_from_a_calendar_or_cleared(editor, store):
    from PySide6.QtCore import QDate

    from unifi2netbox.gui_typeeditor import _TABLE_ATTRIBUTES
    from unifi2netbox.gui_typefields import DateCell
    from unifi2netbox.netbox_catalog import CustomFieldDef, NetBoxCatalog

    editor.set_catalog(
        NetBoxCatalog(
            custom_fields=(CustomFieldDef("bought", "Bought", "date"),), loaded=True
        )
    )
    editor.open_path(store.folder / "Ubiquiti" / "U6-Lite.yaml")
    view = editor.table_view
    cell = view.attributes.cellWidget(_TABLE_ATTRIBUTES.index("end_of_life"), 1)
    assert isinstance(cell, DateCell) and cell.text() == ""
    calendar = cell.calendar()
    calendar.clicked.emit(QDate(2031, 12, 31))
    assert view.document()["end_of_life"] == "2031-12-31"
    assert editor.dirty
    cell.clear.click()
    assert "end_of_life" not in view.document()

    bought = view.custom_fields.cellWidget(0, 1)
    assert isinstance(bought, DateCell)
    bought.calendar().clicked.emit(QDate(2024, 2, 29))
    assert dict(view.document()["custom_fields"]) == {"bought": "2024-02-29"}
