from unifi2netbox.inventory import InventoryDevice, InventorySnapshot, InventorySource
from unifi2netbox.matching import deduplicate_inventory
from unifi2netbox.preview import (
    DeviceAction,
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
    assert "Matched by identity." in device.provenance[0]
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

    manufacturer_cleared = select_field(
        preview, update.device_key, "manufacturer", False
    )
    changes = build_change_preview(manufacturer_cleared)
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
