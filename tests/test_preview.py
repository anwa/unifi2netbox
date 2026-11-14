from dataclasses import replace

from unifi2netbox.inventory import InventoryDevice, InventorySnapshot, InventorySource
from unifi2netbox.matching import deduplicate_inventory
from unifi2netbox.preview import (
    DeviceAction,
    DifferencePreview,
    FieldCategory,
    build_change_preview,
    build_difference_preview,
    select_batch,
    select_device,
    select_field,
)


def snapshot(
    source: InventorySource, devices: list[InventoryDevice]
) -> InventorySnapshot:
    return InventorySnapshot(
        source=source,
        captured_at="2026-10-28T16:00:00+00:00",
        source_version="x",
        devices=tuple(devices),
    )


def force_select(preview, device_key, field_name):
    """Simulate a selectable field the update executor does not support yet."""
    devices = []
    for device in preview.devices:
        if device.device_key == device_key:
            fields = tuple(
                replace(field, selectable=True, selected=True)
                if field.name == field_name
                else field
                for field in device.fields
            )
            device = replace(device, fields=fields, selectable=True, selected=True)
        devices.append(device)
    return DifferencePreview(devices=tuple(devices))


def test_preview_contains_provenance_categories_and_unsupported_fields():
    netbox = snapshot(
        InventorySource.NETBOX,
        [
            InventoryDevice(
                source_id="1",
                name="switch-a",
                manufacturer="Ubiquiti",
                model="USW-24",
                serial="A1",
                mac_address="00:11:22:33:44:55",
                site="HQ",
            )
        ],
    )
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK,
        [
            InventoryDevice(
                source_id="a",
                name="switch-a-renamed",
                manufacturer="Ubiquiti",
                model="USW-24",
                serial="A1",
                mac_address="00:11:22:33:44:55",
                site="HQ",
            )
        ],
    )
    result = deduplicate_inventory(netbox, unifi)

    preview = build_difference_preview(netbox, unifi, result)

    device = next(
        item for item in preview.devices if item.action == DeviceAction.UPDATE
    )
    assert "Matched by serial." in device.provenance[0]
    name_field = next(field for field in device.fields if field.name == "name")
    assert name_field.category == FieldCategory.CONFIGURED
    assert name_field.changed is True
    assert name_field.selectable is True
    unsupported = next(field for field in device.fields if field.name == "vlan")
    assert unsupported.supported is False
    assert unsupported.selectable is False


def test_preview_includes_create_and_target_only_actions():
    netbox = snapshot(
        InventorySource.NETBOX, [InventoryDevice(source_id="1", name="nb")]
    )
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK, [InventoryDevice(source_id="a", name="uf")]
    )
    result = deduplicate_inventory(netbox, unifi)

    preview = build_difference_preview(netbox, unifi, result)

    assert any(item.action == DeviceAction.CREATE for item in preview.devices)
    assert any(item.action == DeviceAction.TARGET_ONLY for item in preview.devices)


def test_batch_device_and_field_selection_controls():
    netbox = snapshot(
        InventorySource.NETBOX,
        [InventoryDevice(source_id="1", name="old-name", serial="S1")],
    )
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK,
        [InventoryDevice(source_id="a", name="new-name", serial="S1")],
    )
    result = deduplicate_inventory(netbox, unifi)
    preview = build_difference_preview(netbox, unifi, result)

    update = next(
        item for item in preview.devices if item.action == DeviceAction.UPDATE
    )

    cleared = select_batch(preview, False)
    cleared_update = next(
        item for item in cleared.devices if item.device_key == update.device_key
    )
    assert cleared_update.selected is False
    assert all(
        not field.selected for field in cleared_update.fields if field.selectable
    )

    chosen_device = select_device(cleared, update.device_key, True)
    chosen_update = next(
        item for item in chosen_device.devices if item.device_key == update.device_key
    )
    assert chosen_update.selected is True

    only_name = select_field(chosen_device, update.device_key, "name", False)
    only_name_update = next(
        item for item in only_name.devices if item.device_key == update.device_key
    )
    name_field = next(
        field for field in only_name_update.fields if field.name == "name"
    )
    assert name_field.selected is False


def test_change_preview_reports_target_only_as_non_executable():
    netbox = snapshot(
        InventorySource.NETBOX, [InventoryDevice(source_id="1", name="nb")]
    )
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK, [InventoryDevice(source_id="a", name="uf")]
    )
    result = deduplicate_inventory(netbox, unifi)
    preview = build_difference_preview(netbox, unifi, result)

    changes = build_change_preview(preview)

    target_only = next(
        item for item in changes.devices if item.action == DeviceAction.TARGET_ONLY
    )
    assert target_only.executable is False
    assert any(dep.name == "target_only_no_write" for dep in target_only.dependencies)


