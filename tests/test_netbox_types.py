"""NetBox device types as definitions and their comparison (M14 slice 2)."""

import copy

from test_devicetype_import import FULL
from test_netbox_objects import CONFIG, FakeSession

from unifi2netbox.devicetypes import dump_yaml, errors, validate
from unifi2netbox.netbox_types import (
    DIFFERS,
    LOCAL_ONLY,
    MISSING,
    NETBOX_ONLY,
    SAME,
    NetBoxTypes,
    compare,
    read_netbox_types,
)


def choice(value):
    return {"value": value, "label": value.upper()}


DT = {"id": 378}
ROWS = {
    "/api/dcim/device-types/": [
        {
            "id": 378,
            "manufacturer": {"id": 41, "name": "Ubiquiti", "slug": "ubiquiti"},
            "model": "Lab Box",
            "slug": "ubiquiti-lab-box",
            "part_number": "",
            "u_height": 1.0,
            "is_full_depth": False,
            "exclude_from_utilization": True,
            "airflow": None,
            "cooling_method": choice("air"),
            "weight": None,
            "weight_unit": None,
            "subdevice_role": None,
            "end_of_life": "2031-12-31",
            "owner": {"id": 51, "name": "Network team"},
            "default_platform": {"id": 52, "name": "UniFi OS"},
            "tags": [{"id": 53, "name": "Core", "slug": "core"}],
            "custom_fields": {"support": "gold", "unused": None},
            "front_image": "/media/devicetype-images/x.png",
            "rear_image": None,
            "description": "",
            "comments": "",
            "device_count": 3,
        }
    ],
    "/api/dcim/power-port-templates/": [
        {
            "id": 1,
            "device_type": DT,
            "name": "PSU 1",
            "label": "",
            "type": choice("iec-60320-c14"),
            "maximum_draw": None,
        },
    ],
    "/api/dcim/power-outlet-templates/": [
        {
            "id": 2,
            "device_type": DT,
            "name": "Out 1",
            "type": choice("iec-60320-c13"),
            "power_port": {"id": 1, "name": "PSU 1"},
            "feed_leg": None,
            "color": "",
        },
    ],
    "/api/dcim/interface-templates/": [
        {
            "id": 3,
            "device_type": DT,
            "name": "eth0",
            "type": choice("1000base-t"),
            "enabled": True,
            "mgmt_only": False,
            "parent": None,
            "bridge": None,
        },
        {
            "id": 4,
            "device_type": DT,
            "name": "eth0.10",
            "type": choice("virtual"),
            "enabled": True,
            "mgmt_only": False,
            "parent": {"id": 3, "name": "eth0"},
        },
        {
            "id": 5,
            "device_type": DT,
            "name": "br0",
            "type": choice("bridge"),
            "enabled": True,
            "mgmt_only": False,
        },
        {
            "id": 6,
            "device_type": DT,
            "name": "eth1",
            "type": choice("1000base-t"),
            "enabled": True,
            "mgmt_only": False,
            "bridge": {"id": 5, "name": "br0"},
        },
        # A module type template is not part of any device type.
        {
            "id": 99,
            "device_type": None,
            "module_type": {"id": 1},
            "name": "x",
            "type": choice("virtual"),
        },
    ],
    "/api/dcim/rear-port-templates/": [
        {
            "id": 7,
            "device_type": DT,
            "name": "R1",
            "type": choice("8p8c"),
            "positions": 2,
            "color": "",
        },
    ],
    "/api/dcim/front-port-templates/": [
        {
            "id": 12,
            "device_type": DT,
            "name": "F1",
            "type": choice("8p8c"),
            "positions": 1,
            "rear_ports": [{"position": 1, "rear_port": 7, "rear_port_position": 2}],
        },
    ],
    "/api/dcim/cooling-intake-templates/": [
        {"id": 8, "device_type": DT, "name": "In 1", "type": choice("uqd")},
    ],
    "/api/dcim/cooling-outflow-templates/": [
        {
            "id": 9,
            "device_type": DT,
            "name": "Out A",
            "type": choice("uqd"),
            "cooling_intake": {"id": 8, "name": "In 1"},
        },
    ],
    "/api/dcim/inventory-item-templates/": [
        {
            "id": 10,
            "device_type": DT,
            "name": "Tray",
            "parent": None,
            "role": {"id": 54, "name": "Fan tray"},
            "manufacturer": {"id": 41, "name": "Ubiquiti"},
            "component_type": "dcim.powerporttemplate",
            "component_id": 1,
        },
        {
            "id": 11,
            "device_type": DT,
            "name": "Fan 1",
            "parent": 10,
            "role": None,
            "manufacturer": None,
            "component_type": None,
            "component_id": None,
        },
    ],
}


