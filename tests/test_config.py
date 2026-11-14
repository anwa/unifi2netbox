import tomllib

import pytest

from unifi2netbox.config import (
    ConfigError,
    NetBoxConfig,
    UniFiConfig,
    load_config,
    save_config,
    save_connections,
)


def test_missing_file_is_unconfigured(tmp_path):
    assert not load_config(tmp_path / "missing.toml").configured


@pytest.mark.parametrize(
    "changes",
    [
        {"url": "netbox.invalid"},
        {"url": "https://user:password@netbox.invalid"},
        {"url": "https://netbox.invalid?token=secret"},
        {"url": "https://netbox.invalid/api/"},
        {"url": "https://netbox.invalid:bad"},
        {"url": "https://netbox.invalid:0"},
        {"url": 42},
        {"token": "secret\r\nheader"},
        {"verify_tls": "false"},
        {"timeout": True},
        {"timeout": float("nan")},
        {"timeout": 0},
        {"timeout": 61},
        {"ca_bundle": "missing-ca.pem"},
    ],
)
def test_invalid_settings_are_rejected(changes):
    with pytest.raises(ConfigError):
        NetBoxConfig(**changes)


def test_roundtrip_preserves_unrelated_settings_and_comments(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('# keep this\n[future]\nsite = "example"\n', encoding="utf-8")
    config = NetBoxConfig("https://netbox.invalid", "synthetic-token", False)
    save_config(path, config)
    assert load_config(path) == config
    assert "# keep this" in path.read_text(encoding="utf-8")
    assert tomllib.loads(path.read_text())["future"]["site"] == "example"
    assert "synthetic-token" not in repr(config)


@pytest.mark.parametrize(
    "content", ["[broken", "netbox = 42", "schema_version = 2", "schema_version = true"]
)
def test_bad_configuration_is_safe(tmp_path, content):
    path = tmp_path / "config.toml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_failed_atomic_replace_preserves_previous_file(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    save_config(path, NetBoxConfig())
    original = path.read_bytes()

    def fail(*args):
        raise PermissionError("synthetic failure")

    monkeypatch.setattr("unifi2netbox.config.os.replace", fail)
    with pytest.raises(ConfigError):
        save_config(path, NetBoxConfig("https://netbox.invalid", "replacement"))
    assert path.read_bytes() == original
    assert not list(tmp_path.glob(".config-*"))


def test_security_warnings():
    assert "HTTP" in NetBoxConfig("http://netbox.invalid").security_warning
    assert (
        "disabled"
        in NetBoxConfig("https://netbox.invalid", verify_tls=False).security_warning
    )
    assert not NetBoxConfig("https://netbox.invalid").security_warning


def test_protect_section_round_trips_and_keeps_other_sections(tmp_path):
    from unifi2netbox.config import ProtectConfig, load_protect_config

    path = tmp_path / "config.toml"
    netbox = NetBoxConfig("https://netbox.invalid", "nb")
    unifi = UniFiConfig("https://udm.invalid", "uf")
    protect = ProtectConfig("https://unvr.invalid", "pr", verify_tls=False)

    save_connections(path, netbox, unifi, protect=protect)

    assert load_protect_config(path) == protect
    assert load_config(path) == netbox
    save_connections(path, netbox, unifi)
    assert load_protect_config(path) == protect


def test_missing_protect_section_is_unconfigured(tmp_path):
    from unifi2netbox.config import load_protect_config

    path = tmp_path / "config.toml"
    save_connections(
        path,
        NetBoxConfig("https://netbox.invalid", "nb"),
        UniFiConfig("https://udm.invalid", "uf"),
    )

    assert not load_protect_config(path).configured


def test_access_section_round_trips_next_to_protect(tmp_path):
    from unifi2netbox.config import (
        AccessConfig,
        ProtectConfig,
        load_access_config,
        load_protect_config,
    )

    path = tmp_path / "config.toml"
    protect = ProtectConfig("https://unvr.invalid", "pr")
    access = AccessConfig("https://udm.invalid:12445", "ac", verify_tls=False)
    save_connections(
        path,
        NetBoxConfig("https://netbox.invalid", "nb"),
        UniFiConfig("https://udm.invalid", "uf"),
        protect=protect,
        access=access,
    )

    assert load_access_config(path) == access
    assert load_protect_config(path) == protect
