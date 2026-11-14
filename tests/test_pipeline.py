from unifi2netbox.config import NetBoxConfig, UniFiConfig
from unifi2netbox.inventory import (
    InventoryDevice,
    InventoryDeviceRole,
    InventoryError,
    InventorySite,
    InventorySnapshot,
    InventorySource,
)
from unifi2netbox.pipeline import build_inventory_preview

NETBOX = NetBoxConfig("https://netbox.invalid", "token")
UNIFI = UniFiConfig("https://console.invalid", "token", site="default")


def _snapshot(source: InventorySource, devices, **catalogs) -> InventorySnapshot:
    return InventorySnapshot(
        source=source,
        captured_at="2026-11-14T10:00:00+00:00",
        source_version="x",
        devices=tuple(devices),
        **catalogs,
    )


def _patch_readers(monkeypatch, netbox_reader, unifi_reader):
    monkeypatch.setattr("unifi2netbox.refresh.read_netbox_inventory", netbox_reader)
    monkeypatch.setattr("unifi2netbox.refresh.read_unifi_inventory", unifi_reader)


def test_build_inventory_preview_ready_produces_rows_and_plan(tmp_path, monkeypatch):
    netbox = _snapshot(
        InventorySource.NETBOX,
        [InventoryDevice(source_id="1", name="switch-a", serial="OLD", site="HQ")],
        device_roles=(InventoryDeviceRole(source_id="5", name="Switch"),),
        sites=(InventorySite(source_id="7", name="HQ"),),
    )
    unifi = _snapshot(
        InventorySource.UNIFI_NETWORK,
        [InventoryDevice(source_id="a", name="switch-a", serial="NEW", site="HQ")],
        unifi_api_feedback=({"endpoint": "info", "params": {}, "payload": {}},),
        unifi_raw_devices=({"id": "a", "name": "switch-a"},),
    )
    _patch_readers(monkeypatch, lambda config, **kw: netbox, lambda c, **kw: unifi)

    result = build_inventory_preview(
        tmp_path / "config.toml",
        NETBOX,
        UNIFI,
        include_all_netbox_delete_candidates=False,
    )

    assert result.status == "Ready"
    assert result.matched_devices == 1
    assert result.executable_operations == 1
    assert result.netbox_device_roles == ("Switch",)
    assert result.netbox_sites == ("HQ",)
    assert [row.action for row in result.rows] == ["update"]
    assert result.write_plan is not None
    assert result.difference_preview is not None
    assert (tmp_path / "snapshots.sqlite3").exists()
    assert result.unifi_captured_at == "2026-11-14T10:00:00+00:00"
    assert result.unifi_raw_devices == ({"id": "a", "name": "switch-a"},)
    assert result.unifi_api_feedback[0]["endpoint"] == "info"


def test_build_inventory_preview_partial_on_source_error(tmp_path, monkeypatch):
    unifi = _snapshot(InventorySource.UNIFI_NETWORK, [])

    def failing_netbox(config, **kwargs):
        raise InventoryError("NetBox read failed.")

    _patch_readers(monkeypatch, failing_netbox, lambda c, **kw: unifi)

    result = build_inventory_preview(
        tmp_path / "config.toml",
        NETBOX,
        UNIFI,
        include_all_netbox_delete_candidates=False,
    )

    assert result.status == "Partial"
    assert result.write_plan is None
    assert result.difference_preview is None
    assert result.detail_lines


def _site_fixture(monkeypatch):
    netbox = _snapshot(
        InventorySource.NETBOX,
        [InventoryDevice(source_id="1", name="switch-a", site="Home")],
        sites=(InventorySite(source_id="7", name="Home"),),
    )
    unifi = _snapshot(
        InventorySource.UNIFI_NETWORK,
        [
            InventoryDevice(source_id="a", name="switch-a", site="Default"),
            InventoryDevice(source_id="b", name="ap-new", site="Default"),
        ],
    )
    _patch_readers(monkeypatch, lambda c, **kw: netbox, lambda c, **kw: unifi)


def test_site_mapping_removes_site_updates_and_sets_create_site(tmp_path, monkeypatch):
    _site_fixture(monkeypatch)

    result = build_inventory_preview(
        tmp_path / "config.toml",
        NETBOX,
        UNIFI,
        include_all_netbox_delete_candidates=False,
        netbox_site_name="Home",
    )

    rows = {row.action: row for row in result.rows}
    assert rows["update"].selected_fields == ""
    assert "site" in rows["create"].selected_fields
    assert result.write_plan.issues == ()
    create = next(d for d in result.difference_preview.devices if d.action == "create")
    assert next(f for f in create.fields if f.name == "site").source_value == "Home"