def read(rows=ROWS, fail=()):
    return read_netbox_types(CONFIG, lambda config: FakeSession(rows, fail))


def test_netbox_types_become_library_style_definitions():
    types = read()
    assert types.loaded and not types.errors
    (item,) = types.types
    assert item.id == "378" and item.device_count == 3
    doc = item.doc
    assert list(doc)[:4] == ["manufacturer", "model", "slug", "u_height"]
    assert doc["manufacturer"] == "Ubiquiti" and doc["owner"] == "Network team"
    assert doc["default_platform"] == "UniFi OS" and doc["tags"] == ["core"]
    assert dict(doc["custom_fields"]) == {"support": "gold"}
    assert doc["cooling_method"] == "air" and doc["front_image"] is True
    assert "rear_image" not in doc and "part_number" not in doc
    assert doc["interfaces"][1] == {
        "name": "eth0.10",
        "type": "virtual",
        "parent": "eth0",
    }
    assert doc["interfaces"][0] == {"name": "eth0", "type": "1000base-t"}
    assert [dict(m) for m in doc["port-mappings"]] == [
        {
            "front_port": "F1",
            "front_port_position": 1,
            "rear_port": "R1",
            "rear_port_position": 2,
        }
    ]
    tray = next(i for i in doc["inventory-items"] if i["name"] == "Tray")
    assert dict(tray) == {
        "name": "Tray",
        "manufacturer": "Ubiquiti",
        "role": "Fan tray",
        "component_type": "dcim.powerporttemplate",
        "component_name": "PSU 1",
    }
    fan = next(i for i in doc["inventory-items"] if i["name"] == "Fan 1")
    assert fan["parent"] == "Tray"
    assert doc["cooling-outflows"][0]["cooling_intake"] == "In 1"
    assert errors(validate(doc)) == ()
    assert dump_yaml(doc).startswith("---\nmanufacturer: Ubiquiti\n")


def test_imported_definition_compares_equal_and_differences_are_listed():
    types = read()
    assert compare(FULL, types).status == SAME

    local = copy.deepcopy(FULL)
    local["u_height"] = 2
    local["interfaces"][3]["mgmt_only"] = True
    local["interfaces"].append({"name": "eth9", "type": "1000base-t"})
    local.pop("owner")  # missing locally: shown, never "clear in NetBox"
    netbox_rows = copy.deepcopy(ROWS)
    netbox_rows["/api/dcim/rear-port-templates/"].append(
        {"id": 13, "device_type": DT, "name": "R2", "type": choice("8p8c")}
    )
    result = compare(local, read(netbox_rows))

    assert result.status == DIFFERS and result.netbox.id == "378"
    assert result.field_diff("u_height").netbox == 1
    assert result.field_diff("owner").local is None
    assert result.field_diff("owner").netbox == "Network team"
    eth1 = result.row("interfaces", "eth1")
    assert eth1.kind == DIFFERS and eth1.fields[0].name == "mgmt_only"
    assert result.row("interfaces", "eth9").kind == LOCAL_ONLY
    assert result.row("rear-ports", "R2").kind == NETBOX_ONLY
    assert result.row("rear-ports", "R2").netbox_row["name"] == "R2"
    assert "2 field(s)" in result.summary() and "2 interfaces" in result.summary()


def test_matching_by_model_and_missing_types_and_read_errors():
    types = read()
    renamed = copy.deepcopy(FULL)
    renamed["slug"] = "ubiquiti-other-slug"
    assert compare(renamed, types).netbox.id == "378"
    other = copy.deepcopy(FULL)
    other["slug"], other["model"] = "ubiquiti-x", "X"
    assert compare(other, types).status == MISSING
    assert compare(other, NetBoxTypes()).summary() == "Not in NetBox."

    failed = read(fail={"/api/dcim/interface-templates/"})
    assert not failed.loaded and failed.errors
