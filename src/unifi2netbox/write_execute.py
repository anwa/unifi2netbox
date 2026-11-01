from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import requests

from unifi2netbox.config import BehaviorConfig, NetBoxConfig
from unifi2netbox.preview import DevicePreview, DifferencePreview
from unifi2netbox.write_journal import (
    OperationOutcomeStatus,
    WriteJournal,
    finalize_journal,
    initialize_journal,
    record_operation_result,
)
from unifi2netbox.write_plan import OperationType, WriteOperation, WritePlan


class WriteExecutionError(ValueError):
    pass


class NetBoxWriteBackend(Protocol):
    def resolve_site_id(self, name: str) -> str: ...

    def resolve_role_id(self, name: str) -> str: ...

    def resolve_device_type_id(self, manufacturer: str, model: str) -> str: ...

    def create_device(self, payload: dict[str, object]) -> str: ...

    def update_device(self, device_id: str, payload: dict[str, object]) -> None: ...


@dataclass(frozen=True)
class WriteExecutionResult:
    journal: WriteJournal


def execute_write_plan(
    write_plan: WritePlan,
    difference_preview: DifferencePreview,
    netbox: NetBoxConfig,
    behavior: BehaviorConfig,
    *,
    run_id: str,
    started_at: str,
    finished_at: str,
    dry_run: bool = False,
    role_overrides: dict[str, str] | None = None,
    site_overrides: dict[str, str] | None = None,
    status_overrides: dict[str, str] | None = None,
    device_type_overrides: dict[str, str] | None = None,
    backend: NetBoxWriteBackend | None = None,
) -> WriteExecutionResult:
    journal = initialize_journal(write_plan, run_id=run_id, started_at=started_at)
    if not write_plan.executable:
        return WriteExecutionResult(
            journal=finalize_journal(journal, finished_at, cancelled=False)
        )

    device_by_key = {item.device_key: item for item in difference_preview.devices}
    resolved_backend = backend or RequestsNetBoxWriteBackend(netbox)
    resolved_role_overrides = role_overrides or {}
    resolved_site_overrides = site_overrides or {}
    resolved_status_overrides = status_overrides or {}
    resolved_device_type_overrides = device_type_overrides or {}

    for operation in write_plan.operations:
        device = device_by_key.get(operation.device_key)
        if device is None:
            journal = record_operation_result(
                journal,
                operation.sequence,
                OperationOutcomeStatus.FAILED,
                "Missing preview device for write operation.",
            )
            continue

        try:
            payload = _build_payload(
                operation,
                device,
                behavior,
                resolved_backend,
                role_name_override=resolved_role_overrides.get(
                    operation.device_key, ""
                ),
                site_name_override=resolved_site_overrides.get(
                    operation.device_key, ""
                ),
                status_value_override=resolved_status_overrides.get(
                    operation.device_key, ""
                ),
                device_type_id_override=resolved_device_type_overrides.get(
                    operation.device_key, ""
                ),
            )
        except WriteExecutionError as error:
            journal = record_operation_result(
                journal,
                operation.sequence,
                OperationOutcomeStatus.FAILED,
                str(error),
            )
            continue

        if dry_run:
            journal = record_operation_result(
                journal,
                operation.sequence,
                OperationOutcomeStatus.SKIPPED,
                "Dry-run mode: write operation was not executed.",
            )
            continue

        try:
            if operation.operation_type == OperationType.CREATE_DEVICE:
                created_id = resolved_backend.create_device(payload)
                journal = record_operation_result(
                    journal,
                    operation.sequence,
                    OperationOutcomeStatus.SUCCESS,
                    "Created device in NetBox.",
                    netbox_object_id=created_id,
                )
            elif operation.operation_type == OperationType.UPDATE_DEVICE:
                device_id = _update_target_id(operation)
                resolved_backend.update_device(device_id, payload)
                journal = record_operation_result(
                    journal,
                    operation.sequence,
                    OperationOutcomeStatus.SUCCESS,
                    "Updated device in NetBox.",
                    netbox_object_id=device_id,
                )
            else:
                journal = record_operation_result(
                    journal,
                    operation.sequence,
                    OperationOutcomeStatus.FAILED,
                    "Unsupported operation type.",
                )
        except (WriteExecutionError, requests.exceptions.RequestException) as error:
            journal = record_operation_result(
                journal,
                operation.sequence,
                OperationOutcomeStatus.FAILED,
                str(error),
            )

    return WriteExecutionResult(
        journal=finalize_journal(journal, finished_at, cancelled=False)
    )