def test_unknown_unifi_site_without_mapping_is_not_written(tmp_path, monkeypatch):
    _site_fixture(monkeypatch)

    result = build_inventory_preview(
        tmp_path / "config.toml",
        NETBOX,
        UNIFI,
        include_all_netbox_delete_candidates=False,
    )

    rows = {row.action: row for row in result.rows}
    assert rows["update"].selected_fields == ""
    assert "does not exist in NetBox" in rows["create"].blocked_reason
    assert [op.operation_type for op in result.write_plan.operations] == [
        "create_device"
    ]


def test_netbox_device_type_part_number_is_normalized():
    from unifi2netbox.inventory import _normalize_netbox_device_type

    item = _normalize_netbox_device_type(
        {
            "id": 7,
            "model": "UniFi Switch 24 Pro",
            "part_number": " USW-Pro-24 ",
            "manufacturer": {"name": "Ubiquiti"},
        }
    )

    assert item is not None
    assert item.part_number == "USW-Pro-24"


def test_reread_unifi_sources_applies_site_mapping(monkeypatch):
    from unifi2netbox.pipeline import reread_unifi_sources

    unifi = _snapshot(
        InventorySource.UNIFI_NETWORK,
        [InventoryDevice(source_id="a", name="switch-a", site="Default")],
    )
    monkeypatch.setattr(
        "unifi2netbox.pipeline.read_unifi_inventory", lambda config: unifi
    )

    sources, error = reread_unifi_sources(UNIFI, "Home")

    assert error == ""
    assert sources["unifi_network:a"].site == "Home"


def test_reread_unifi_sources_reports_errors(monkeypatch):
    from unifi2netbox.pipeline import reread_unifi_sources

    def failing(config):
        raise InventoryError("UniFi request timed out.")

    monkeypatch.setattr("unifi2netbox.pipeline.read_unifi_inventory", failing)

    assert reread_unifi_sources(UNIFI, "") == (None, "UniFi request timed out.")


def test_run_write_execution_passes_fresh_sources(monkeypatch):
    from unifi2netbox import pipeline
    from unifi2netbox.config import BehaviorConfig
    from unifi2netbox.write_execute import WriteExecutionResult
    from unifi2netbox.write_journal import initialize_journal
    from unifi2netbox.write_plan import WritePlan, WritePlanSummary

    captured = {}
    plan = WritePlan((), (), False, WritePlanSummary(0, 0, 0, 0, 0, (), False, ""))

    def fake_execute(*args, **kwargs):
        captured.update(kwargs)
        return WriteExecutionResult(
            journal=initialize_journal(plan, run_id="r", started_at="s")
        )

    monkeypatch.setattr(pipeline, "execute_write_plan", fake_execute)
    fresh_device = InventoryDevice(source_id="a", name="switch-a")
    monkeypatch.setattr(
        pipeline,
        "reread_unifi_snapshot",
        lambda config, site, protect=None: (
            _snapshot(InventorySource.UNIFI_NETWORK, [fresh_device]),
            "",
        ),
    )

    pipeline.run_write_execution(
        NETBOX,
        BehaviorConfig(),
        None,
        plan,
        role_overrides={},
        site_overrides={},
        status_overrides={},
        device_type_overrides={},
        dry_run=True,
        unifi_config=UNIFI,
    )

    assert captured["source_devices"] == {"unifi_network:a": fresh_device}
    assert captured["source_error"] == ""


