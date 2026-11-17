"""Checks before a device type sync writes to NetBox (M14 slice 5).

**Blockers** stop the sync of a type because NetBox would refuse the change
or it would break placed devices:

- a new rack height (``u_height``) under which a racked device of the type
  would overlap another device or leave its rack, or a height of 0 for
  racked devices;
- a depth change (``is_full_depth``) that makes racked devices overlap the
  other face;
- a ``subdevice_role`` change while devices of the type are racked as
  children, sit in device bays, or hold devices in their bays;
- a slug, or a manufacturer and model, that another NetBox type already
  uses.

**Warnings** need the user's confirmation: field changes that apply to every
device of the type at once, and template changes, which NetBox applies only
to devices created later.

Reads only (GET): the devices of the type, their racks and the devices in
those racks, device bays when the subdevice role changes.
"""

from __future__ import annotations

from dataclasses import dataclass

from unifi2netbox.netbox_types import NetBoxTypes

BLOCKER = "blocker"
WARNING = "warning"
DEVICES = "/api/dcim/devices/"
RACKS = "/api/dcim/racks/"
DEVICE_BAYS = "/api/dcim/device-bays/"
# Fields whose change is visible on every device of the type.
VISIBLE = (
    "manufacturer",
    "model",
    "part_number",
    "u_height",
    "is_full_depth",
    "airflow",
    "weight",
    "weight_unit",
    "subdevice_role",
    "owner",
    "tags",
    "default_platform",
    "exclude_from_utilization",
)


@dataclass(frozen=True)
class Finding:
    level: str
    message: str

    def __str__(self) -> str:
        return f"{self.level.capitalize()}: {self.message}"


def preflight(plan, types: NetBoxTypes, backend) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    new, old = plan.local_doc, plan.netbox_doc
    fields = set(plan.fields)
    findings += _conflicts(plan, types, fields)
    rack_change = fields & {"u_height", "is_full_depth", "subdevice_role"}
    devices = (
        backend.list_objects(DEVICES, device_type_id=plan.type_id)
        if rack_change and plan.device_count
        else []
    )
    racked = [
        d for d in devices if _id(d.get("rack")) and d.get("position") is not None
    ]
    if fields & {"u_height", "is_full_depth"} and racked:
        findings += _rack_space(plan, types, backend, racked)
    if "subdevice_role" in fields and devices:
        findings += _subdevices(
            str(old.get("subdevice_role") or ""),
            str(new.get("subdevice_role") or ""),
            devices,
            racked,
            backend,
        )
    if plan.device_count:
        visible = sorted(fields & set(VISIBLE))
        if visible:
            findings.append(
                Finding(
                    WARNING,
                    f"{', '.join(visible)} change(s) at once on the "
                    f"{plan.device_count} device(s) of this type.",
                )
            )
        if plan.creates or plan.updates or plan.mapping_fronts:
            findings.append(
                Finding(
                    WARNING,
                    "Template changes apply only to devices created later; the "
                    f"{plan.device_count} existing device(s) keep their components.",
                )
            )
    return tuple(findings)


def _conflicts(plan, types: NetBoxTypes, fields) -> list[Finding]:
    new = plan.local_doc
    result = []
    others = [t for t in types.types if t.id != plan.type_id]
    slug = str(new.get("slug") or "")
    if "slug" in fields and any(str(t.doc.get("slug") or "") == slug for t in others):
        result.append(Finding(BLOCKER, f"Another NetBox type uses the slug {slug}."))
    if fields & {"manufacturer", "model"}:
        maker = str(new.get("manufacturer") or "").lower()
        model = str(new.get("model") or "").lower()
        if any(
            t.manufacturer.lower() == maker and t.model.lower() == model for t in others
        ):
            result.append(
                Finding(
                    BLOCKER,
                    f"Another NetBox type is {new.get('manufacturer')} "
                    f"{new.get('model')}.",
                )
            )
    return result


def _rack_space(plan, types: NetBoxTypes, backend, racked) -> list[Finding]:
    new = plan.local_doc
    height = _float(new.get("u_height"), 1.0)
    full_depth = new.get("is_full_depth")
    full_depth = True if full_depth is None else bool(full_depth)
    if height == 0:
        return [
            Finding(
                BLOCKER,
                f"A height of 0 U is not possible: {len(racked)} device(s) of this "
                "type are mounted in racks.",
            )
        ]
    heights = {
        t.id: (_float(t.doc.get("u_height"), 1.0), t.doc.get("is_full_depth", True))
        for t in types.types
    }
    heights[plan.type_id] = (height, full_depth)
    findings = []
    for rack_id in sorted({_id(d.get("rack")) for d in racked}):
        rack = backend.read_object(f"{RACKS}{rack_id}/") or {}
        start = _float(rack.get("starting_unit"), 1.0)
        top = start + _float(rack.get("u_height"), 42.0)
        placed = [
            d
            for d in backend.list_objects(DEVICES, rack_id=rack_id)
            if d.get("position") is not None
        ]
        ours = [d for d in placed if _id(d.get("device_type")) == plan.type_id]
        for device in ours:
            low = _float(device.get("position"), start)
            high = low + height
            if high > top:
                findings.append(
                    Finding(
                        BLOCKER,
                        f"{_name(device)} would leave rack {_name(rack)} "
                        f"({height:g} U from U{low:g}).",
                    )
                )
            for other in placed:
                if _id(other.get("id")) == _id(device.get("id")):
                    continue
                other_height, other_full = heights.get(
                    _id(other.get("device_type")), (1.0, True)
                )
                other_low = _float(other.get("position"), start)
                if not (low < other_low + other_height and other_low < high):
                    continue
                faces_meet = full_depth or other_full or _face(device) == _face(other)
                if faces_meet:
                    findings.append(
                        Finding(
                            BLOCKER,
                            f"{_name(device)} would overlap {_name(other)} in rack "
                            f"{_name(rack)} ({height:g} U from U{low:g}).",
                        )
                    )
    return findings


def _subdevices(old, new, devices, racked, backend) -> list[Finding]:
    findings = []
    if new == "child" and racked:
        findings.append(
            Finding(
                BLOCKER,
                f"Child devices cannot be mounted in racks; {len(racked)} device(s) "
                "of this type are.",
            )
        )
    if old == "child" and new != "child":
        children = [d for d in devices if d.get("parent_device")]
        if children:
            findings.append(
                Finding(
                    BLOCKER,
                    f"{len(children)} device(s) of this type sit in device bays.",
                )
            )
    if old == "parent" and new != "parent":
        used = 0
        for device in devices:
            bays = backend.list_objects(DEVICE_BAYS, device_id=_id(device.get("id")))
            used += sum(1 for bay in bays if bay.get("installed_device"))
        if used:
            findings.append(
                Finding(
                    BLOCKER,
                    f"{used} device bay(s) of devices of this type hold devices.",
                )
            )
    return findings


def _id(value) -> str:
    if isinstance(value, dict):
        value = value.get("id")
    return "" if value in (None, "") else str(value)


def _name(value) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or value.get("display") or value.get("id") or "")
    return str(value or "")


def _face(device) -> str:
    face = device.get("face")
    if isinstance(face, dict):
        face = face.get("value")
    return str(face or "front")


def _float(value, default: float) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except TypeError, ValueError:
        return default
