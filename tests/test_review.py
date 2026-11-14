from datetime import datetime

from unifi2netbox.config import BehaviorConfig
from unifi2netbox.inventory import (
    InventoryDevice,
    InventoryDeviceRole,
    InventoryDeviceType,
    InventorySite,
    InventorySnapshot,
    InventorySource,
)
from unifi2netbox.matching import (
    deduplicate_inventory,
    suggest_device_types_for_unmatched,
)
from unifi2netbox.pipeline import (
    InventoryPreviewResult,
    WriteExecutionReport,
    WriteOutcome,
    preview_rows,
)
from unifi2netbox.preview import build_change_preview, build_difference_preview
from unifi2netbox.review import (
    ATTENTION,
    CREATE,
    IN_SYNC,
    NETBOX_ONLY,
    UPDATE,
    ReviewState,
    friendly_reason,
    humanize_timestamp,
)
from unifi2netbox.write_plan import build_write_plan


def _snapshot(source, devices, **catalogs):
    return InventorySnapshot(
        source=source,
        captured_at="2026-11-14T10:00:00+00:00",
        devices=tuple(devices),
        **catalogs,
    )


def make_result(role_catalog=("Access Point", "Switch")):
    netbox = _snapshot(
        InventorySource.NETBOX,
        [
            InventoryDevice(source_id="1", name="sw-a", serial="OLD", site="Home"),
            InventoryDevice(source_id="2", name="sw-b", serial="S2", site="Home"),
            InventoryDevice(source_id="3", name="legacy", site="Home"),
        ],
        device_types=(
            InventoryDeviceType("101", "Ubiquiti", "U6 Lite", "U6-Lite"),
            InventoryDeviceType("102", "Ubiquiti", "AC Professional", "UAP-AC-PRO"),
        ),
        device_roles=tuple(
            InventoryDeviceRole(str(i), name) for i, name in enumerate(role_catalog)
        ),
        sites=(InventorySite("7", "Home"),),
    )
    unifi = _snapshot(
        InventorySource.UNIFI_NETWORK,
        [
            InventoryDevice(source_id="a", name="sw-a", serial="NEW", site="Home"),
            InventoryDevice(source_id="b", name="sw-b", serial="S2", site="Home"),
            InventoryDevice(
                source_id="c",
                name="ap-1",
                manufacturer="Ubiquiti",
                model="U6 Lite",
                site="Home",
            ),
            InventoryDevice(
                source_id="d",
                name="ap-2",
                manufacturer="Ubiquiti",
                model="AC Pro",
                site="Home",
            ),
        ],
    )
    dedup = deduplicate_inventory(netbox, unifi)
    suggestions = suggest_device_types_for_unmatched(dedup, netbox, unifi)
    sites = frozenset({"Home"})
    diff = build_difference_preview(netbox, unifi, dedup, netbox_sites=sites)
    change = build_change_preview(diff)
    plan = build_write_plan(diff, change, netbox_sites=sites)
    return InventoryPreviewResult(
        status="Ready",
        details="",
        rows=preview_rows(diff, change, plan, suggestions=suggestions),
        netbox_device_types=(
            ("101", "Ubiquiti", "U6 Lite"),
            ("102", "Ubiquiti", "AC Professional"),
        ),
        netbox_device_roles=tuple(role_catalog),
        netbox_sites=("Home",),
        netbox_device_statuses=("active", "planned"),
        difference_preview=diff,
        write_plan=plan,
    )


def by_name(state, name):
    return next(item for item in state.rows() if item.name == name)


def test_rows_are_categorized_and_counted():
    state = ReviewState(make_result(), BehaviorConfig())

    assert by_name(state, "sw-a").category == UPDATE
    assert by_name(state, "sw-b").category == IN_SYNC
    assert by_name(state, "ap-1").category == CREATE
    assert by_name(state, "legacy").category == NETBOX_ONLY
    counts = state.counts()
    assert counts[CREATE] == 2
    assert counts[UPDATE] == 1
    assert counts[IN_SYNC] == 1
    assert counts[NETBOX_ONLY] == 1
    assert state.selected_count() == 3
    assert [item.name for item in state.rows(text="AP-")] == ["ap-1", "ap-2"]


def test_create_choices_use_exact_and_confident_types_and_defaults():
    state = ReviewState(
        make_result(), BehaviorConfig(default_device_role_name="Switch")
    )

    ap1 = by_name(state, "ap-1").key
    ap2 = by_name(state, "ap-2").key
    assert state.type_by_key[ap1] == "101"
    assert state.type_by_key[ap2] == "102"
    assert state.role_by_key[ap1] == "Switch"
    assert state.status_by_key[ap1] == "active"
    assert state.site_by_key[ap1] == "Home"