def _journal_run(monkeypatch, tmp_path, journal_path):
    from unifi2netbox import pipeline
    from unifi2netbox.config import BehaviorConfig
    from unifi2netbox.write_execute import WriteExecutionResult
    from unifi2netbox.write_journal import (
        OperationOutcomeStatus,
        initialize_journal,
        record_operation_result,
    )
    from unifi2netbox.write_plan import (
        OperationType,
        WriteOperation,
        WritePlan,
        WritePlanSummary,
    )

    operation = WriteOperation(
        1, OperationType.CREATE_DEVICE, "create:unifi_network:c", "ap-1", "", ()
    )
    plan = WritePlan(
        (operation,), (), True, WritePlanSummary(1, 1, 0, 0, 0, (), True, "")
    )

    def fake_execute(*args, **kwargs):
        journal = initialize_journal(plan, run_id="run-1", started_at="start")
        journal = record_operation_result(
            journal, 1, OperationOutcomeStatus.SUCCESS, "Created.", "55"
        )
        return WriteExecutionResult(journal=journal)

    monkeypatch.setattr(pipeline, "execute_write_plan", fake_execute)
    return pipeline.run_write_execution(
        NETBOX,
        BehaviorConfig(),
        None,
        plan,
        role_overrides={},
        site_overrides={},
        status_overrides={},
        device_type_overrides={},
        dry_run=False,
        journal_path=journal_path,
    )


def test_run_write_execution_saves_history(monkeypatch, tmp_path):
    from unifi2netbox.journal_store import JournalStore

    path = tmp_path / "write-journal.sqlite3"
    report = _journal_run(monkeypatch, tmp_path, path)

    runs = JournalStore(path).recent()
    assert report.run_id == "run-1"
    assert [item.run_id for item in runs] == ["run-1"]
    assert runs[0].finished_at
    assert runs[0].outcomes[0].label == "ap-1"
    assert runs[0].outcomes[0].netbox_object_id == "55"


def test_history_save_failure_is_reported_not_raised(monkeypatch, tmp_path):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x", encoding="utf-8")

    report = _journal_run(monkeypatch, tmp_path, blocker / "write-journal.sqlite3")

    assert "Write history not saved" in report.details
    assert report.outcomes[0].status == "success"


def test_preview_result_carries_ports_and_interfaces(tmp_path, monkeypatch):
    from dataclasses import replace

    from unifi2netbox.inventory import InventoryInterface, InventoryPort

    netbox = _snapshot(
        InventorySource.NETBOX,
        [InventoryDevice(source_id="1", name="switch-a", site="HQ")],
        interfaces=(InventoryInterface("10", "1", "Port 1", "1000base-t"),),
    )
    unifi = replace(
        _snapshot(
            InventorySource.UNIFI_NETWORK,
            [InventoryDevice(source_id="a", name="switch-a", site="HQ")],
        ),
        ports=(InventoryPort("a", 1, "RJ45", 1000, "UP", 1000),),
    )
    _patch_readers(monkeypatch, lambda c, **kw: netbox, lambda c, **kw: unifi)

    result = build_inventory_preview(
        tmp_path / "config.toml",
        NETBOX,
        UNIFI,
        include_all_netbox_delete_candidates=False,
    )

    assert [p.idx for p in result.unifi_ports] == [1]
    assert [i.name for i in result.netbox_interfaces] == ["Port 1"]


def test_preview_result_carries_network_plan(tmp_path, monkeypatch):
    from dataclasses import replace

    from unifi2netbox.inventory import InventoryNetwork

    netbox = _snapshot(
        InventorySource.NETBOX,
        [],
        sites=(InventorySite(source_id="7", name="Home"),),
    )
    unifi = replace(
        _snapshot(InventorySource.UNIFI_NETWORK, []),
        networks=(InventoryNetwork("n1", "IoT", 20, True, "10.0.20.0/24"),),
    )
    _patch_readers(monkeypatch, lambda c, **kw: netbox, lambda c, **kw: unifi)

    result = build_inventory_preview(
        tmp_path / "config.toml",
        NETBOX,
        UNIFI,
        include_all_netbox_delete_candidates=False,
        netbox_site_name="Home",
    )

    assert result.network_plan.group.name == "UniFi Home"
    assert [row.name for row in result.network_plan.rows] == ["IoT"]


