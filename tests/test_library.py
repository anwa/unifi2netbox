"""devicetype-library index, downloads and type search (M12 slice 2)."""

from pathlib import Path

import httpx
import pytest

from unifi2netbox.config import (
    ConfigError,
    DeviceTypesConfig,
    load_device_types_config,
    local_type_folder,
    save_device_types_config,
)
from unifi2netbox.devicetypes import LocalTypeStore, new_document
from unifi2netbox.inventory import InventoryDeviceType
from unifi2netbox.library import (
    LibraryCache,
    LibraryError,
    client,
    fetch_index,
    fetch_text,
    find,
)
from unifi2netbox.typesearch import (
    LIBRARY,
    LOCAL,
    NETBOX,
    TypeFilter,
    is_suggested,
    library_candidates,
    local_candidates,
    netbox_candidates,
    search,
)

FIXTURES = Path(__file__).parent / "fixtures" / "devicetype-library" / "device-types"
SHA_ROOT = "a" * 40
SHA_PRO = "b" * 40
SHA_PLUS = "c" * 40
CONFIG = DeviceTypesConfig()


def github(requests, *, truncated=False, status=200, headers=None):
    pro = (FIXTURES / "Ubiquiti" / "USW-Pro-24.yaml").read_text(encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if status != 200:
            return httpx.Response(status, headers=headers or {})
        path = request.url.path
        if path.endswith("/git/trees/master"):
            return httpx.Response(
                200,
                json={
                    "tree": [
                        {"path": "README.md", "type": "blob", "sha": "d" * 40},
                        {"path": "device-types", "type": "tree", "sha": SHA_ROOT},
                    ]
                },
            )
        if path.endswith(f"/git/trees/{SHA_ROOT}"):
            return httpx.Response(
                200,
                json={
                    "truncated": truncated,
                    "tree": [
                        {"path": "Ubiquiti", "type": "tree", "sha": "e" * 40},
                        {
                            "path": "Ubiquiti/USW-Pro-24.yaml",
                            "type": "blob",
                            "sha": SHA_PRO,
                        },
                        {"path": "Ubiquiti/U6+.yaml", "type": "blob", "sha": SHA_PLUS},
                        {"path": "Ubiquiti/notes.txt", "type": "blob", "sha": "f" * 40},
                    ],
                },
            )
        if request.url.host == "raw.githubusercontent.com":
            return httpx.Response(200, text=pro)
        return httpx.Response(404)

    return client(httpx.MockTransport(handler))


def test_index_lists_device_type_files_and_is_cached(tmp_path):
    requests = []
    index = fetch_index(CONFIG, github(requests))

    assert [(e.manufacturer, e.name) for e in index.entries] == [
        ("Ubiquiti", "U6+"),
        ("Ubiquiti", "USW-Pro-24"),
    ]
    assert requests[0] == (
        "https://api.github.com/repos/netbox-community/devicetype-library/git/trees/master"
    )
    cache = LibraryCache(tmp_path)
    cache.save_index(index)
    assert cache.load_index(CONFIG) == index
    other = DeviceTypesConfig(library_branch="develop")
    assert cache.load_index(other) is None
    assert find(index, ["usw-pro-24"])[0].sha == SHA_PRO


def test_files_are_downloaded_once_per_blob(tmp_path):
    requests = []
    http = github(requests)
    index = fetch_index(CONFIG, http)
    cache = LibraryCache(tmp_path)
    (plus,) = find(index, ["U6+"])

    first = fetch_text(CONFIG, plus, http, cache)
    second = fetch_text(CONFIG, plus, http, cache)

    raw = [url for url in requests if "raw.githubusercontent" in url]
    assert first == second and "manufacturer: Ubiquiti" in first
    assert raw == [
        "https://raw.githubusercontent.com/netbox-community/devicetype-library/"
        "master/device-types/Ubiquiti/U6%2B.yaml"
    ]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"truncated": True}, "incomplete"),
        ({"status": 404}, "Not found"),
        ({"status": 403, "headers": {"x-ratelimit-remaining": "0"}}, "rate limit"),
        ({"status": 500}, "HTTP 500"),
    ],
)
def test_index_errors_are_reported(kwargs, message):
    with pytest.raises(LibraryError, match=message):
        fetch_index(CONFIG, github([], **kwargs))


def test_device_types_config_round_trip_and_validation(tmp_path):
    path = tmp_path / "config.toml"
    assert load_device_types_config(path) == DeviceTypesConfig()
    assert (
        local_type_folder(DeviceTypesConfig(), path) == tmp_path / "devicetype-library"
    )
    config = DeviceTypesConfig(
        local_folder=str(tmp_path / "fork"),
        use_library=False,
        library_repository="me/devicetype-library",
        library_branch="feature/ubiquiti",
        use_techspecs=False,
    )
    save_device_types_config(path, config)
    assert load_device_types_config(path) == config
    assert local_type_folder(config, path) == tmp_path / "fork"
    with pytest.raises(ConfigError, match="owner/name"):
        DeviceTypesConfig(library_repository="https://github.com/x")
    with pytest.raises(ConfigError, match="branch"):
        DeviceTypesConfig(library_branch="a..b")


