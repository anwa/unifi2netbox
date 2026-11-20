"""NetBox restore: order, matching, modes and safeguards (M15 slices 2-3)."""

import pytest
from netbox_mem import MemNetBox, sample

from unifi2netbox.config import NetBoxConfig
from unifi2netbox.netbox_backup import create_backup
from unifi2netbox.netbox_restore import (
    CREATE,
    REPLACE,
    UPDATE,
    RestoreCancelled,
    natural_key,
    restore,
    restore_order,
)

CONFIG = NetBoxConfig(url="https://mem.example.com", token="t")


def backup_of(nb):
    return create_backup(CONFIG, session_factory=lambda c: nb)


def test_order_puts_dependencies_first():
    order = restore_order(backup_of(sample()))
    pos = order.index
    assert order[0] == "extras/tags"
    assert pos("dcim/manufacturers") < pos("dcim/device-types")
    assert (
        pos("dcim/device-types") < pos("dcim/interface-templates") < pos("dcim/devices")
    )
    assert pos("dcim/devices") < pos("dcim/interfaces") < pos("ipam/ip-addresses")
    assert pos("dcim/interfaces") < pos("dcim/cables")
    # devices -> primary_ip4 (optional) comes later and is patched afterwards
    assert pos("dcim/devices") < pos("ipam/ip-addresses")


def test_restore_into_an_empty_netbox_reproduces_the_source():
    source = sample()
    backup = backup_of(source)
    target = MemNetBox()

    plan = restore(backup, target, mode=CREATE, dry_run=True)
    assert target.writes == [] and not plan.errors
    assert plan.result("dcim/devices").create == 2
    assert plan.deferred == 1  # sw1's primary IP

    report = restore(
        backup, target, mode=CREATE, dry_run=False, expected_counts=plan.counts_before
    )
    assert not report.errors, report.errors
    assert report.verification == "verified", report.verification_detail
    assert target.canon() == source.canon()
    # interfaces from templates were matched, not created twice
    assert report.result("dcim/interfaces").create == 1  # only eth0.10
    assert report.result("dcim/interfaces").equal == 4
    assert report.files == 2

    again = restore(backup, target, mode=CREATE, dry_run=True)
    assert again.total("create") == 0 and again.total("update") == 0
    assert again.total("failed") == 0


def test_update_mode_restores_changed_values():
    source = sample()
    backup = backup_of(source)
    target = MemNetBox()
    restore(backup, target, mode=CREATE, dry_run=False)
    site = next(iter(target.data["dcim/sites"]))
    target.data["dcim/sites"][site]["status"] = "planned"
    iface = next(
        i for i, r in target.data["dcim/interfaces"].items() if r["name"] == "eth1"
    )
    target.data["dcim/interfaces"][iface]["type"] = "10gbase-x-sfpp"

    check = restore(backup, target, mode=CREATE, dry_run=True)
    assert check.total("update") == 0  # create mode leaves existing objects
    plan = restore(backup, target, mode=UPDATE, dry_run=True)
    assert plan.result("dcim/sites").update == 1
    assert plan.result("dcim/sites").changes[0][2] == ["status"]
    assert plan.result("dcim/interfaces").update == 1

    restore(backup, target, mode=UPDATE, dry_run=False)
    assert target.canon() == source.canon()


def test_replace_mode_empties_first_and_skip_excludes_objects():
    source = sample()
    backup = backup_of(source)
    target = MemNetBox()
    restore(backup, target, mode=CREATE, dry_run=False)
    target.add("dcim/sites", name="Extra", slug="extra")
    plan = restore(backup, target, mode=REPLACE, dry_run=True)
    assert (
        plan.result("dcim/sites").deleted == 2 and plan.result("dcim/sites").create == 1
    )
    assert target.count("/api/dcim/sites/") == 2  # dry run deletes nothing

    report = restore(backup, target, mode=REPLACE, dry_run=False)
    assert not report.errors, report.errors
    assert target.canon() == source.canon()

    fresh = MemNetBox()
    site = backup.endpoints["dcim/sites"][0]["id"]
    partial = restore(
        backup, fresh, mode=CREATE, dry_run=True, skip=[("dcim/sites", site)]
    )
    assert partial.result("dcim/sites").create == 0
    assert partial.result("dcim/devices").failed == 2  # site is required