def test_run_write_execution_runs_networks_first_and_records_them(
    monkeypatch, tmp_path
):
    from unifi2netbox import pipeline
    from unifi2netbox.config import BehaviorConfig
    from unifi2netbox.journal_store import JournalStore
    from unifi2netbox.network_execute import NetworkOutcome
    from unifi2netbox.write_execute import WriteExecutionResult
    from unifi2netbox.write_journal import initialize_journal
    from unifi2netbox.write_plan import WritePlan, WritePlanSummary

    plan = WritePlan((), (), False, WritePlanSummary(0, 0, 0, 0, 0, (), False, ""))
    order = []

    def fake_networks(network_plan, backend, **kwargs):
        order.append("networks")
        return (
            NetworkOutcome(
                "network:n1",
                "create_vlan",
                "VLAN 20 IoT",
                "success",
                "Created.",
                "9",
                "verified",
                "ok",
            ),
        )

    def fake_execute(*args, **kwargs):
        order.append("devices")
        return WriteExecutionResult(
            journal=initialize_journal(plan, run_id="r", started_at="s")
        )

    monkeypatch.setattr(pipeline, "execute_network_plan", fake_networks)

    def fake_interfaces(interface_plan, backend, **kwargs):
        order.append("interfaces")
        return ()

    monkeypatch.setattr(pipeline, "execute_interface_plan", fake_interfaces)

    def fake_cables(cable_plan, backend, **kwargs):
        order.append("cables")
        return ()

    monkeypatch.setattr(pipeline, "execute_cable_plan", fake_cables)
    monkeypatch.setattr(pipeline, "execute_write_plan", fake_execute)
    path = tmp_path / "write-journal.sqlite3"

    report = pipeline.run_write_execution(
        NETBOX,
        BehaviorConfig(),
        None,
        plan,
        role_overrides={},
        site_overrides={},
        status_overrides={},
        device_type_overrides={},
        dry_run=False,
        journal_path=path,
        network_plan=object(),
    )

    assert order == ["networks", "interfaces", "cables", "devices"]
    assert "1 success" in report.details and "1 verified" in report.details
    assert report.outcomes[0].device_key == "network:n1"
    stored = JournalStore(path).recent()[0].outcomes[0]
    assert (stored.label, stored.operation_type) == ("VLAN 20 IoT", "create_vlan")


def test_protect_note_reports_counts_failures_and_cache():
    from unifi2netbox.pipeline import _protect_note
    from unifi2netbox.refresh import RefreshStatus

    two = InventorySnapshot(
        InventorySource.UNIFI_PROTECT,
        "2026-11-14T12:00:00+00:00",
        devices=(InventoryDevice("a", "x"), InventoryDevice("b", "y")),
    )

    assert _protect_note(None) == ""
    assert _protect_note(RefreshStatus(snapshot=two)) == "Protect: 2 devices read."
    assert _protect_note(
        RefreshStatus(snapshot=two, error="timeout", cached=True, stale=True)
    ) == ("Protect refresh failed: timeout Showing the last cached Protect snapshot.")


def test_protect_devices_join_matching_without_network_duplicates():
    from unifi2netbox.pipeline import merge_protect_devices

    network = InventorySnapshot(
        InventorySource.UNIFI_NETWORK,
        "2026-11-14T12:00:00+00:00",
        devices=(
            InventoryDevice(
                "sw", "switch", mac_address="AA:00:00:00:00:01", site="Home"
            ),
        ),
    )
    protect = InventorySnapshot(
        InventorySource.UNIFI_PROTECT,
        "2026-11-14T12:00:00+00:00",
        devices=(
            InventoryDevice(
                "c1", "Garden", mac_address="AA:00:00:00:00:02", kind="camera"
            ),
            InventoryDevice(
                "c2", "Dup", mac_address="AA:00:00:00:00:01", kind="camera"
            ),
        ),
    )

    merged, duplicates = merge_protect_devices(network, protect)

    assert duplicates == 1
    assert [(d.source_id, d.site) for d in merged.devices] == [
        ("sw", "Home"),
        ("protect:c1", "Home"),
    ]
    assert merge_protect_devices(network, None) == (network, 0)


def test_preview_uses_fresh_protect_only(monkeypatch, tmp_path):
    from unifi2netbox import pipeline
    from unifi2netbox.config import ProtectConfig
    from unifi2netbox.refresh import RefreshResult, RefreshStatus

    netbox = _snapshot(InventorySource.NETBOX, [])
    unifi = _snapshot(
        InventorySource.UNIFI_NETWORK, [InventoryDevice("sw", "switch", site="Home")]
    )
    protect = InventorySnapshot(
        InventorySource.UNIFI_PROTECT,
        "2026-11-14T12:00:00+00:00",
        devices=(InventoryDevice("c1", "Garden", kind="camera"),),
    )

    def run(protect_status):
        monkeypatch.setattr(
            pipeline,
            "refresh_snapshots",
            lambda *args: RefreshResult(
                RefreshStatus(snapshot=netbox),
                RefreshStatus(snapshot=unifi),
                protect_status,
            ),
        )
        return pipeline.build_inventory_preview(
            tmp_path / "config.toml",
            NETBOX,
            UniFiConfig("https://udm.invalid", "uf"),
            include_all_netbox_delete_candidates=False,
            protect_config=ProtectConfig("https://unvr.invalid", "pr"),
        )

    fresh = run(RefreshStatus(snapshot=protect))
    stale = run(RefreshStatus(snapshot=protect, error="timeout", cached=True))

    assert any("protect:c1" in row.device_key for row in fresh.rows)
    assert "Protect: 1 device read." in fresh.detail_lines
    assert not any("protect:c1" in row.device_key for row in stale.rows)
    assert any("Protect refresh failed" in line for line in stale.detail_lines)


