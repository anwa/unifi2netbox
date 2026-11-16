"""Device type definitions in the devicetype-library format (M12 slice 1)."""

from pathlib import Path

import pytest

from unifi2netbox.devicetypes import (
    DeviceTypeError,
    LocalTypeStore,
    choices,
    component_columns,
    device_slug,
    dump_yaml,
    errors,
    load_yaml,
    new_document,
    required_columns,
    slugify,
    validate,
)

LIBRARY = Path(__file__).parent / "fixtures" / "devicetype-library" / "device-types"


def library_files():
    return sorted(LIBRARY.rglob("*.yaml"))


@pytest.mark.parametrize("path", library_files(), ids=lambda p: p.name)
def test_library_files_round_trip_byte_identical_and_validate(path):
    text = path.read_text(encoding="utf-8")
    doc = load_yaml(text)

    assert dump_yaml(doc) == text
    assert errors(validate(doc, path)) == ()


def test_new_document_is_written_in_library_style():
    doc = {
        "interfaces": [
            {"name": "Port 1", "type": "1000base-t", "poe_mode": "pse"},
            {"name": "SFP+ 1", "type": "10gbase-x-sfpp", "description": ""},
        ],
        "comments": "Line one\nLine two",
        "weight": 1.2,
        "manufacturer": "Ubiquiti",
        "model": "USW Pro 24",
        "slug": "ubiquiti-usw-pro-24",
        "part_number": "USW-Pro-24",
        "u_height": 1,
        "is_full_depth": False,
        "weight_unit": "kg",
        "airflow": None,
    }

    assert dump_yaml(doc) == (
        "---\n"
        "manufacturer: Ubiquiti\n"
        "model: USW Pro 24\n"
        "slug: ubiquiti-usw-pro-24\n"
        "part_number: USW-Pro-24\n"
        "u_height: 1\n"
        "is_full_depth: false\n"
        "weight: 1.2\n"
        "weight_unit: kg\n"
        "comments: |\n"
        "  Line one\n"
        "  Line two\n"
        "interfaces:\n"
        "  - name: Port 1\n"
        "    type: 1000base-t\n"
        "    poe_mode: pse\n"
        "  - name: SFP+ 1\n"
        "    type: 10gbase-x-sfpp\n"
    )


def test_slugs_follow_the_library_rules():
    assert slugify("UniFi Switch 24 Pro") == "unifi-switch-24-pro"
    assert slugify("U6+") == "u6-plus"
    assert slugify("GL.iNet") == "gl-inet"
    assert device_slug("Ubiquiti", "USW-Pro-24") == "ubiquiti-usw-pro-24"
    assert new_document("Ubiquiti", "U6 Pro")["slug"] == "ubiquiti-u6-pro"


def test_validation_reports_schema_and_contributing_violations(tmp_path):
    doc = load_yaml(
        "---\n"
        "manufacturer: Ubiquiti\n"
        "model: U6 Pro\n"
        "slug: cisco-U6\n"
        "u_height: 0\n"
        "is_full_depth: false\n"
        "colour: blue\n"
        "weight: 1\n"
        "comments: ''\n"
        "interfaces:\n"
        "  - name: eth0\n"
        "    type: banana\n"
        "  - name: eth0\n"
        "    type: 1000base-t\n"
    )
    path = tmp_path / "Acme" / "Other.yaml"

    found = {
        (i.level, i.location, i.message.split(" ")[0]) for i in validate(doc, path)
    }
    messages = " ".join(i.message for i in validate(doc, path))

    assert ("error", "slug", "Use") in found
    assert ("error", "slug", "Must") in found
    assert ("error", "comments", "Remove") in found
    assert ("error", "weight_unit", "A") in found
    assert ("error", "interfaces", "Duplicate") in found
    assert ("warning", "airflow", "Recommended") in found
    assert "colour" in messages and "banana" in messages
    assert "must be the model or the part number" in messages
    assert "must be the manufacturer" in messages


def test_schema_choices_and_columns():
    assert "10gbase-x-sfpp" in choices("interface", "type")
    assert choices("interface", "poe_type")[0] == "type1-ieee802.3af"
    assert "passive" in choices("airflow", "")
    assert choices("weight-unit", "") == ("kg", "g", "lb", "oz")
    assert component_columns("interfaces")[:3] == ("name", "label", "type")
    assert required_columns("interfaces") == ("name", "type")


def test_invalid_yaml_and_non_mapping_are_reported():
    with pytest.raises(DeviceTypeError, match="Invalid YAML"):
        load_yaml("manufacturer: [unclosed\n")
    with pytest.raises(DeviceTypeError, match="mapping"):
        load_yaml("- a\n- b\n")


def test_local_store_writes_renames_lists_and_deletes(tmp_path):
    store = LocalTypeStore(tmp_path)
    doc = new_document("Ubiquiti", "U6 Pro")
    doc["part_number"] = "U6-Pro"

    path = store.write(doc)
    assert path == (tmp_path / "device-types" / "Ubiquiti" / "U6-Pro.yaml").resolve()
    assert [f.name for f in store.files()] == ["U6-Pro"]
    assert store.read(path)["model"] == "U6 Pro"

    doc["part_number"] = "U6-Pro-EU"
    renamed = store.write(doc, previous=path)
    assert not path.exists() and renamed.name == "U6-Pro-EU.yaml"

    other = new_document("Ubiquiti", "Other")
    other["part_number"] = "U6-Pro-EU"
    with pytest.raises(DeviceTypeError, match="already exists"):
        store.write(other)

    store.delete(renamed)
    assert store.files() == () and not (tmp_path / "device-types" / "Ubiquiti").exists()


def test_local_store_refuses_paths_outside_and_bad_names(tmp_path):
    store = LocalTypeStore(tmp_path / "lib")
    with pytest.raises(DeviceTypeError, match="outside"):
        store.read(tmp_path / "secret.yaml")
    with pytest.raises(DeviceTypeError, match="valid file names"):
        store.path_for(new_document("Acme", "A/B"))