def test_deselecting_a_device_removes_its_operation():
    state = ReviewState(make_result(), BehaviorConfig())
    key = by_name(state, "ap-1").key

    state.set_device_selected(key, False)

    assert key not in {op.device_key for op in state.plan.operations}
    assert by_name(state, "ap-1").selected is False
    assert by_name(state, "ap-1").attention is False
    assert state.selected_count() == 2


def test_field_selection_controls_update_operation():
    state = ReviewState(make_result(), BehaviorConfig())
    key = by_name(state, "sw-a").key

    state.set_field_selected(key, "serial", False)

    assert key not in {op.device_key for op in state.plan.operations}


def test_missing_role_marks_create_rows_as_needing_attention():
    state = ReviewState(make_result(role_catalog=()), BehaviorConfig())

    ap1 = by_name(state, "ap-1")
    assert ap1.attention is True
    assert ap1.note == "Choose a device role"
    assert state.counts()[ATTENTION] == 2
    assert any("device role" in reason for reason in state.plan_blockers(state.plan))


def test_overrides_and_single_plan_are_limited_to_plan_creates():
    state = ReviewState(make_result(), BehaviorConfig())
    key = by_name(state, "ap-1").key

    single = state.plan_for(key)
    overrides = state.overrides(single)

    assert [op.device_key for op in single.operations] == [key]
    assert set(overrides["type"]) == {key}
    assert state.plan_for("missing") is None


def test_report_outcomes_are_attached_to_rows():
    state = ReviewState(make_result(), BehaviorConfig())
    key = by_name(state, "ap-1").key

    state.record_report(
        WriteExecutionReport(
            status="Applied",
            details="done",
            outcomes=(WriteOutcome(key, "success", "Created device in NetBox."),),
        )
    )

    assert by_name(state, "ap-1").outcome.status == "success"


def test_friendly_reason_and_timestamps():
    assert friendly_reason("selected_supported_fields: missing <any>") == (
        "Nothing selected to write"
    )
    assert friendly_reason("create_required_identity: missing name, site") == (
        "Missing name, site for a new device"
    )
    now = datetime.fromisoformat("2026-11-14T12:00:00+01:00")
    assert humanize_timestamp("2026-11-14T10:05:00+01:00", now) == "today 10:05"
    assert humanize_timestamp("2026-11-13T10:05:00+01:00", now) == "13 Nov 10:05"
    assert humanize_timestamp("", now) == "never"


def test_empty_state_has_no_rows():
    state = ReviewState()

    assert state.rows() == ()
    assert state.ready is False


def test_device_ids_are_parsed_from_preview_keys():
    from unifi2netbox.review import _device_ids

    assert _device_ids("unifi_network:a->netbox:1") == ("a", "1")
    assert _device_ids("create:unifi_network:c") == ("c", "")
    assert _device_ids("target-only:netbox:3") == ("", "3")


def test_ports_for_pairs_matched_devices_and_lists_new_device_ports():
    from dataclasses import replace

    from unifi2netbox.inventory import InventoryInterface, InventoryPort

    result = replace(
        make_result(),
        unifi_ports=(
            InventoryPort("a", 1, "RJ45", 1000, "UP", 1000),
            InventoryPort("a", 2, "RJ45", 1000, "DOWN", 0),
            InventoryPort("c", 1, "RJ45", 1000, "UP", 100),
        ),
        netbox_interfaces=(
            InventoryInterface("10", "1", "Port 1", "1000base-t"),
            InventoryInterface("11", "1", "Port 2", "1000base-t"),
            InventoryInterface("12", "2", "Port 1", "1000base-t"),
        ),
    )
    state = ReviewState(result, BehaviorConfig())

    sw_a = state.ports_for(by_name(state, "sw-a").key)
    assert [(m.port.idx, m.interface.name) for m in sw_a] == [
        (1, "Port 1"),
        (2, "Port 2"),
    ]
    ap1 = state.ports_for(by_name(state, "ap-1").key)
    assert [(m.port.idx, m.interface) for m in ap1] == [(1, None)]
    assert state.ports_for(by_name(state, "legacy").key) == ()


def test_devices_without_unifi_ports_show_no_port_comparison():
    from dataclasses import replace

    from unifi2netbox.inventory import InventoryInterface

    result = replace(
        make_result(),
        netbox_interfaces=(InventoryInterface("10", "1", "eth0", "1000base-t"),),
    )
    state = ReviewState(result, BehaviorConfig())

    assert state.ports_for(by_name(state, "sw-a").key) == ()
