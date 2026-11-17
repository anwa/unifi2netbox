"""NetBox catalog, "New" object creation and its dialog (M13 slice 2)."""

import pytest
import requests
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QComboBox, QLineEdit

from unifi2netbox.config import NetBoxConfig
from unifi2netbox.journal_store import JournalStore
from unifi2netbox.netbox_catalog import CatalogObject, NetBoxCatalog, read_catalog
from unifi2netbox.netbox_objects import (
    ObjectCreateError,
    create_object,
    payload_for,
)

CONFIG = NetBoxConfig(url="https://netbox.example.com", token="t")


class FakeSession:
    """Answers paginated GETs from a dict of path -> rows."""

    def __init__(self, rows, fail=()):
        self.rows = rows
        self.fail = set(fail)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url, headers=None):
        path = url.split("netbox.example.com", 1)[1].split("?", 1)[0]
        if path in self.fail:
            return FakeResponse(403, {})
        rows = self.rows.get(path, [])
        return FakeResponse(200, {"count": len(rows), "results": rows})


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self.payload = payload

    def json(self):
        return self.payload


def test_catalog_reads_lists_and_device_type_custom_fields():
    rows = {
        "/api/dcim/manufacturers/": [
            {"id": 2, "name": "Ubiquiti", "slug": "ubiquiti"},
            {"id": 1, "name": "APC", "slug": "apc"},
        ],
        "/api/users/owners/": [{"id": 5, "name": "Ops", "group": {"name": "IT"}}],
        "/api/extras/tags/": [
            {"id": 7, "name": "Core", "slug": "core", "color": "ff0000"}
        ],
        "/api/extras/custom-field-choice-sets/": [
            {"id": 3, "extra_choices": [["gold", "Gold"], ["silver", "Silver"]]}
        ],
        "/api/extras/custom-fields/": [
            {
                "name": "support",
                "label": "Support",
                "type": {"value": "select"},
                "object_types": ["dcim.devicetype"],
                "choice_set": {"id": 3},
            },
            {
                "name": "firmware",
                "type": {"value": "text"},
                "object_types": ["dcim.device"],
            },
        ],
    }
    catalog = read_catalog(
        CONFIG, lambda config: FakeSession(rows, {"/api/dcim/platforms/"})
    )

    assert catalog.names("manufacturers") == ("APC", "Ubiquiti")
    assert catalog.names("tags") == ("core",)
    assert catalog.find("owners", "ops").detail == "IT"
    assert catalog.find("tags", "core").color == "ff0000"
    assert [(f.name, f.type, f.choices) for f in catalog.custom_fields] == [
        ("support", "select", ("gold", "silver"))
    ]
    assert catalog.items("platforms") == ()
    assert catalog.errors[0].startswith("platforms:")


CATALOG = NetBoxCatalog(
    {
        "manufacturers": (CatalogObject("2", "Ubiquiti", "ubiquiti"),),
        "owner_groups": (CatalogObject("9", "IT"),),
    },
    loaded=True,
)


def test_payloads_resolve_references_and_check_values():
    assert payload_for("tags", {"name": "Core Switch"}, CATALOG) == {
        "name": "Core Switch",
        "slug": "core-switch",
    }
    assert payload_for(
        "platforms", {"name": "UniFi OS", "manufacturer": "ubiquiti"}, CATALOG
    ) == {"name": "UniFi OS", "slug": "unifi-os", "manufacturer": 2}
    assert payload_for("owners", {"name": "Ops", "group": "IT"}, CATALOG)["group"] == 9
    with pytest.raises(ObjectCreateError, match="Owner group is required"):
        payload_for("owners", {"name": "Ops"}, CATALOG)
    with pytest.raises(ObjectCreateError, match="not in NetBox"):
        payload_for("owners", {"name": "Ops", "group": "HR"}, CATALOG)
    with pytest.raises(ObjectCreateError, match="six hex"):
        payload_for("tags", {"name": "x", "color": "red"}, CATALOG)
    with pytest.raises(ObjectCreateError, match="slug"):
        payload_for("tags", {"name": "x", "slug": "Bad Slug"}, CATALOG)


