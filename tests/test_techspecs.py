"""techspecs.ui.com lookups and drafts from UniFi data (M12 slice 3)."""

import json

import httpx
import pytest

from unifi2netbox.devicetypes import dump_yaml, errors, validate
from unifi2netbox.inventory import InventoryDevice, InventoryPort
from unifi2netbox.library import client
from unifi2netbox.techspecs import (
    TechSpecError,
    candidate_slugs,
    check_url,
    fetch_url,
    lookup,
    parse_page,
)
from unifi2netbox.typedraft import draft_from_unifi, interface_type


def text(label, value, parent=None, note=None):
    return {
        "__typename": "SpecificationEntitySectionFeatureEntryText",
        "value": value,
        "note": note,
        "feature": {"id": label, "label": label, "parentId": parent},
    }


def group(label):
    return {
        "__typename": "SpecificationEntitySectionFeatureGroup",
        "feature": {"id": f"group-{label}", "label": label, "parentId": None},
    }


def page(slug, sku, title, features, category="switching", kind="[product]"):
    data = {
        "page": f"/[productLine]/[category]/{kind}",
        "props": {
            "pageProps": {
                "category": category,
                "product": {
                    "slug": slug,
                    "name": sku,
                    "title": title,
                    "variants": [{"sku": sku}],
                    "technicalSpecification": {
                        "sections": [
                            {"section": {"label": "Overview"}, "features": features}
                        ]
                    },
                },
            }
        },
    }
    return (
        '<html><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(data)
        + "</script></html>"
    )


SWITCH = page(
    "usw-pro-24",
    "USW-Pro-24",
    "Switch Pro 24",
    [
        text("Dimensions", '442 x 285 x 44 mm \n(17.4 x 11.2 x 1.7")'),
        group("Port Layout"),
        text("1 GbE RJ45", "24\n(1G/100M/10M)", parent="group-Port Layout"),
        text("10G SFP+", "2\n(10G/1G)", parent="group-Port Layout"),
        text("Form Factor", "Rack mount (1U)"),
        text("Weight", "Without mounting brackets: 3.5 kg (7.7 lb)"),
        text("Max. Power Consumption", "30W"),
        text("Power Method", "(1) Universal input, 100-240V AC"),
    ],
)
INTERCOM = page(
    "ua-intercom",
    "UA-Intercom-EU",
    "Access Intercom",
    [
        text("Weight", "Device: 965 g (2.1 lb)"),
        text("Networking Interface", "(1) GbE RJ45 port"),
        text("Power Method", "PoE <b>802.3at</b>"),
    ],
    category="door-access",
)
HOME = page("", "", "", [], kind="")


def test_switch_page_is_parsed():
    spec = parse_page(SWITCH, "https://techspecs.ui.com/unifi/switching/usw-pro-24")

    assert (spec.slug, spec.sku, spec.title) == (
        "usw-pro-24",
        "USW-Pro-24",
        "Switch Pro 24",
    )
    assert spec.u_height == 1 and spec.rack_mount
    assert spec.dimensions == "442 x 285 x 44 mm"
    assert (spec.weight, spec.weight_unit, spec.max_power_w) == (3.5, "kg", 30)
    assert [(p.count, p.kind, p.speed_mbps) for p in spec.ports] == [
        (24, "RJ45", 1000),
        (2, "SFPPLUS", 10000),
    ]
    assert not spec.poe_powered


def test_intercom_page_uses_the_networking_interface_and_poe():
    spec = parse_page(INTERCOM, "https://techspecs.ui.com/unifi/x/ua-intercom")

    assert spec.url == "https://techspecs.ui.com/unifi/door-access/ua-intercom"
    assert spec.part_number == "UA-Intercom"
    assert [(p.count, p.kind) for p in spec.ports] == [(1, "RJ45")]
    assert spec.poe_powered and spec.poe_type == "type2-ieee802.3at"
    assert ("Power Method", "PoE 802.3at") in spec.fields
    assert parse_page(HOME, "x") is None and parse_page("<html/>", "x") is None


def transport(pages, seen):
    def handler(request):
        seen.append(str(request.url))
        slug = request.url.path.rsplit("/", 1)[-1]
        if slug == "moved":
            return httpx.Response(302, headers={"location": "https://evil.example/x"})
        return httpx.Response(200, text=pages.get(slug, HOME))

    return client(httpx.MockTransport(handler))


def test_lookup_tries_part_number_then_model_and_needs_a_matching_slug():
    seen = []
    http = transport({"usw-pro-24": SWITCH}, seen)

    assert candidate_slugs("USW Pro 24", "USW-Pro-24-EU") == (
        "usw-pro-24-eu",
        "usw-pro-24",
    )
    spec = lookup("USW Pro 24", "USW-Pro-24-EU", http)
    assert spec.sku == "USW-Pro-24"
    assert seen == [
        "https://techspecs.ui.com/unifi/switching/usw-pro-24-eu",
        "https://techspecs.ui.com/unifi/switching/usw-pro-24",
    ]
    assert lookup("Unknown Model", "", http) is None


