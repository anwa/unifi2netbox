from dataclasses import dataclass
from datetime import UTC, datetime

from unifi2netbox.config import NetBoxConfig, UniFiConfig
from unifi2netbox.inventory import (
    InventoryError,
    InventorySnapshot,
    InventorySource,
    read_netbox_inventory,
    read_unifi_inventory,
)
from unifi2netbox.snapshots import SnapshotStore, StoredSnapshots


@dataclass(frozen=True)
class RefreshStatus:
    snapshot: InventorySnapshot | None = None
    previous_snapshot: InventorySnapshot | None = None
    last_updated: str = ""
    stale: bool = False
    cached: bool = False
    diagnostics: tuple[str, ...] = ()
    error: str = ""


@dataclass(frozen=True)
class RefreshResult:
    netbox: RefreshStatus
    unifi: RefreshStatus


@dataclass(frozen=True)
class BrowseStatus:
    snapshot: InventorySnapshot | None
    previous_snapshot: InventorySnapshot | None
    last_updated: str
    stale: bool
    diagnostics: tuple[str, ...]


@dataclass(frozen=True)
class BrowseResult:
    netbox: BrowseStatus
    unifi: BrowseStatus


def refresh_snapshots(
    netbox: NetBoxConfig,
    unifi: UniFiConfig,
    store: SnapshotStore,
) -> RefreshResult:
    netbox_status = _refresh_netbox(netbox, store)
    unifi_status = _refresh_unifi(unifi, store)
    return RefreshResult(netbox=netbox_status, unifi=unifi_status)


def _refresh_netbox(config: NetBoxConfig, store: SnapshotStore) -> RefreshStatus:
    try:
        snapshot = read_netbox_inventory(config)
    except InventoryError as error:
        return _failed_status(
            store.load_state(InventorySource.NETBOX),
            str(error),
            "NetBox",
        )
    store.save_current(snapshot)
    state = store.load_state(InventorySource.NETBOX)
    diagnostics = ("NetBox refresh succeeded.",)
    return RefreshStatus(
        snapshot=snapshot,
        previous_snapshot=state.previous,
        last_updated=state.updated_at,
        diagnostics=diagnostics,
    )


def _refresh_unifi(config: UniFiConfig, store: SnapshotStore) -> RefreshStatus:
    try:
        snapshot = read_unifi_inventory(config)
    except InventoryError as error:
        return _failed_status(
            store.load_state(InventorySource.UNIFI_NETWORK),
            str(error),
            "UniFi",
        )
    store.save_current(snapshot)
    state = store.load_state(InventorySource.UNIFI_NETWORK)
    diagnostics = ("UniFi refresh succeeded.",)
    return RefreshStatus(
        snapshot=snapshot,
        previous_snapshot=state.previous,
        last_updated=state.updated_at,
        diagnostics=diagnostics,
    )


def browse_cached_snapshots(
    store: SnapshotStore,
    *,
    max_age_seconds: int = 3600,
    now: datetime | None = None,
) -> BrowseResult:
    if max_age_seconds < 1:
        raise ValueError("max_age_seconds must be positive.")
    reference = now if now is not None else datetime.now(UTC)
    netbox = _browse_status(
        store.load_state(InventorySource.NETBOX),
        "NetBox",
        max_age_seconds,
        reference,
    )
    unifi = _browse_status(
        store.load_state(InventorySource.UNIFI_NETWORK),
        "UniFi",
        max_age_seconds,
        reference,
    )
    return BrowseResult(netbox=netbox, unifi=unifi)


def _failed_status(
    state: StoredSnapshots, error: str, source_label: str
) -> RefreshStatus:
    diagnostics = [f"{source_label} refresh failed: {error}"]
    cached = state.current is not None
    if cached:
        diagnostics.append("Using the last successful cached snapshot.")
    else:
        diagnostics.append("No cached snapshot is available yet.")
    return RefreshStatus(
        snapshot=state.current,
        previous_snapshot=state.previous,
        last_updated=state.updated_at,
        stale=cached,
        cached=cached,
        diagnostics=tuple(diagnostics),
        error=error,
    )


def _browse_status(
    state: StoredSnapshots,
    source_label: str,
    max_age_seconds: int,
    now: datetime,
) -> BrowseStatus:
    diagnostics: list[str] = []
    stale = False
    if state.current is None:
        diagnostics.append(f"No cached {source_label} snapshot is available.")
        stale = True
    else:
        try:
            stale = _snapshot_is_stale(state.current, max_age_seconds, now)
        except ValueError:
            stale = True
            diagnostics.append(
                f"Cached {source_label} snapshot has an invalid timestamp format."
            )
        if stale and not diagnostics:
            diagnostics.append(
                f"Cached {source_label} snapshot is older than "
                f"{max_age_seconds} seconds."
            )
        elif not stale:
            diagnostics.append(
                f"Cached {source_label} snapshot is within freshness limits."
            )
    return BrowseStatus(
        snapshot=state.current,
        previous_snapshot=state.previous,
        last_updated=state.updated_at,
        stale=stale,
        diagnostics=tuple(diagnostics),
    )


def _snapshot_is_stale(
    snapshot: InventorySnapshot,
    max_age_seconds: int,
    now: datetime,
) -> bool:
    captured = datetime.fromisoformat(snapshot.captured_at)
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=UTC)
    age = (now.astimezone(UTC) - captured.astimezone(UTC)).total_seconds()
    return age > max_age_seconds
