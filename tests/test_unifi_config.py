import pytest

from unifi2netbox.config import (
    ConfigError,
    NetBoxConfig,
    UniFiConfig,
    load_config,
    load_unifi_config,
    save_config,
    save_connections,
    save_unifi_config,
)


def test_old_netbox_config_needs_no_migration(tmp_path):
    path = tmp_path / "config.toml"
    netbox = NetBoxConfig("https://netbox.invalid", "synthetic-netbox")
    save_config(path, netbox)
    assert load_unifi_config(path) == UniFiConfig()
    assert load_config(path) == netbox


def test_sections_roundtrip_independently(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("# preserve\n[future]\nenabled = true\n", encoding="utf-8")
    netbox = NetBoxConfig("https://netbox.invalid", "synthetic-netbox")
    unifi = UniFiConfig(
        "https://console.invalid", "synthetic-unifi", False, site="site-id"
    )
    save_config(path, netbox)
    save_unifi_config(path, unifi)
    assert load_config(path) == netbox
    assert load_unifi_config(path) == unifi
    replacement = NetBoxConfig("https://new-netbox.invalid", "replacement-netbox")
    save_config(path, replacement)
    assert load_unifi_config(path) == unifi
    assert "# preserve" in path.read_text(encoding="utf-8")
    assert "synthetic-unifi" not in repr(unifi)
    assert load_config(path).verify_tls is True
    assert load_unifi_config(path).verify_tls is False


@pytest.mark.parametrize(
    "changes",
    [
        {"site": 42},
        {"site": "bad\nsite"},
        {"url": "console.invalid"},
        {"url": "https://console.invalid/proxy/network/integration/v1"},
        {"token": "bad\r\nkey"},
        {"verify_tls": "false"},
        {"timeout": 0},
    ],
)
def test_invalid_unifi_settings_are_rejected(changes):
    with pytest.raises(ConfigError):
        UniFiConfig(**changes)


def test_bad_other_section_does_not_block_valid_connection(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('unifi_network = 42\n[netbox]\nurl = "https://netbox.invalid"\n')
    assert load_config(path).url == "https://netbox.invalid"
    with pytest.raises(ConfigError, match="unifi_network"):
        load_unifi_config(path)


def test_missing_file_is_unconfigured(tmp_path):
    assert not load_unifi_config(tmp_path / "missing.toml").configured


def test_save_rejects_invalid_schema_without_overwriting(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("schema_version = true\n")
    original = path.read_bytes()
    with pytest.raises(ConfigError):
        save_unifi_config(path, UniFiConfig())
    assert path.read_bytes() == original


def test_combined_save_replaces_file_once_and_preserves_unrelated_data(
    tmp_path, monkeypatch
):
    path = tmp_path / "config.toml"
    path.write_text("# preserve\n[future]\nenabled = true\n", encoding="utf-8")
    netbox = NetBoxConfig("https://netbox.invalid", "synthetic-netbox")
    unifi = UniFiConfig("https://console.invalid", "synthetic-unifi")
    import os

    original_replace = os.replace
    replaced = []

    def replace(source, target):
        replaced.append(target)
        original_replace(source, target)

    monkeypatch.setattr("unifi2netbox.config.os.replace", replace)
    save_connections(path, netbox, unifi)
    assert replaced == [path]
    assert load_config(path) == netbox
    assert load_unifi_config(path) == unifi
    assert "# preserve" in path.read_text(encoding="utf-8")
    assert "[future]" in path.read_text(encoding="utf-8")


def test_combined_save_failure_preserves_both_connections(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    save_connections(path, NetBoxConfig(), UniFiConfig())
    previous = path.read_bytes()

    def fail(*args):
        raise PermissionError("synthetic failure")

    monkeypatch.setattr("unifi2netbox.config.os.replace", fail)
    with pytest.raises(ConfigError):
        save_connections(
            path,
            NetBoxConfig("https://netbox.invalid", "synthetic-netbox"),
            UniFiConfig("https://console.invalid", "synthetic-unifi"),
        )
    assert path.read_bytes() == previous
    assert not list(tmp_path.glob(".config-*"))
