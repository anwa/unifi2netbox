from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from unifi2netbox.inventory import InventoryDevice, InventorySnapshot, InventorySource
from unifi2netbox.matching import DeduplicationResult


class DeviceAction(StrEnum):
    UPDATE = "update"
    CREATE = "create"
    TARGET_ONLY = "target_only"


class FieldCategory(StrEnum):
    CONFIGURED = "configured"
    OPERATIONAL = "operational"


@dataclass(frozen=True)
class FieldPreview:
    name: str
    category: FieldCategory
    source_value: str
    target_value: str
    changed: bool
    supported: bool
    provenance: str
    selectable: bool
    selected: bool


@dataclass(frozen=True)
class DevicePreview:
    device_key: str
    action: DeviceAction
    source_label: str
    target_label: str
    provenance: tuple[str, ...]
    unsupported_fields: tuple[str, ...]
    selectable: bool
    selected: bool
    fields: tuple[FieldPreview, ...]


@dataclass(frozen=True)
class DifferencePreview:
    devices: tuple[DevicePreview, ...]


@dataclass(frozen=True)
class ChangeDependency:
    name: str
    description: str
    required_fields: tuple[str, ...]
    missing_fields: tuple[str, ...]
    satisfied: bool


@dataclass(frozen=True)
class DeviceChangePreview:
    device_key: str
    action: DeviceAction
    selected_fields: tuple[str, ...]
    dependencies: tuple[ChangeDependency, ...]
    executable: bool


@dataclass(frozen=True)
class ChangePreview:
    devices: tuple[DeviceChangePreview, ...]


_FIELD_SPECS: tuple[tuple[str, FieldCategory], ...] = (
    ("name", FieldCategory.CONFIGURED),
    ("manufacturer", FieldCategory.CONFIGURED),
    ("model", FieldCategory.CONFIGURED),
    ("serial", FieldCategory.CONFIGURED),
    ("site", FieldCategory.CONFIGURED),
    ("mac_address", FieldCategory.OPERATIONAL),
)

_UNSUPPORTED_FIELDS: tuple[str, ...] = (
    "profile",
    "overrides",
    "vlan",
    "poe",
    "speed_duplex",
    "lag",
    "lldp",
)


def build_difference_preview(
    netbox_snapshot: InventorySnapshot | None,
    unifi_snapshot: InventorySnapshot | None,
    result: DeduplicationResult,
) -> DifferencePreview:
    netbox_by_id = _device_index(netbox_snapshot)
    unifi_by_id = _device_index(unifi_snapshot)

    devices: list[DevicePreview] = []

    for pair in result.pairs:
        source = unifi_by_id.get(pair.unifi_observation_id)
        target = netbox_by_id.get(pair.netbox_observation_id)
        if source is None or target is None:
            continue
        fields = _field_previews(source, target)
        selectable = any(field.selectable for field in fields)
        selected = any(field.selected for field in fields)
        devices.append(
            DevicePreview(
                device_key=f"{pair.unifi_observation_id}->{pair.netbox_observation_id}",
                action=DeviceAction.UPDATE,
                source_label=source.name or source.source_id,
                target_label=target.name or target.source_id,
                provenance=(
                    f"Matched by {pair.reason}.",
                    "Field provenance: source=UniFi, target=NetBox.",
                ),
                unsupported_fields=_UNSUPPORTED_FIELDS,
                selectable=selectable,
                selected=selected,
                fields=fields,
            )
        )

    for observation_id in result.unmatched_unifi:
        source = unifi_by_id.get(observation_id)
        if source is None:
            continue
        fields = _create_fields(source)
        devices.append(
            DevicePreview(
                device_key=f"create:{observation_id}",
                action=DeviceAction.CREATE,
                source_label=source.name or source.source_id,
                target_label="",
                provenance=(
                    "No NetBox match found.",
                    "Field provenance: source=UniFi, target=empty.",
                ),
                unsupported_fields=_UNSUPPORTED_FIELDS,
                selectable=True,
                selected=True,
                fields=fields,
            )
        )

    for observation_id in result.unmatched_netbox:
        target = netbox_by_id.get(observation_id)
        if target is None:
            continue
        fields = _target_only_fields(target)
        devices.append(
            DevicePreview(
                device_key=f"target-only:{observation_id}",
                action=DeviceAction.TARGET_ONLY,
                source_label="",
                target_label=target.name or target.source_id,
                provenance=(
                    "Only present in NetBox.",
                    "No source change is proposed.",
                ),
                unsupported_fields=(),
                selectable=False,
                selected=False,
                fields=fields,
            )
        )

    return DifferencePreview(devices=tuple(devices))


def select_batch(preview: DifferencePreview, selected: bool) -> DifferencePreview:
    return DifferencePreview(
        devices=tuple(
            _set_device_selected(device, selected) for device in preview.devices
        )
    )


def select_device(
    preview: DifferencePreview,
    device_key: str,
    selected: bool,
) -> DifferencePreview:
    devices: list[DevicePreview] = []
    for device in preview.devices:
        if device.device_key != device_key:
            devices.append(device)
            continue
        devices.append(_set_device_selected(device, selected))
    return DifferencePreview(devices=tuple(devices))


def select_field(
    preview: DifferencePreview,
    device_key: str,
    field_name: str,
    selected: bool,
) -> DifferencePreview:
    devices: list[DevicePreview] = []
    for device in preview.devices:
        if device.device_key != device_key:
            devices.append(device)
            continue
        fields = []
        for field in device.fields:
            if field.name == field_name and field.selectable:
                fields.append(replace(field, selected=selected))
            else:
                fields.append(field)
        device_selected = any(item.selected for item in fields if item.selectable)
        devices.append(replace(device, fields=tuple(fields), selected=device_selected))
    return DifferencePreview(devices=tuple(devices))