def test_interrupted_batches_are_looked_up_and_drift_and_cancel_stop():
    source = sample()
    backup = backup_of(source)
    target = MemNetBox()
    target.fail_next_create = "dcim/manufacturers"
    report = restore(backup, target, mode=CREATE, dry_run=False)
    assert any("interrupted" in e for e in report.errors)
    assert target.canon() == source.canon()  # looked up, nothing duplicated

    other = MemNetBox()
    plan = restore(backup, other, mode=CREATE, dry_run=True)
    other.add("extras/tags", name="New", slug="new")
    drift = restore(
        backup, other, mode=CREATE, dry_run=False, expected_counts=plan.counts_before
    )
    assert "changed since the check" in drift.errors[0] and other.writes == []

    with pytest.raises(RestoreCancelled):
        restore(backup, MemNetBox(), dry_run=False, cancelled=lambda: True)


def test_natural_keys():
    fields = {"name": {}, "slug": {}}
    assert natural_key("dcim/sites", {"slug": "lab", "name": "Lab"}, fields) == ("lab",)
    assert natural_key("dcim/interfaces", {"device": 5, "name": "eth0"}, {}) == (
        5,
        "eth0",
    )
    assert natural_key(
        "dcim/interface-templates", {"device_type": 3, "name": "e"}, {}
    ) == (
        3,
        None,
        "e",
    )
    assert natural_key("dcim/devices", {"name": None, "site": 2}, {}) is None
    assert natural_key("ipam/ip-addresses", {"address": "10.0.0.1/24"}, {}) == (
        "10.0.0.1/24",
        None,
    )


def test_cycles_over_optional_references_keep_required_parents_first():
    order = restore_order(backup_of(sample()))
    pos = order.index
    # the cycle devices -> ip-addresses -> interfaces -> devices is broken at
    # the optional primary IP: devices, then interfaces, then IPs and cables
    assert pos("dcim/devices") < pos("dcim/interfaces") < pos("dcim/cables")


def test_template_components_missing_in_the_source_are_removed_once():
    source = sample()
    sw2 = next(i for i, r in source.data["dcim/devices"].items() if r["name"] == "sw2")
    gone = next(
        i
        for i, r in source.data["dcim/interfaces"].items()
        if r["device"] == sw2 and r["name"] == "eth1"
    )
    del source.data["dcim/interfaces"][gone]  # removed from the device by hand
    backup = backup_of(source)
    target = MemNetBox()
    report = restore(backup, target, mode=CREATE, dry_run=False)
    assert report.result("dcim/interfaces").removed == 1
    assert "made from templates" in report.summary()
    assert target.canon() == source.canon()

    # existing devices' components are never removed by this rule
    target.add(
        "dcim/interfaces",
        device=next(
            i for i, r in target.data["dcim/devices"].items() if r["name"] == "sw1"
        ),
        name="extra",
        type="virtual",
    )
    again = restore(backup, target, mode=CREATE, dry_run=False)
    assert again.result("dcim/interfaces").removed == 0
    assert any(r["name"] == "extra" for r in target.data["dcim/interfaces"].values())


def test_images_are_not_uploaded_again():
    source = sample()
    backup = backup_of(source)
    target = MemNetBox()
    restore(backup, target, mode=CREATE, dry_run=False)
    target.writes.clear()
    report = restore(backup, target, mode=CREATE, dry_run=False)
    assert report.files == 0 and not [w for w in target.writes if w[0] == "UPLOAD"]


def test_create_mode_gives_template_components_the_backup_values():
    source = sample()
    sw1 = next(i for i, r in source.data["dcim/devices"].items() if r["name"] == "sw1")
    eth1 = next(
        i
        for i, r in source.data["dcim/interfaces"].items()
        if r["device"] == sw1 and r["name"] == "eth1"
    )
    source.data["dcim/interfaces"][eth1]["type"] = "10gbase-x-sfpp"  # not the template
    backup = backup_of(source)
    target = MemNetBox()
    report = restore(backup, target, mode=CREATE, dry_run=False)
    assert report.result("dcim/interfaces").update == 1
    assert target.canon() == source.canon()
