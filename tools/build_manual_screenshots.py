"""Render the manual screenshots from a fictional demo network.

Usage (repository root, project .venv):

    python tools/build_manual_screenshots.py [output-folder]

The default output is ``manual/images``. Nothing is contacted: connection
checks return a synthetic "Online", and the inventory refresh is replaced by
fixed demo snapshots (site "Example Lab", private 10.20.x.x addresses, made-up
names and serials) that run through the real pipeline. The demo configuration
lives in a temporary folder and holds placeholder tokens only. Never point
this tool at real data: the manual is published with the repository.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThreadPool  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QLabel,
    QLineEdit,
    QStatusBar,
)

from unifi2netbox import pipeline, theme  # noqa: E402
from unifi2netbox.config import (  # noqa: E402
    DEFAULT_LIBRARY_REPOSITORY,
    BehaviorConfig,
    NetBoxConfig,
    UiConfig,
    UniFiConfig,
    load_access_config,
    load_behavior_config,
    load_config,
    load_drive_config,
    load_protect_config,
    load_unifi_config,
    save_connections,
    save_ui_config,
)
from unifi2netbox.details import (  # noqa: E402
    InventoryDhcpRange,
    InventoryReservation,
    InventorySfp,
    InventoryWlan,
)
from unifi2netbox.devicetypes import LocalTypeStore  # noqa: E402
from unifi2netbox.gui import MainWindow, SettingsDialog  # noqa: E402
from unifi2netbox.gui_manual import ManualWindow  # noqa: E402
from unifi2netbox.gui_review import ConfirmDialog, HistoryDialog  # noqa: E402
from unifi2netbox.gui_typepicker import DeviceTypePicker  # noqa: E402
from unifi2netbox.inventory import (  # noqa: E402
    InventoryDevice,
    InventoryDeviceRole,
    InventoryDeviceStatus,
    InventoryDeviceType,
    InventoryInterface,
    InventoryManufacturer,
    InventoryNetwork,
    InventoryPort,
    InventorySite,
    InventorySnapshot,
    InventorySource,
)
from unifi2netbox.journal_store import StoredOutcome, StoredRun  # noqa: E402
from unifi2netbox.library import (  # noqa: E402
    LibraryCache,
    LibraryEntry,
    LibraryIndex,
    cache_folder,
)
from unifi2netbox.links import UPLINK, InventoryLink  # noqa: E402
from unifi2netbox.netbox import ConnectionResult, ConnectionState  # noqa: E402
from unifi2netbox.port_config import ACCESS, TAGGED, InventoryPortConfig  # noqa: E402
from unifi2netbox.refresh import RefreshResult, RefreshStatus  # noqa: E402
from unifi2netbox.techspecs import SpecPorts, TechSpec  # noqa: E402
from unifi2netbox.typedraft import draft_from_unifi  # noqa: E402

SITE = "Example Lab"
WHEN = "2026-11-15T09:30:00+00:00"
WIDTH, HEIGHT = 1480, 860
# Shown instead of the temporary folder, whose path contains the user name.
DEMO_FOLDER = r"C:\Users\demo\AppData\Local\unifi2netbox"


def _mac(n: int) -> str:
    return f"02:00:5E:10:00:{n:02X}"


def _rj45(device: str, count: int) -> tuple[InventoryPort, ...]:
    return tuple(
        InventoryPort(device, i, "RJ45", 1000, "UP" if i <= 3 else "DOWN", 1000)
        for i in range(1, count + 1)
    )


def unifi_snapshot() -> InventorySnapshot:
    devices = (
        InventoryDevice(
            "gw",
            "Gateway",
            "DEMO0001",
            "UDM Pro",
            "Ubiquiti",
            _mac(1),
            SITE,
            "gateway",
            "ONLINE",
            "10.20.0.1",
            "4.3.6",
        ),
        InventoryDevice(
            "core",
            "Core Switch",
            "DEMO0002",
            "USW Pro 24",
            "Ubiquiti",
            _mac(2),
            SITE,
            "switch",
            "ONLINE",
            "10.20.0.2",
            "7.2.120",
        ),
        InventoryDevice(
            "office",
            "Office Switch",
            "DEMO0003",
            "USW Lite 8 PoE",
            "Ubiquiti",
            _mac(3),
            SITE,
            "switch",
            "ONLINE",
            "10.20.0.3",
            "7.2.120",
        ),
        InventoryDevice(
            "ap1",
            "AP Living Room",
            "DEMO0004",
            "U6 Lite",
            "Ubiquiti",
            _mac(4),
            SITE,
            "accessPoint",
            "ONLINE",
            "10.20.0.11",
            "6.7.31",
        ),
        InventoryDevice(
            "ap2",
            "AP Office",
            "DEMO0005",
            "U6 Pro",
            "Ubiquiti",
            _mac(5),
            SITE,
            "accessPoint",
            "ONLINE",
            "10.20.0.12",
            "6.7.31",
        ),
        InventoryDevice(
            "door",
            "Door Intercom",
            "DEMO0006",
            "UA Intercom",
            "Ubiquiti",
            _mac(6),
            SITE,
            "",
            "ONLINE",
            "10.20.0.40",
            "1.4.2",
        ),
    )
    ports = (
        *_rj45("gw", 8),
        InventoryPort("gw", 10, "SFPPLUS", 10000, "UP", 10000),
        *_rj45("core", 8),
        InventoryPort("core", 25, "SFPPLUS", 10000, "UP", 10000),
        InventoryPort("core", 26, "SFPPLUS", 10000, "DOWN"),
        *_rj45("office", 8),
    )
    configs = (
        InventoryPortConfig("core", 1, "Office Switch", True, TAGGED, 1, (30, 40)),
        InventoryPortConfig("core", 2, "AP Living Room", True, TAGGED, 1, (30, 40)),
        InventoryPortConfig("core", 3, "NAS", True, ACCESS, 1),
        InventoryPortConfig("core", 4, "Printer", True, ACCESS, 1),
        InventoryPortConfig("core", 5, "Port 5", True, ACCESS, 30),
        InventoryPortConfig(
            "core",
            25,
            "Uplink Gateway",
            True,
            TAGGED,
            1,
            (30, 40),
            "",
            None,
            (),
            10000,
            True,
        ),
        InventoryPortConfig("office", 1, "Uplink", True, TAGGED, 1, (30, 40)),
        InventoryPortConfig("office", 2, "AP Office", True, TAGGED, 1, (30, 40)),
    )
    networks = (
        InventoryNetwork("n1", "Default", 1, True, "10.20.0.0/24", "10.20.0.1", True),
        InventoryNetwork("n30", "IoT", 30, True, "10.20.30.0/24", "10.20.30.1"),
        InventoryNetwork("n40", "Guest", 40, True, "10.20.40.0/24", "10.20.40.1"),
    )
    return InventorySnapshot(
        InventorySource.UNIFI_NETWORK,
        WHEN,
        source_version="11.0.99",
        scope="Default",
        devices=devices,
        ports=ports,
        port_configs=configs,
        networks=networks,
        links=(
            InventoryLink("core", 25, "gw", 10, UPLINK),
            InventoryLink("office", 1, "core", 1, UPLINK),
        ),
        sfps=(
            InventorySfp(
                "core", 25, "UBNT", "UACC-OM-MM-10G-D", "DEMO-SFP-1", "10G BASE-SR", "A"
            ),
        ),
        dhcp_ranges=(
            InventoryDhcpRange(1, "Default", "10.20.0.100", "10.20.0.199"),
            InventoryDhcpRange(30, "IoT", "10.20.30.100", "10.20.30.199"),
            InventoryDhcpRange(40, "Guest", "10.20.40.100", "10.20.40.199"),
        ),
        wlans=(
            InventoryWlan("w1", "Example Home", True, "wpapsk", "wpa2", "ccmp", 1),
            InventoryWlan(
                "w2", "Example IoT", True, "wpapsk", "wpa2", "ccmp", 30, True
            ),
            InventoryWlan("w3", "Example Guest", True, "open", "", "", 40, False, True),
            InventoryWlan("w4", "Old Network", False, "wpapsk", "wpa2", "ccmp", 1),
        ),
        reservations=(
            InventoryReservation(
                _mac(20), "10.20.0.20", "NAS", "nas", "nas.example.lan"
            ),
            InventoryReservation(_mac(21), "10.20.0.30", "Printer", "printer"),
            InventoryReservation(_mac(22), "10.20.30.40", "", "thermostat"),
        ),
    )


def _interfaces(device: str, first_id: int, count: int, sfp: tuple[str, ...] = ()):
    rows = [
        InventoryInterface(str(first_id + i), device, f"Port {i}", "1000base-t")
        for i in range(1, count + 1)
    ]
    rows += [
        InventoryInterface(str(first_id + 50 + i), device, name, "10gbase-x-sfpp")
        for i, name in enumerate(sfp, start=1)
    ]
    return rows


def netbox_snapshot() -> InventorySnapshot:
    devices = (
        InventoryDevice(
            "1", "Gateway", "DEMO0001", "UDM Pro", "Ubiquiti", _mac(1), SITE
        ),
        InventoryDevice(
            "2", "Core Switch", "OLD-SERIAL", "USW Pro 24", "Ubiquiti", _mac(2), SITE
        ),
        InventoryDevice(
            "3",
            "Office Switch",
            "DEMO0003",
            "USW Lite 8 PoE",
            "Ubiquiti",
            _mac(3),
            SITE,
        ),
        InventoryDevice(
            "4", "AP Living Room", "DEMO0004", "U6 Lite", "Ubiquiti", _mac(4), SITE
        ),
        InventoryDevice(
            "5", "AP Attic", "DEMO0099", "UAP AC Lite", "Ubiquiti", _mac(9), SITE
        ),
    )
    interfaces = (
        _interfaces("1", 100, 8, ("SFP+ 1",))
        + _interfaces("2", 200, 8, ("SFP+ 1", "SFP+ 2"))
        + _interfaces("3", 300, 8)
    )
    return InventorySnapshot(
        InventorySource.NETBOX,
        WHEN,
        source_version="4.7.3",
        devices=devices,
        device_types=(
            InventoryDeviceType("11", "Ubiquiti", "UDM Pro", "UDM-Pro"),
            InventoryDeviceType("12", "Ubiquiti", "USW Pro 24", "USW-Pro-24"),
            InventoryDeviceType("13", "Ubiquiti", "USW Lite 8 PoE", "USW-Lite-8-PoE"),
            InventoryDeviceType("14", "Ubiquiti", "U6 Lite", "U6-Lite"),
            InventoryDeviceType("15", "Ubiquiti", "U6 Pro", "U6-Pro"),
        ),
        device_roles=(
            InventoryDeviceRole("21", "Access Point"),
            InventoryDeviceRole("22", "Gateway"),
            InventoryDeviceRole("23", "Switch"),
        ),
        sites=(InventorySite("31", SITE),),
        device_statuses=(
            InventoryDeviceStatus("active", "Active"),
            InventoryDeviceStatus("planned", "Planned"),
            InventoryDeviceStatus("offline", "Offline"),
        ),
        interfaces=tuple(interfaces),
        manufacturers=(InventoryManufacturer("41", "Ubiquiti"),),
    )


def demo_runs() -> tuple[StoredRun, ...]:
    def done(key, label, operation, message="Created in NetBox."):
        return StoredOutcome(
            key, label, operation, "success", message, "", "verified", "NetBox matches."
        )

    applied = StoredRun(
        "demo-2",
        "2026-11-15T09:42:10+00:00",
        "2026-11-15T09:42:14+00:00",
        False,
        (
            done("cf", "Custom Field firmware", "create_custom_field"),
            done("network:n30", "VLAN 30 IoT", "create_vlan"),
            done("network:n30", "Prefix 10.20.30.0/24", "create_prefix"),
            done("wlan:w2", "Wireless LAN Example IoT", "create_wireless_lan"),
            done("dev:2", "Core Switch", "update_device", "Updated serial, firmware."),
            done("dev:new", "AP Office", "create_device"),
            StoredOutcome(
                "reservation:10.20.0.30",
                "Reserved IP 10.20.0.30",
                "create_reserved_ip",
                "skipped",
                "NetBox got the IP address 10.20.0.30 since the preview; refresh.",
            ),
        ),
    )
    dry = StoredRun(
        "demo-1",
        "2026-11-15T09:38:02+00:00",
        "2026-11-15T09:38:05+00:00",
        True,
        (
            StoredOutcome(
                "dev:new", "AP Office", "create_device", "skipped", "Dry-run mode."
            ),
        ),
    )
    return (applied, dry)


def fake_refresh(*_args, **_kwargs) -> RefreshResult:
    return RefreshResult(
        netbox=RefreshStatus(snapshot=netbox_snapshot(), last_updated=WHEN),
        unifi=RefreshStatus(snapshot=unifi_snapshot(), last_updated=WHEN),
    )


def online(_config) -> ConnectionResult:
    return ConnectionResult(ConnectionState.ONLINE, "Demo data.", "4.7.3")


def unifi_online(_config) -> ConnectionResult:
    return ConnectionResult(ConnectionState.ONLINE, "Demo data.", "11.0.99", "Default")


DEMO_SPEC = TechSpec(
    url="https://techspecs.ui.com/unifi/door-access/ua-intercom",
    slug="ua-intercom",
    sku="UA-Intercom",
    title="Access Intercom",
    dimensions="324.8 x 113.7 x 28.3 mm",
    weight=965.0,
    weight_unit="g",
    poe_powered=True,
    poe_type="type2-ieee802.3at",
    ports=(SpecPorts(1, "RJ45", 1000),),
)
LIBRARY_NAMES = (
    ("Ubiquiti", "U6-Lite"),
    ("Ubiquiti", "U6-Pro"),
    ("Ubiquiti", "UDM-Pro"),
    ("Ubiquiti", "USW-Lite-8-PoE"),
    ("Ubiquiti", "USW-Pro-24"),
    ("Ubiquiti", "UA-Hub"),
    ("Cisco", "C9300-24P"),
)


def write_demo_types(folder: Path, config_path: Path) -> None:
    """A local definition (UA-Intercom) and a small fake library index."""
    device = InventoryDevice(
        "door", "Door Intercom", model="UA Intercom", manufacturer="Ubiquiti"
    )
    doc, _notes = draft_from_unifi(device, (), DEMO_SPEC)
    doc["airflow"] = "passive"
    LocalTypeStore(folder / "devicetype-library").write(doc)
    entries = tuple(
        LibraryEntry(maker, name, f"{maker}/{name}.yaml", f"{index:040x}")
        for index, (maker, name) in enumerate(LIBRARY_NAMES, start=1)
    )
    LibraryCache(cache_folder(config_path)).save_index(
        LibraryIndex(DEFAULT_LIBRARY_REPOSITORY, "master", WHEN, entries)
    )


def write_demo_config(folder: Path) -> Path:
    path = folder / "config.toml"
    save_connections(
        path,
        NetBoxConfig(url="https://netbox.example.com", token="demo-token"),
        UniFiConfig(url="https://unifi.example.com", token="demo-key"),
        BehaviorConfig(default_device_role_name="Access Point", netbox_site_name=SITE),
    )
    save_ui_config(path, UiConfig(theme="light"))
    write_demo_types(folder, path)
    return path


class Shooter:
    def __init__(self, app: QApplication, out: Path, folder: Path) -> None:
        self.app = app
        self.out = out
        self.folder = folder
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(2)
        self.path = write_demo_config(folder)

    def settle(self, window: MainWindow | None = None) -> None:
        for _ in range(200):
            self.app.processEvents()
            busy = window is not None and (
                window.inventory_runner.busy
                or any(
                    panel.runner.busy
                    for panel in (window.netbox, window.unifi)
                    if hasattr(panel.runner, "busy")
                )
            )
            if not busy:
                break
            self.pool.waitForDone(50)
        for _ in range(5):
            self.app.processEvents()

    def scrub(self, widget) -> None:
        """Replace the temporary folder in every visible text."""
        empty = self.folder / "empty"
        real = sorted(
            {
                str(empty),
                str(empty.resolve()),
                str(self.folder),
                str(self.folder.resolve()),
            },
            key=len,
            reverse=True,
        )

        def clean(text: str) -> str:
            for item in real:
                text = text.replace(item, DEMO_FOLDER)
            return text

        for label in widget.findChildren(QLabel):
            if any(item in label.text() for item in real):
                label.setText(clean(label.text()))
        for edit in widget.findChildren(QLineEdit):
            for getter, setter in (
                (edit.text, edit.setText),
                (edit.placeholderText, edit.setPlaceholderText),
            ):
                if any(item in getter() for item in real):
                    setter(clean(getter()))
        for bar in widget.findChildren(QStatusBar):
            message = bar.currentMessage()
            if any(item in message for item in real):
                bar.showMessage(clean(message))

    def save(self, widget, name: str) -> None:
        self.settle()
        self.scrub(widget)
        self.app.processEvents()
        widget.grab().save(str(self.out / f"{name}.png"))
        print("wrote", name)

    def window(self) -> MainWindow:
        window = MainWindow(
            self.path,
            self.pool,
            online,
            open_first_run=False,
            unifi_checker=unifi_online,
            protect_checker=online,
            access_checker=online,
            drive_checker=online,
        )
        window.resize(WIDTH, HEIGHT)
        window.show()
        self.settle(window)
        return window

    def run(self) -> None:
        first = MainWindow(
            self.folder / "empty" / "config.toml",
            self.pool,
            online,
            open_first_run=False,
        )
        first.resize(WIDTH, HEIGHT)
        first.show()
        self.save(first, "first-start")
        first.close()

        window = self.window()
        window.recheck()
        self.settle(window)
        self.save(window, "connected")
        window.refresh_inventory_preview()
        self.settle(window)
        self.select_device(window, "Core Switch")
        self.save(window, "review-overview")

        window.set_filter("create")
        self.select_device(window, "AP Office")
        self.save(window, "review-new-device")
        window.set_filter("netbox_only")
        self.save(window, "review-netbox-only")
        window.set_filter("update")
        self.select_device(window, "Gateway")
        self.save(window, "review-firmware")

        for name in (
            "networks",
            "interfaces",
            "cables",
            "addresses",
            "wireless",
            "modules",
        ):
            window.set_filter(name)
            self.save(window, f"review-{name}")

        # Device types: a new device without a type, the picker, the editor
        # and the chosen local definition that is imported on apply.
        window.set_filter("create")
        self.select_device(window, "Door Intercom")
        self.save(window, "review-new-device-type")
        door = "create:unifi_network:door"
        candidates, note = window.type_candidates()
        picker = DeviceTypePicker(
            candidates,
            hint="UA Intercom",
            hint_manufacturer="Ubiquiti",
            note=note,
            refresh_library=lambda: [],
            pool=self.pool,
            parent=window,
        )
        picker.resize(980, 660)
        picker.show()
        self.save(picker, "type-picker")
        picker.close()
        editor = window.show_type_editor()
        editor.resize(WIDTH, HEIGHT)
        local = next(c for c in candidates if c.source == "local")
        editor.open_path(Path(local.path))
        self.save(editor, "type-editor-table")
        editor.set_mode("yaml")
        self.save(editor, "type-editor-yaml")
        editor.set_mode("table")
        editor.close()
        window.set_device_type_choice(door, local)
        self.select_device(window, "Door Intercom")
        self.save(window, "review-device-type-import")

        window.set_filter("all")
        dialog = ConfirmDialog(
            window.review,
            window.review.plan,
            dry_run=False,
            network_plan=window.review.network_plan,
            interface_plan=window.review.interface_plan,
            cable_plan=window.review.cable_plan,
            custom_field_plan=window.review.custom_field_plan,
            mgmt_ip_plan=window.review.mgmt_ip_plan,
            sfp_plan=window.review.sfp_plan,
            site_detail_plan=window.review.site_detail_plan,
            type_import_plan=window.review.type_import_plan(),
        )
        dialog.show()
        self.save(dialog, "confirm-apply")
        dialog.close()

        settings = SettingsDialog(
            self.path,
            load_config(self.path),
            self.pool,
            online,
            unifi_config=load_unifi_config(self.path),
            unifi_checker=unifi_online,
            protect_config=load_protect_config(self.path),
            protect_checker=online,
            access_config=load_access_config(self.path),
            access_checker=online,
            drive_config=load_drive_config(self.path),
            drive_checker=online,
        )
        settings.show()
        for page, name in (
            ("NetBox", "settings-netbox"),
            ("UniFi Network", "settings-unifi-network"),
            ("UniFi Protect", "settings-unifi-protect"),
            ("UniFi Access", "settings-unifi-access"),
            ("UniFi Drive", "settings-unifi-drive"),
            ("Sync defaults", "settings-sync"),
            ("Device types", "settings-device-types"),
        ):
            settings.show_page(page)
            self.save(settings, name)
        settings.close()

        history = HistoryDialog(demo_runs(), window)
        history.resize(1100, 520)
        history.show()
        self.save(history, "write-history")
        history.close()

        manual = ManualWindow(window)
        manual.resize(WIDTH, HEIGHT)
        manual.show()
        self.save(manual, "manual-window")
        manual.close()

        theme.apply_theme(self.app, True)
        window.set_filter("all")
        self.select_device(window, "Core Switch")
        self.save(window, "dark-mode")
        theme.apply_theme(self.app, False)
        window.close()
        print("behavior site:", load_behavior_config(self.path).netbox_site_name)

    def select_device(self, window: MainWindow, name: str) -> None:
        model = window.table_model
        for row in range(model.rowCount()):
            if model.data(model.index(row, 1)) == name:
                window.table.selectRow(row)
                break
        self.settle(window)


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("manual/images")
    out.mkdir(parents=True, exist_ok=True)
    pipeline.refresh_snapshots = fake_refresh
    app = QApplication.instance() or QApplication([])
    theme.apply_theme(app, False)
    with tempfile.TemporaryDirectory() as folder:
        Shooter(app, out, Path(folder)).run()


if __name__ == "__main__":
    main()