def build_change_preview(preview: DifferencePreview) -> ChangePreview:
    devices: list[DeviceChangePreview] = []
    for device in preview.devices:
        selected_fields = tuple(
            field.name
            for field in device.fields
            if field.supported and field.selectable and field.selected
        )
        dependencies = _change_dependencies(device, selected_fields)
        executable = device.selectable and all(item.satisfied for item in dependencies)
        devices.append(
            DeviceChangePreview(
                device_key=device.device_key,
                action=device.action,
                selected_fields=selected_fields,
                dependencies=dependencies,
                executable=executable,
            )
        )
    return ChangePreview(devices=tuple(devices))


def _set_device_selected(device: DevicePreview, selected: bool) -> DevicePreview:
    if not device.selectable:
        return device
    fields = tuple(
        replace(field, selected=selected) if field.selectable else field
        for field in device.fields
    )
    return replace(device, selected=selected, fields=fields)


def _change_dependencies(
    device: DevicePreview,
    selected_fields: tuple[str, ...],
) -> tuple[ChangeDependency, ...]:
    selected = set(selected_fields)
    fields_by_name = {field.name: field for field in device.fields}
    dependencies: list[ChangeDependency] = []

    has_selected = bool(selected)
    dependencies.append(
        ChangeDependency(
            name="selected_supported_fields",
            description="At least one supported and selected field is required.",
            required_fields=(),
            missing_fields=() if has_selected else ("<any>",),
            satisfied=has_selected,
        )
    )

    if device.action == DeviceAction.CREATE:
        required = ("name", "site")
        missing: list[str] = []
        for field_name in required:
            field = fields_by_name.get(field_name)
            if field is None:
                missing.append(field_name)
                continue
            if field_name not in selected or not field.source_value:
                missing.append(field_name)
        dependencies.append(
            ChangeDependency(
                name="create_required_identity",
                description=(
                    "Create previews require selected non-empty name and site values."
                ),
                required_fields=required,
                missing_fields=tuple(missing),
                satisfied=not missing,
            )
        )

    if "model" in selected:
        missing = () if "manufacturer" in selected else ("manufacturer",)
        dependencies.append(
            ChangeDependency(
                name="model_requires_manufacturer",
                description="Selected model updates depend on selected manufacturer.",
                required_fields=("model", "manufacturer"),
                missing_fields=missing,
                satisfied=not missing,
            )
        )

    if device.action == DeviceAction.TARGET_ONLY:
        dependencies.append(
            ChangeDependency(
                name="target_only_no_write",
                description="Target-only rows are informational and cannot be written.",
                required_fields=(),
                missing_fields=("source_change",),
                satisfied=False,
            )
        )

    return tuple(dependencies)


def _field_previews(
    source: InventoryDevice, target: InventoryDevice
) -> tuple[FieldPreview, ...]:
    previews: list[FieldPreview] = []
    for field_name, category in _FIELD_SPECS:
        source_value = _value(source, field_name)
        target_value = _value(target, field_name)
        changed = source_value != target_value
        selectable = changed
        previews.append(
            FieldPreview(
                name=field_name,
                category=category,
                source_value=source_value,
                target_value=target_value,
                changed=changed,
                supported=True,
                provenance=f"UniFi.{field_name} -> NetBox.{field_name}",
                selectable=selectable,
                selected=selectable,
            )
        )
    previews.extend(_unsupported_placeholders())
    return tuple(previews)


def _create_fields(source: InventoryDevice) -> tuple[FieldPreview, ...]:
    previews: list[FieldPreview] = []
    for field_name, category in _FIELD_SPECS:
        source_value = _value(source, field_name)
        previews.append(
            FieldPreview(
                name=field_name,
                category=category,
                source_value=source_value,
                target_value="",
                changed=bool(source_value),
                supported=True,
                provenance=f"UniFi.{field_name} -> NetBox.{field_name}",
                selectable=True,
                selected=bool(source_value),
            )
        )
    previews.extend(_unsupported_placeholders())
    return tuple(previews)


def _target_only_fields(target: InventoryDevice) -> tuple[FieldPreview, ...]:
    previews: list[FieldPreview] = []
    for field_name, category in _FIELD_SPECS:
        target_value = _value(target, field_name)
        previews.append(
            FieldPreview(
                name=field_name,
                category=category,
                source_value="",
                target_value=target_value,
                changed=False,
                supported=True,
                provenance=f"NetBox.{field_name} only",
                selectable=False,
                selected=False,
            )
        )
    return tuple(previews)


def _unsupported_placeholders() -> tuple[FieldPreview, ...]:
    return tuple(
        FieldPreview(
            name=field_name,
            category=FieldCategory.CONFIGURED,
            source_value="",
            target_value="",
            changed=False,
            supported=False,
            provenance="Unsupported in current preview slice.",
            selectable=False,
            selected=False,
        )
        for field_name in _UNSUPPORTED_FIELDS
    )


def _device_index(
    snapshot: InventorySnapshot | None,
) -> dict[str, InventoryDevice]:
    if snapshot is None:
        return {}
    return {
        _observation_id(snapshot.source, device): device for device in snapshot.devices
    }


def _observation_id(source: InventorySource, device: InventoryDevice) -> str:
    key = device.source_id.strip() or device.name.strip() or "unnamed"
    return f"{source}:{key}"


def _value(device: InventoryDevice, field_name: str) -> str:
    value = getattr(device, field_name)
    if not isinstance(value, str):
        return ""
    return value.strip()