def candidates(tmp_path):
    store = LocalTypeStore(tmp_path)
    doc = new_document("Ubiquiti", "UniFi Switch Lite 8 PoE")
    doc["part_number"] = "USW-Lite-8-PoE"
    doc["interfaces"] = [
        {"name": "Port 1", "type": "1000base-t", "poe_mode": "pse"},
        {"name": "Port 2", "type": "1000base-t"},
    ]
    store.write(doc)
    cache = LibraryCache(tmp_path / "cache")
    index = fetch_index(CONFIG, github([]))
    (pro,) = find(index, ["USW-Pro-24"])
    cache.store_text(pro, (FIXTURES / "Ubiquiti" / "USW-Pro-24.yaml").read_text())
    return (
        netbox_candidates(
            [
                InventoryDeviceType("11", "Ubiquiti", "U6 Lite", "U6-Lite"),
                InventoryDeviceType("12", "Cisco", "Catalyst 9300-24P", "C9300-24P"),
            ]
        )
        + local_candidates(store.files(), store.read)
        + library_candidates(index, cache)
    )


def test_search_ranks_hint_matches_first_across_sources(tmp_path):
    items = candidates(tmp_path)

    result = search(items, hint="USW Pro 24", hint_manufacturer="Ubiquiti")
    assert result.candidates[0].part_number == "USW-Pro-24"
    assert result.candidates[0].source == LIBRARY
    assert is_suggested(result.candidates[0], "USW Pro 24")

    lite = search(items, [TypeFilter("search", "usw lite 8")])
    assert [c.source for c in lite.candidates] == [LOCAL]
    assert search(items, [TypeFilter("search", "U6+")]).candidates[0].source == LIBRARY


def test_filters_by_manufacturer_source_and_components(tmp_path):
    items = candidates(tmp_path)

    not_cisco = search(items, [TypeFilter("manufacturer", "Cisco", "is not")])
    assert all(c.manufacturer != "Cisco" for c in not_cisco.candidates)
    netbox = search(items, [TypeFilter("source", NETBOX)])
    assert {c.source for c in netbox.candidates} == {NETBOX}

    poe = search(items, [TypeFilter("poe", "yes")])
    assert [c.part_number for c in poe.candidates] == ["USW-Lite-8-PoE"]
    # NetBox types and the uncached U6+ cannot be checked for components.
    assert poe.unchecked == 3
    sfp = search(items, [TypeFilter("sfp", "yes")])
    assert [c.part_number for c in sfp.candidates] == ["USW-Pro-24"]
    racked = search(items, [TypeFilter("u_height", "1")])
    assert [c.part_number for c in racked.candidates] == ["USW-Pro-24"]


def test_settings_page_saves_device_type_sources(qtbot, tmp_path):
    from PySide6.QtCore import QThreadPool

    from unifi2netbox.config import NetBoxConfig
    from unifi2netbox.gui import SettingsDialog

    path = tmp_path / "config.toml"
    dialog = SettingsDialog(path, NetBoxConfig(), QThreadPool())
    qtbot.addWidget(dialog)
    dialog.show_page("Device types")
    page = dialog.device_types
    assert dialog.pages.currentWidget() is page
    assert "No library index" in page.index_status.text()
    assert page.local_folder.placeholderText().endswith("devicetype-library")

    page.use_library.setChecked(False)
    page.branch.setText("develop")
    assert not page.refresh_button.isEnabled()
    assert page.config_from_fields() == DeviceTypesConfig(
        use_library=False, library_branch="develop"
    )


def test_settings_page_refreshes_the_index_in_the_background(
    qtbot, tmp_path, monkeypatch
):
    from PySide6.QtCore import QThreadPool

    from unifi2netbox import gui_devicetypes
    from unifi2netbox.gui_devicetypes import DeviceTypeSettingsPage

    index = fetch_index(CONFIG, github([]))
    monkeypatch.setattr(gui_devicetypes, "refresh_index", lambda config, path: index)
    page = DeviceTypeSettingsPage(CONFIG, tmp_path / "config.toml", QThreadPool())
    qtbot.addWidget(page)

    with qtbot.waitSignal(page.runner.finished, timeout=5000):
        page.refresh()
    assert page.index_status.text().startswith("2 device types from 1 manufacturers")

    monkeypatch.setattr(
        gui_devicetypes,
        "refresh_index",
        lambda config, path: (_ for _ in ()).throw(LibraryError("offline")),
    )
    with qtbot.waitSignal(page.runner.finished, timeout=5000):
        page.refresh()
    assert page.index_status.text() == "Index not refreshed: offline"
