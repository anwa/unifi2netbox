from dataclasses import dataclass

from unifi2netbox.config import NetBoxConfig, UniFiConfig
from unifi2netbox.inventory import (
    InventoryError,
    InventorySnapshot,
    read_netbox_inventory,
    read_unifi_inventory,
)
from unifi2netbox.snapshots import SnapshotStore


@dataclass(frozen=True)
class RefreshStatus:
    snapshot: InventorySnapshot | None = None
    error: str = ""


@dataclass(frozen=True)
class RefreshResult:
    netbox: RefreshStatus
    unifi: RefreshStatus


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
        return RefreshStatus(error=str(error))
    store.save_current(snapshot)
    return RefreshStatus(snapshot=snapshot)


def _refresh_unifi(config: UniFiConfig, store: SnapshotStore) -> RefreshStatus:
    try:
        snapshot = read_unifi_inventory(config)
    except InventoryError as error:
        return RefreshStatus(error=str(error))
    store.save_current(snapshot)
    return RefreshStatus(snapshot=snapshot)
