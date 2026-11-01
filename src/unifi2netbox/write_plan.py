from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from unifi2netbox.preview import ChangePreview, DeviceAction, DifferencePreview


class OperationType(StrEnum):
    CREATE_DEVICE = "create_device"
    UPDATE_DEVICE = "update_device"


class IssueSeverity(StrEnum):
    BLOCKER = "blocker"
    WARNING = "warning"


@dataclass(frozen=True)
class PreflightIssue:
    device_key: str
    severity: IssueSeverity
    code: str
    message: str


@dataclass(frozen=True)
class WriteOperation:
    sequence: int
    operation_type: OperationType
    device_key: str
    source_label: str
    target_label: str
    selected_fields: tuple[str, ...]


@dataclass(frozen=True)
class WritePlan:
    operations: tuple[WriteOperation, ...]
    issues: tuple[PreflightIssue, ...]
    executable: bool
    summary: WritePlanSummary


@dataclass(frozen=True)
class WritePlanSummary:
    total_operations: int
    create_operations: int
    update_operations: int
    blocker_issues: int
    warning_issues: int
    blocked_device_keys: tuple[str, ...]
    requires_confirmation: bool
    confirmation_message: str


def build_write_plan(
    difference_preview: DifferencePreview,
    change_preview: ChangePreview,
) -> WritePlan:
    devices = {device.device_key: device for device in difference_preview.devices}

    raw_operations: list[tuple[OperationType, str, str, str, tuple[str, ...]]] = []
    issues: list[PreflightIssue] = []

    for item in change_preview.devices:
        device = devices.get(item.device_key)
        if device is None:
            issues.append(
                PreflightIssue(
                    device_key=item.device_key,
                    severity=IssueSeverity.BLOCKER,
                    code="missing_device_preview",
                    message=(
                        "Change references a device that is absent in preview " "data."
                    ),
                )
            )
            continue

        if not item.selected_fields:
            continue

        if not item.executable:
            issues.append(
                PreflightIssue(
                    device_key=item.device_key,
                    severity=IssueSeverity.BLOCKER,
                    code="dependency_blocked",
                    message="Selected fields violate dependency requirements.",
                )
            )
            continue

        if item.action == DeviceAction.CREATE:
            raw_operations.append(
                (
                    OperationType.CREATE_DEVICE,
                    item.device_key,
                    device.source_label,
                    device.target_label,
                    item.selected_fields,
                )
            )
        elif item.action == DeviceAction.UPDATE:
            raw_operations.append(
                (
                    OperationType.UPDATE_DEVICE,
                    item.device_key,
                    device.source_label,
                    device.target_label,
                    item.selected_fields,
                )
            )

        # TARGET_ONLY and unknown actions intentionally produce no write operation.

    _collect_preflight_conflicts(raw_operations, issues)

    # Ensure deterministic order: creates before updates, then by device key.
    raw_operations.sort(
        key=lambda item: (item[0] != OperationType.CREATE_DEVICE, item[1])
    )

    operations = tuple(
        WriteOperation(
            sequence=index,
            operation_type=op_type,
            device_key=device_key,
            source_label=source_label,
            target_label=target_label,
            selected_fields=fields,
        )
        for index, (
            op_type,
            device_key,
            source_label,
            target_label,
            fields,
        ) in enumerate(raw_operations, start=1)
    )

    executable = bool(operations) and not any(
        issue.severity == IssueSeverity.BLOCKER for issue in issues
    )

    summary = _build_summary(
        operations=operations, issues=tuple(issues), executable=executable
    )

    return WritePlan(
        operations=operations,
        issues=tuple(issues),
        executable=executable,
        summary=summary,
    )


def _build_summary(
    operations: tuple[WriteOperation, ...],
    issues: tuple[PreflightIssue, ...],
    executable: bool,
) -> WritePlanSummary:
    create_operations = sum(
        operation.operation_type == OperationType.CREATE_DEVICE
        for operation in operations
    )
    update_operations = sum(
        operation.operation_type == OperationType.UPDATE_DEVICE
        for operation in operations
    )
    blocker_issues = sum(issue.severity == IssueSeverity.BLOCKER for issue in issues)
    warning_issues = sum(issue.severity == IssueSeverity.WARNING for issue in issues)
    blocked_device_keys = tuple(
        sorted(
            {
                issue.device_key
                for issue in issues
                if issue.severity == IssueSeverity.BLOCKER
            }
        )
    )

    if executable:
        confirmation_message = (
            "Confirm execution of "
            f"{len(operations)} operations "
            f"({create_operations} create, {update_operations} update)."
        )
    elif not operations:
        confirmation_message = (
            "No eligible operations selected. Resolve selection or blockers before "
            "confirmation."
        )
    else:
        confirmation_message = (
            f"{len(operations)} operations prepared, but {blocker_issues} blocker "
            "issue(s) must be resolved before confirmation."
        )

    return WritePlanSummary(
        total_operations=len(operations),
        create_operations=create_operations,
        update_operations=update_operations,
        blocker_issues=blocker_issues,
        warning_issues=warning_issues,
        blocked_device_keys=blocked_device_keys,
        requires_confirmation=bool(operations),
        confirmation_message=confirmation_message,
    )


def _collect_preflight_conflicts(
    operations: list[tuple[OperationType, str, str, str, tuple[str, ...]]],
    issues: list[PreflightIssue],
) -> None:
    create_name_to_devices: dict[str, list[str]] = {}
    update_target_to_devices: dict[str, list[str]] = {}

    for op_type, device_key, source_label, target_label, _ in operations:
        if op_type == OperationType.CREATE_DEVICE and source_label.strip():
            create_name_to_devices.setdefault(source_label.strip().lower(), []).append(
                device_key
            )
        if op_type == OperationType.UPDATE_DEVICE and target_label.strip():
            update_target_to_devices.setdefault(
                target_label.strip().lower(), []
            ).append(device_key)

    for key, device_keys in create_name_to_devices.items():
        if len(device_keys) > 1:
            for device_key in device_keys:
                issues.append(
                    PreflightIssue(
                        device_key=device_key,
                        severity=IssueSeverity.BLOCKER,
                        code="duplicate_create_name",
                        message=(
                            f"Multiple create operations share the same source label "
                            f"'{key}'."
                        ),
                    )
                )

    for key, device_keys in update_target_to_devices.items():
        if len(device_keys) > 1:
            for device_key in device_keys:
                issues.append(
                    PreflightIssue(
                        device_key=device_key,
                        severity=IssueSeverity.BLOCKER,
                        code="duplicate_update_target",
                        message=(
                            f"Multiple update operations target the same device label "
                            f"'{key}'."
                        ),
                    )
                )
