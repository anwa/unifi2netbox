"""Effective port configuration from internal UniFi payloads (synthetic)."""

import pytest

from unifi2netbox.port_config import (
    ACCESS,
    DISABLED,
    TAGGED,
    TAGGED_ALL,
    UNKNOWN,
    allowed_networks,
    allowed_profiles,
    resolve_port_configs,
)

NETWORKS = allowed_networks(
    [
        {"_id": "lan", "purpose": "corporate", "vlan_enabled": False},
        {"_id": "iot", "purpose": "corporate", "vlan_enabled": True, "vlan": 20},
        {"_id": "cam", "purpose": "corporate", "vlan_enabled": True, "vlan": 30},
        {"_id": "guest", "purpose": "guest", "vlan_enabled": True, "vlan": 60},
        {
            "_id": "wan",
            "purpose": "wan",
            "vlan_enabled": True,
            "vlan": 7,
            "x_password": "synthetic-secret",
        },
    ]
)
PROFILES = allowed_profiles(
    [
        {
            "_id": "p-cam",
            "name": "Cams",
            "forward": "native",
            "native_networkconf_id": "cam",
            "tagged_vlan_mgmt": "block_all",
        },
    ]
)


def resolve(*ports, macs=None):
    device = {"mac": "aa:bb:cc:00:00:01", "port_table": list(ports)}
    return resolve_port_configs(
        [device], PROFILES, NETWORKS, macs or {"aabbcc000001": "sw"}
    )


def test_networks_keep_only_port_capable_vlans_and_no_secrets():
    assert {key: n.vid for key, n in NETWORKS.items()} == {
        "lan": 1,
        "iot": 20,
        "cam": 30,
        "guest": 60,
    }
    assert "synthetic-secret" not in repr(NETWORKS)


@pytest.mark.parametrize(
    ("port", "mode", "native", "tagged"),
    [
        ({"forward": "disabled", "enable": False}, DISABLED, None, ()),
        ({"forward": "native", "native_networkconf_id": "iot"}, ACCESS, 20, ()),
        ({"forward": "all", "native_networkconf_id": ""}, TAGGED_ALL, 1, ()),
        ({"forward": "all", "native_networkconf_id": "iot"}, TAGGED_ALL, 20, ()),
        (
            {
                "forward": "customize",
                "tagged_vlan_mgmt": "auto",
                "native_networkconf_id": "lan",
            },
            TAGGED_ALL,
            1,
            (),
        ),
        (
            {
                "forward": "customize",
                "tagged_vlan_mgmt": "block_all",
                "native_networkconf_id": "iot",
            },
            ACCESS,
            20,
            (),
        ),
        (
            {
                "forward": "customize",
                "tagged_vlan_mgmt": "custom",
                "native_networkconf_id": "iot",
                "excluded_networkconf_ids": ["guest"],
            },
            TAGGED,
            20,
            (30,),
        ),
    ],
)
def test_forwarding_rules_resolve_to_effective_modes(port, mode, native, tagged):
    (config,) = resolve({"port_idx": 1, **port})

    assert (config.mode, config.native_vid, config.tagged_vids) == (
        mode,
        native,
        tagged,
    )


def test_tagged_all_is_explicit_and_never_expanded():
    (config,) = resolve({"port_idx": 1, "forward": "all"})

    assert config.tagged_vids == ()
    assert config.summary() == "tagged-all, native 1"


def test_profile_overrides_the_port_entry():
    (config,) = resolve(
        {
            "port_idx": 3,
            "portconf_id": "p-cam",
            "forward": "all",
            "native_networkconf_id": None,
        }
    )

    assert (config.profile, config.mode, config.native_vid) == ("Cams", ACCESS, 30)
    assert config.summary() == "access 30"


@pytest.mark.parametrize(
    ("port", "note", "mode"),
    [
        ({"portconf_id": "missing", "forward": "all"}, "profile is unknown", UNKNOWN),
        (
            {"forward": "native", "native_networkconf_id": "gone"},
            "Native network is unknown",
            ACCESS,
        ),
        ({"forward": "mirror"}, "Unknown forwarding mode", UNKNOWN),
        ({"forward": "customize", "tagged_vlan_mgmt": "odd"}, "tagging rule", UNKNOWN),
    ],
)
def test_unknown_inputs_are_reported_not_guessed(port, note, mode):
    (config,) = resolve({"port_idx": 1, **port})

    assert any(note in text for text in config.notes)
    assert config.mode == mode
    assert config.native_vid is None


def test_disabled_is_configuration_not_link_state():
    down, off = resolve(
        {"port_idx": 1, "enable": True, "up": False, "forward": "all"},
        {"port_idx": 2, "enable": False, "up": False, "forward": "disabled"},
    )

    assert (down.enabled, down.mode) == (True, TAGGED_ALL)
    assert (off.enabled, off.mode) == (False, DISABLED)


def test_lag_members_and_master_share_the_lag_id():
    configs = resolve(
        {"port_idx": 1, "forward": "all", "aggregated_by": False},
        {"port_idx": 7, "forward": "all"},
        {"port_idx": 8, "forward": "all", "aggregated_by": 7},
    )

    assert [(c.idx, c.lag_id) for c in configs] == [(1, None), (7, 7), (8, 7)]


def test_unknown_devices_and_bad_entries_are_ignored():
    assert resolve({"port_idx": 1, "forward": "all"}, macs={"ffffffffffff": "x"}) == ()
    assert resolve({"port_idx": "1"}, {"name": "no idx"}) == ()


def test_custom_trunk_with_everything_excluded():
    (config,) = resolve(
        {
            "port_idx": 1,
            "forward": "customize",
            "tagged_vlan_mgmt": "custom",
            "native_networkconf_id": "lan",
            "excluded_networkconf_ids": ["iot", "cam", "guest"],
        },
    )

    assert config.summary() == "tagged none, native 1"