class FakeNetBox:
    def __init__(self, objects=None, fail=None):
        self.objects = dict(objects or {})
        self.created = []
        self.fail = fail

    def find_ids(self, path, **filters):
        return tuple(
            key
            for key, (kind, row) in self.objects.items()
            if kind == path and all(row.get(k) == v for k, v in filters.items())
        )

    def read_object(self, path):
        key = path.rstrip("/").rsplit("/", 1)[-1]
        entry = self.objects.get(key)
        return {"id": int(key), **entry[1]} if entry else None

    def create_object(self, path, payload):
        key = str(50 + len(self.objects))
        self.objects[key] = (path, dict(payload))
        if self.fail:
            raise self.fail
        self.created.append((path, payload))
        return key


def test_create_writes_reads_back_and_journals(tmp_path):
    backend = FakeNetBox()
    journal = tmp_path / "write-journal.sqlite3"

    result = create_object(
        "tags", {"name": "Lab", "color": "#00FF00"}, CATALOG, backend, journal
    )

    assert result.status == "success" and result.verification == "verified"
    assert backend.created == [
        ("/api/extras/tags/", {"name": "Lab", "slug": "lab", "color": "00ff00"})
    ]
    assert result.item.slug == "lab"
    (run,) = JournalStore(journal).recent()
    assert run.outcomes[0].operation_type == "create_netbox_object"
    assert run.outcomes[0].label == "Tag Lab"


def test_existing_objects_are_returned_not_duplicated_and_timeouts_looked_up():
    backend = FakeNetBox({"7": ("/api/extras/tags/", {"name": "Lab", "slug": "lab"})})
    result = create_object("tags", {"name": "lab2", "slug": "lab"}, CATALOG, backend)
    assert result.status == "existing" and result.item.id == "7" and not backend.created

    flaky = FakeNetBox(fail=requests.exceptions.Timeout("timed out"))
    result = create_object("owner_groups", {"name": "IT2"}, CATALOG, flaky)
    assert result.status == "success" and "interrupted" in result.message


def test_new_object_dialog_creates_and_nests(qtbot):
    calls = []

    def creator(kind, values, catalog):
        calls.append((kind, dict(values)))
        backend = FakeNetBox()
        return create_object(kind, values, catalog, backend)

    from unifi2netbox.gui_newobject import NewObjectDialog

    dialog = NewObjectDialog("owners", CATALOG, creator, QThreadPool(), name="Ops")
    qtbot.addWidget(dialog)
    assert dialog.findChild(QLineEdit, "field_name").text() == "Ops"
    group = dialog.findChild(QComboBox, "field_group")
    assert [group.itemText(i) for i in range(group.count())] == ["", "IT"]

    dialog.create()
    assert "Owner group is required" in dialog.message.text() and not calls

    group.setCurrentText("IT")
    with qtbot.waitSignal(dialog.runner.finished, timeout=5000):
        dialog.create()
    assert calls == [("owners", {"name": "Ops", "group": "IT", "description": ""})]
    assert dialog.created is not None and dialog.created.name == "Ops"
    assert dialog.catalog.find("owners", "Ops") is not None


def test_tag_dialog_slug_follows_the_name_until_edited(qtbot):
    from unifi2netbox.gui_newobject import NewObjectDialog

    dialog = NewObjectDialog("tags", CATALOG, lambda *a: None, QThreadPool())
    qtbot.addWidget(dialog)
    name = dialog.findChild(QLineEdit, "field_name")
    slug = dialog.findChild(QLineEdit, "field_slug")
    name.setText("Core Switch")
    assert slug.text() == "core-switch"
    slug.textEdited.emit("custom")
    slug.setText("custom")
    name.setText("Other")
    assert slug.text() == "custom"