def _build_payload(
    operation: WriteOperation,
    device: DevicePreview,
    behavior: BehaviorConfig,
    backend: NetBoxWriteBackend,
    *,
    role_name_override: str = "",
    site_name_override: str = "",
    status_value_override: str = "",
    device_type_id_override: str = "",
) -> dict[str, object]:
    source_values = {
        field.name: field.source_value.strip()
        for field in device.fields
        if field.name in operation.selected_fields
    }

    if operation.operation_type == OperationType.UPDATE_DEVICE:
        payload: dict[str, object] = {}
        if source_values.get("name"):
            payload["name"] = source_values["name"]
        if "serial" in source_values:
            payload["serial"] = source_values["serial"]
        if source_values.get("site"):
            payload["site"] = backend.resolve_site_id(source_values["site"])
        unsupported = {
            key for key in source_values if key not in {"name", "serial", "site"}
        }
        if unsupported:
            raise WriteExecutionError(
                "Unsupported update fields selected: "
                + ", ".join(sorted(unsupported))
                + "."
            )
        if not payload:
            raise WriteExecutionError("No writable update fields selected.")
        return payload

    if operation.operation_type == OperationType.CREATE_DEVICE:
        role_name = (
            role_name_override.strip() or behavior.default_device_role_name.strip()
        )
        if not role_name:
            raise WriteExecutionError(
                "Create requires a default NetBox device role in settings."
            )
        site_name = site_name_override.strip() or source_values.get("site", "")
        required = {
            "name": source_values.get("name", ""),
            "site": site_name,
            "manufacturer": source_values.get("manufacturer", ""),
            "model": source_values.get("model", ""),
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise WriteExecutionError(
                "Create is missing required fields: " + ", ".join(sorted(missing)) + "."
            )

        selected_device_type_id = device_type_id_override.strip()
        payload = {
            "name": required["name"],
            "site": backend.resolve_site_id(required["site"]),
            "device_role": backend.resolve_role_id(role_name),
            "device_type": (
                selected_device_type_id
                if selected_device_type_id
                else backend.resolve_device_type_id(
                    required["manufacturer"], required["model"]
                )
            ),
        }
        status_value = status_value_override.strip()
        if status_value:
            payload["status"] = status_value
        if "serial" in source_values and source_values["serial"]:
            payload["serial"] = source_values["serial"]
        return payload

    raise WriteExecutionError("Unsupported operation type.")


def _update_target_id(operation: WriteOperation) -> str:
    marker = "->netbox:"
    if marker not in operation.device_key:
        raise WriteExecutionError("Cannot extract NetBox target ID from update key.")
    value = operation.device_key.split(marker, maxsplit=1)[1].strip()
    if not value:
        raise WriteExecutionError("Cannot extract NetBox target ID from update key.")
    return value


class RequestsNetBoxWriteBackend:
    def __init__(self, config: NetBoxConfig) -> None:
        self.config = config
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Token {config.token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )
        self.base_url = config.url.rstrip("/")

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        response = self.session.request(
            method,
            f"{self.base_url}{path}",
            allow_redirects=False,
            verify=(self.config.ca_bundle or True) if self.config.verify_tls else False,
            timeout=(self.config.timeout, self.config.timeout),
            **kwargs,
        )
        if 300 <= response.status_code < 400:
            raise WriteExecutionError("Redirect refused by NetBox.")
        if response.status_code in {401, 403}:
            raise WriteExecutionError("NetBox write permission denied.")
        return response

    def resolve_site_id(self, name: str) -> str:
        response = self._request("GET", "/api/dcim/sites/", params={"name": name})
        site_id = _single_result_id(response, "site", name)
        return site_id

    def resolve_role_id(self, name: str) -> str:
        response = self._request(
            "GET", "/api/dcim/device-roles/", params={"name": name}
        )
        role_id = _single_result_id(response, "device role", name)
        return role_id

    def resolve_device_type_id(self, manufacturer: str, model: str) -> str:
        response = self._request(
            "GET",
            "/api/dcim/device-types/",
            params={"model": model},
        )
        if response.status_code != 200:
            raise WriteExecutionError(
                f"NetBox device type lookup failed with HTTP {response.status_code}."
            )
        payload = response.json()
        rows = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise WriteExecutionError("NetBox device type lookup payload is invalid.")
        matches = []
        normalized_manufacturer = _norm(manufacturer)
        for row in rows:
            if not isinstance(row, dict):
                continue
            manufacturer_info = row.get("manufacturer")
            if not isinstance(manufacturer_info, dict):
                continue
            row_manufacturer = _norm(str(manufacturer_info.get("name", "")))
            row_model = _norm(str(row.get("model", "")))
            if row_manufacturer == normalized_manufacturer and row_model == _norm(
                model
            ):
                matches.append(str(row.get("id", "")).strip())
        matches = [item for item in matches if item]
        if len(matches) != 1:
            raise WriteExecutionError(
                f"Expected exactly one NetBox device type for '{manufacturer} {model}'."
            )
        return matches[0]

    def create_device(self, payload: dict[str, object]) -> str:
        response = self._request("POST", "/api/dcim/devices/", json=payload)
        if response.status_code not in {200, 201}:
            raise WriteExecutionError(
                f"NetBox create failed with HTTP {response.status_code}."
            )
        data = response.json()
        if not isinstance(data, dict) or not str(data.get("id", "")).strip():
            raise WriteExecutionError("NetBox create response did not include an ID.")
        return str(data["id"])

    def update_device(self, device_id: str, payload: dict[str, object]) -> None:
        response = self._request(
            "PATCH", f"/api/dcim/devices/{device_id}/", json=payload
        )
        if response.status_code not in {200, 204}:
            raise WriteExecutionError(
                f"NetBox update failed with HTTP {response.status_code}."
            )


def _single_result_id(response: requests.Response, kind: str, name: str) -> str:
    if response.status_code != 200:
        raise WriteExecutionError(
            f"NetBox {kind} lookup failed with HTTP {response.status_code}."
        )
    payload = response.json()
    if not isinstance(payload, dict):
        raise WriteExecutionError(f"NetBox {kind} lookup payload is invalid.")
    rows = payload.get("results")
    if not isinstance(rows, list):
        raise WriteExecutionError(f"NetBox {kind} lookup payload is invalid.")
    ids = [str(row.get("id", "")).strip() for row in rows if isinstance(row, dict)]
    ids = [item for item in ids if item]
    if len(ids) != 1:
        raise WriteExecutionError(f"Expected exactly one NetBox {kind} for '{name}'.")
    return ids[0]


def _norm(value: str) -> str:
    return "".join(character.lower() for character in value if character.isalnum())