def test_write_reread_merges_protect_and_tolerates_its_failure(monkeypatch):
    from unifi2netbox import pipeline
    from unifi2netbox.config import ProtectConfig
    from unifi2netbox.inventory import InventoryError

    network = _snapshot(
        InventorySource.UNIFI_NETWORK, [InventoryDevice("sw", "switch")]
    )
    protect = InventorySnapshot(
        InventorySource.UNIFI_PROTECT,
        "2026-11-14T12:00:00+00:00",
        devices=(InventoryDevice("c1", "Garden", kind="camera"),),
    )
    monkeypatch.setattr(pipeline, "read_unifi_inventory", lambda config: network)
    config = ProtectConfig("https://unvr.invalid", "pr")

    monkeypatch.setattr(
        "unifi2netbox.protect.read_protect_inventory", lambda config: protect
    )
    merged, error = pipeline.reread_unifi_snapshot(UniFiConfig(), "Home", config)
    assert error == "" and [d.source_id for d in merged.devices] == ["sw", "protect:c1"]

    def fail(config):
        raise InventoryError("denied")

    monkeypatch.setattr("unifi2netbox.protect.read_protect_inventory", fail)
    only_network, error = pipeline.reread_unifi_snapshot(UniFiConfig(), "Home", config)
    assert error == "" and [d.source_id for d in only_network.devices] == ["sw"]


def test_protect_creates_need_a_fitting_role_not_the_default(monkeypatch, tmp_path):
    from unifi2netbox import pipeline
    from unifi2netbox.config import BehaviorConfig, ProtectConfig
    from unifi2netbox.inventory import InventoryDeviceRole
    from unifi2netbox.refresh import RefreshResult, RefreshStatus
    from unifi2netbox.review import ReviewState

    protect = InventorySnapshot(
        InventorySource.UNIFI_PROTECT,
        "2026-11-14T12:00:00+00:00",
        devices=(InventoryDevice("c1", "Garden", kind="camera"),),
    )

    def preview(roles):
        netbox = _snapshot(
            InventorySource.NETBOX,
            [],
            device_roles=tuple(
                InventoryDeviceRole(str(i), name) for i, name in enumerate(roles)
            ),
        )
        unifi = _snapshot(
            InventorySource.UNIFI_NETWORK, [InventoryDevice("ap", "ap", site="Home")]
        )
        monkeypatch.setattr(
            pipeline,
            "refresh_snapshots",
            lambda *args: RefreshResult(
                RefreshStatus(snapshot=netbox),
                RefreshStatus(snapshot=unifi),
                RefreshStatus(snapshot=protect),
            ),
        )
        result = pipeline.build_inventory_preview(
            tmp_path / "config.toml",
            NETBOX,
            UniFiConfig("https://udm.invalid", "uf"),
            include_all_netbox_delete_candidates=False,
            protect_config=ProtectConfig("https://unvr.invalid", "pr"),
        )
        return ReviewState(
            result, BehaviorConfig(default_device_role_name="Access Point")
        )

    plain = preview(("Access Point", "Switch"))
    camera_key = next(row.key for row in plain.rows() if plain.protect_kind(row.key))
    ap_key = next(row.key for row in plain.rows() if not plain.protect_kind(row.key))
    assert plain.role_by_key.get(ap_key) == "Access Point"
    assert camera_key not in plain.role_by_key
    blockers = plain.plan_blockers(plain.plan_for(camera_key))
    assert any("Choose a NetBox device role" in text for text in blockers)

    with_camera = preview(("Access Point", "Camera"))
    assert with_camera.role_by_key[camera_key] == "Camera"