def test_change_preview_create_requires_name_and_site():
    netbox = snapshot(InventorySource.NETBOX, [])
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK,
        [InventoryDevice(source_id="a", name="", site="", serial="S1")],
    )
    result = deduplicate_inventory(netbox, unifi)
    preview = build_difference_preview(netbox, unifi, result)

    changes = build_change_preview(preview)

    create = next(
        item for item in changes.devices if item.action == DeviceAction.CREATE
    )
    dependency = next(
        item for item in create.dependencies if item.name == "create_required_identity"
    )
    assert create.executable is False
    assert dependency.satisfied is False
    assert dependency.missing_fields == ("name", "site")


def test_change_preview_model_depends_on_selected_manufacturer():
    netbox = snapshot(
        InventorySource.NETBOX,
        [
            InventoryDevice(
                source_id="1",
                name="switch-a",
                manufacturer="Ubiquiti",
                model="USW-24",
                serial="S1",
            )
        ],
    )
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK,
        [
            InventoryDevice(
                source_id="a",
                name="switch-a",
                manufacturer="Ubiquity",
                model="USW-48",
                serial="S1",
            )
        ],
    )
    result = deduplicate_inventory(netbox, unifi)
    preview = build_difference_preview(netbox, unifi, result)
    update = next(
        item for item in preview.devices if item.action == DeviceAction.UPDATE
    )

    model_only = force_select(preview, update.device_key, "model")
    changes = build_change_preview(model_only)
    update_change = next(
        item for item in changes.devices if item.device_key == update.device_key
    )
    dependency = next(
        item
        for item in update_change.dependencies
        if item.name == "model_requires_manufacturer"
    )

    assert update_change.executable is False
    assert dependency.satisfied is False
    assert dependency.missing_fields == ("manufacturer",)


def _matched_pair(netbox_device, unifi_device):
    netbox = snapshot(InventorySource.NETBOX, [netbox_device])
    unifi = snapshot(InventorySource.UNIFI_NETWORK, [unifi_device])
    preview = build_difference_preview(
        netbox, unifi, deduplicate_inventory(netbox, unifi)
    )
    update = next(d for d in preview.devices if d.action == DeviceAction.UPDATE)
    return preview, update, {field.name: field for field in update.fields}


def test_update_preview_shows_but_does_not_select_unwritable_fields():
    preview, update, fields = _matched_pair(
        InventoryDevice(
            source_id="1", name="sw", manufacturer="Ubiquiti", model="USW-Pro-24"
        ),
        InventoryDevice(
            source_id="a",
            name="sw",
            manufacturer="Ubiquiti Inc",
            model="USW Pro 24",
            mac_address="00:11:22:33:44:55",
        ),
    )

    for name in ("model", "manufacturer", "mac_address"):
        assert fields[name].changed is True
        assert fields[name].selectable is False
        assert fields[name].selected is False
        assert "preview only" in fields[name].provenance
    assert update.selectable is False
    change = build_change_preview(preview)
    assert change.devices[0].selected_fields == ()


def test_update_preview_never_selects_empty_source_values():
    _, update, fields = _matched_pair(
        InventoryDevice(source_id="1", name="sw", serial="NB-SERIAL", site="HQ"),
        InventoryDevice(source_id="a", name="sw", serial="", site="Branch"),
    )

    assert fields["serial"].changed is True
    assert fields["serial"].selectable is False
    assert "NetBox value is kept" in fields["serial"].provenance
    assert fields["site"].selected is True
    assert update.selectable is True


def test_update_preview_does_not_select_site_missing_in_netbox():
    netbox = snapshot(
        InventorySource.NETBOX,
        [InventoryDevice(source_id="1", name="sw", site="Home")],
    )
    unifi = snapshot(
        InventorySource.UNIFI_NETWORK,
        [InventoryDevice(source_id="a", name="sw", site="Default")],
    )
    preview = build_difference_preview(
        netbox,
        unifi,
        deduplicate_inventory(netbox, unifi),
        netbox_sites=frozenset({"Home"}),
    )
    update = next(d for d in preview.devices if d.action == DeviceAction.UPDATE)
    site = next(field for field in update.fields if field.name == "site")

    assert site.changed is True
    assert site.selectable is False
    assert "does not exist in NetBox" in site.provenance
    assert update.selectable is False