def test_user_urls_are_limited_to_techspecs():
    assert (
        check_url("https://techspecs.ui.com/unifi/door-access/ua-intercom?s=eu#top")
        == "https://techspecs.ui.com/unifi/door-access/ua-intercom?s=eu"
    )
    for bad in (
        "http://techspecs.ui.com/unifi/x",
        "https://evil.example/unifi/x",
        "https://user:pw@techspecs.ui.com/unifi/x",
        "https://techspecs.ui.com/",
    ):
        with pytest.raises(TechSpecError):
            check_url(bad)
    seen = []
    http = transport({"ua-intercom": INTERCOM}, seen)
    assert fetch_url("https://techspecs.ui.com/unifi/a/ua-intercom", http).title
    with pytest.raises(TechSpecError, match="another site"):
        fetch_url("https://techspecs.ui.com/unifi/a/moved", http)
    with pytest.raises(TechSpecError, match="No product"):
        fetch_url("https://techspecs.ui.com/unifi/a/nothing", http)


def test_interface_types():
    assert interface_type("RJ45", 1000) == "1000base-t"
    assert interface_type("RJ45", 2500) == "2.5gbase-t"
    assert interface_type("RJ45", 0) == "1000base-t"
    assert interface_type("SFPPLUS", 10000) == "10gbase-x-sfpp"
    assert interface_type("SFP28", 25000) == "25gbase-x-sfp28"
    assert interface_type("XYZ", 0) == "other"


def test_draft_from_unifi_ports_and_techspecs():
    spec = parse_page(SWITCH, "u")
    device = InventoryDevice("a", "Core", model="USW Pro 24", manufacturer="Ubiquiti")
    ports = [
        InventoryPort("a", i, "RJ45", 1000, poe_type=2 if i == 1 else 0)
        for i in range(1, 25)
    ]
    ports += [
        InventoryPort("a", 25, "SFPPLUS", 10000),
        InventoryPort("a", 26, "SFPPLUS", 10000),
    ]

    doc, notes = draft_from_unifi(device, ports, spec)

    assert doc["model"] == "Switch Pro 24" and doc["part_number"] == "USW-Pro-24"
    assert doc["slug"] == "ubiquiti-usw-pro-24" and doc["u_height"] == 1
    names = [i["name"] for i in doc["interfaces"]]
    assert names[0] == "Port 1" and names[-2:] == ["SFP+ 1", "SFP+ 2"]
    assert doc["interfaces"][0]["poe_type"] == "type2-ieee802.3at"
    assert "poe_mode" not in doc["interfaces"][1]
    assert "techspecs.ui.com/unifi/switching/usw-pro-24" in doc["comments"]
    assert errors(validate(doc)) == ()
    assert not any("UniFi reports" in note for note in notes)

    fewer, notes = draft_from_unifi(device, ports[:24], spec)
    assert any("UniFi reports 24 Port, techspecs lists" in note for note in notes)


def test_draft_without_unifi_ports_or_specs():
    spec = parse_page(INTERCOM, "u")
    device = InventoryDevice("b", "Door", model="UA Intercom", manufacturer="Ubiquiti")

    doc, notes = draft_from_unifi(device, (), spec)
    assert doc["interfaces"] == [
        {
            "name": "eth0",
            "type": "1000base-t",
            "poe_mode": "pd",
            "poe_type": "type2-ieee802.3at",
        }
    ]
    assert any("from techspecs" in note for note in notes)

    plain, notes = draft_from_unifi(device, (), None)
    assert plain["part_number"] == "UA-Intercom" and "interfaces" not in plain
    assert any("No techspecs data" in note for note in notes)
    assert dump_yaml(plain).startswith(
        "---\nmanufacturer: Ubiquiti\nmodel: UA Intercom\n"
    )


def test_single_port_without_count_and_mbe_speed():
    camera = page(
        "uvc-g5-bullet",
        "UVC-G5-Bullet",
        "G5 Bullet",
        [
            text("Networking Interface", "10/100 MbE RJ45 port"),
            text("Power Method", "PoE"),
        ],
        category="physical-security",
    )
    spec = parse_page(camera, "u")

    assert [(p.count, p.kind, p.speed_mbps) for p in spec.ports] == [(1, "RJ45", 100)]
    device = InventoryDevice("c", "Cam", model="UVC G5 Bullet", manufacturer="Ubiquiti")
    doc, _ = draft_from_unifi(device, (), spec)
    assert doc["interfaces"] == [
        {"name": "eth0", "type": "100base-tx", "poe_mode": "pd"}
    ]


def test_draft_without_manufacturer_asks_for_it():
    doc, notes = draft_from_unifi(
        InventoryDevice("p", "Cam", model="CAM-PT2"), (), None
    )

    assert doc["manufacturer"] == "" and doc["slug"] == ""
    assert notes[0] == "UniFi reports no manufacturer: enter it before saving."
