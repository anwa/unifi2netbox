"""Read UniFi product specifications from techspecs.ui.com (read-only).

Product pages are Next.js pages with a ``__NEXT_DATA__`` JSON script. The
product sits at ``props.pageProps.product`` (``slug``, ``name``, ``title``,
``variants[].sku``, ``technicalSpecification.sections[].features[]``); each
feature has ``feature.label``, an optional ``feature.parentId`` (children of
groups such as "Port Layout") and a ``value``, ``flag`` or ``note``.

The URL is ``/unifi/{category}/{slug}``; any valid category serves every
product, an unknown slug is answered with the home page (HTTP 200). A page
only counts when its Next.js page is a product page and its product slug
equals the requested slug. Only the slug is sent.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

import httpx

from unifi2netbox.devicetypes import slugify

HOST = "techspecs.ui.com"
BASE = f"https://{HOST}"
_NEXT_DATA = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)
_TAG = re.compile(r"<[^>]+>")
_DIMENSIONS = re.compile(r"[\d.]+\s*x\s*[\d.]+\s*x\s*[\d.]+\s*mm", re.I)
# Regional SKU suffixes; the library uses the plain part number.
_REGION = re.compile(r"-(US|EU|UK|CA|JP|AU|BR|IN|IL|MX|TW|KR|CN|NA)$", re.I)
_RACK = re.compile(r"\((\d+(?:\.\d+)?)\s*U\)", re.I)
_WEIGHT = re.compile(r"([\d.]+)\s*(kg|g)\b", re.I)
_WATTS = re.compile(r"([\d.]+)\s*W\b")
_KINDS = (
    ("QSFP28", "QSFP28"),
    ("SFP28", "SFP28"),
    ("SFP+", "SFPPLUS"),
    ("SFP", "SFP"),
    ("RJ45", "RJ45"),
)
_PORTS_IN_TEXT = re.compile(
    r"\((\d+)\)\s*([^()\n]*?)(QSFP28|SFP28|SFP\+|SFP|RJ45)", re.I
)


class TechSpecError(RuntimeError):
    pass


@dataclass(frozen=True)
class SpecPorts:
    count: int
    kind: str  # RJ45, SFP, SFPPLUS, SFP28, QSFP28
    speed_mbps: int = 0


@dataclass(frozen=True)
class TechSpec:
    url: str
    slug: str
    sku: str
    title: str
    u_height: float = 0
    rack_mount: bool = False
    dimensions: str = ""
    weight: float | None = None
    weight_unit: str = ""
    max_power_w: float | None = None
    poe_powered: bool = False
    poe_type: str = ""
    ports: tuple[SpecPorts, ...] = ()
    fields: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @property
    def part_number(self) -> str:
        """The SKU without a regional suffix (``U6-Lite-US`` -> ``U6-Lite``)."""
        return _REGION.sub("", self.sku)


def candidate_slugs(model: str, part_number: str = "") -> tuple[str, ...]:
    """Slugs to try: the part number first, then the UniFi model name."""
    result: list[str] = []
    for name in (part_number, model):
        slug = slugify(name)
        if slug and slug not in result:
            result.append(slug)
    return tuple(result)


def product_url(slug: str) -> str:
    # Any valid category serves every product; an invalid one redirects.
    return f"{BASE}/unifi/switching/{slug}"


def check_url(url: str) -> str:
    """A user-entered page URL, reduced to https://techspecs.ui.com/...."""
    parts = urlsplit(url.strip())
    if parts.scheme != "https" or parts.hostname != HOST:
        raise TechSpecError(f"Enter a page on {BASE}.")
    if parts.username or parts.password or parts.port not in (None, 443):
        raise TechSpecError("The URL must not contain credentials or a port.")
    if not parts.path.strip("/"):
        raise TechSpecError("Enter the URL of a product page.")
    return urlunsplit(("https", HOST, parts.path, parts.query, ""))


def lookup(model: str, part_number: str, http: httpx.Client) -> TechSpec | None:
    """The first slug candidate that resolves to its own product page."""
    for slug in candidate_slugs(model, part_number):
        text = _get(http, product_url(slug))
        spec = parse_page(text, product_url(slug))
        if spec is not None and spec.slug == slug:
            return spec
    return None


def fetch_url(url: str, http: httpx.Client) -> TechSpec:
    page = check_url(url)
    spec = parse_page(_get(http, page), page)
    if spec is None:
        raise TechSpecError("No product found on that page.")
    return spec


def parse_page(text: str, url: str) -> TechSpec | None:
    match = _NEXT_DATA.search(text)
    if match is None:
        return None
    try:
        data = json.loads(match.group(1))
    except ValueError:
        return None
    if not isinstance(data, dict) or not str(data.get("page", "")).endswith(
        "[product]"
    ):
        return None
    props = data.get("props")
    page_props = props.get("pageProps") if isinstance(props, dict) else None
    if not isinstance(page_props, dict):
        return None
    product = page_props.get("product")
    if not isinstance(product, dict) or not product.get("slug"):
        return None
    category = page_props.get("category")
    if isinstance(category, str) and re.fullmatch(r"[a-z0-9-]+", category):
        url = f"{BASE}/unifi/{category}/{product['slug']}"
    return _spec(product, url)


def _spec(product: dict, url: str) -> TechSpec:
    variants = [v for v in product.get("variants") or () if isinstance(v, dict)]
    sku = next((str(v["sku"]) for v in variants if v.get("sku")), "") or str(
        product.get("name") or ""
    )
    features = list(_features(product.get("technicalSpecification")))
    values = {label.lower(): value for _, label, value in features}

    def value(*labels: str) -> str:
        return next((values[k.lower()] for k in labels if k.lower() in values), "")

    # The axis order differs between pages, so dimensions stay text.
    size = _DIMENSIONS.search(value("Dimensions"))
    form = value("Form Factor")
    rack = _RACK.search(form)
    weight = unit = None
    if m := _WEIGHT.search(value("Weight")):
        weight, unit = float(m.group(1)), m.group(2).lower()
    power = None
    if m := _WATTS.search(value("Max. Power Consumption")):
        power = float(m.group(1))
    method = value("Power Method").lower()
    poe_type = ""
    if "802.3bt" in method or "poe++" in method:
        poe_type = ""
    elif "802.3at" in method or "poe+" in method:
        poe_type = "type2-ieee802.3at"
    elif "802.3af" in method:
        poe_type = "type1-ieee802.3af"
    return TechSpec(
        url=url,
        slug=str(product.get("slug")),
        sku=sku,
        title=str(product.get("title") or product.get("shortTitle") or sku),
        u_height=float(rack.group(1)) if rack else 0,
        rack_mount="rack" in form.lower(),
        dimensions=size.group(0) if size else "",
        weight=weight,
        weight_unit=unit or "",
        max_power_w=power,
        poe_powered="poe" in method,
        poe_type=poe_type,
        ports=_ports(features, value),
        fields=tuple((label, text) for _, label, text in features if text),
    )


def _features(spec: object) -> Iterable[tuple[str, str, str]]:
    """(group label, label, plain text) per feature, groups resolved."""
    if not isinstance(spec, dict):
        return
    for section in spec.get("sections") or ():
        if not isinstance(section, dict):
            continue
        groups: dict[str, str] = {}
        for entry in section.get("features") or ():
            if not isinstance(entry, dict) or not isinstance(
                entry.get("feature"), dict
            ):
                continue
            feature = entry["feature"]
            label = str(feature.get("label") or "").strip()
            if entry.get("__typename", "").endswith("FeatureGroup"):
                groups[str(feature.get("id"))] = label
                continue
            parent = groups.get(str(feature.get("parentId") or ""), "")
            if "value" in entry:
                text = _plain(entry.get("value"))
            elif "flag" in entry:
                text = "Yes" if str(entry.get("flag")) == "True" else "No"
            else:
                text = ""
            if entry.get("note"):
                text = f"{text} ({_plain(entry['note'])})".strip()
            yield parent, label, text


def _ports(features, value) -> tuple[SpecPorts, ...]:
    result: list[SpecPorts] = []
    for group, label, text in features:
        if group.lower() != "port layout":
            continue
        kind = _kind(label)
        count = re.match(r"\s*(\d+)", text)
        if kind and count:
            result.append(SpecPorts(int(count.group(1)), kind, _speed(label)))
    if result:
        return tuple(result)
    for text in (
        value("Networking Interface"),
        value("Ethernet Interface"),
        value("Networking Interfaces"),
    ):
        for count, speed, kind in _PORTS_IN_TEXT.findall(text):
            result.append(SpecPorts(int(count), _kind(kind), _speed(speed or kind)))
        if result:
            break
    return tuple(result)


def _kind(text: str) -> str:
    upper = text.upper()
    return next((kind for token, kind in _KINDS if token in upper), "")


def _speed(text: str) -> int:
    upper = text.upper().replace(" ", "")
    if m := re.search(r"([\d.]+)G(BE)?", upper):
        return int(float(m.group(1)) * 1000)
    if "GBE" in upper:
        return 1000
    return 0


def _plain(value: object) -> str:
    text = html.unescape(_TAG.sub("", str(value or "")))
    return re.sub(r"[ \t]+", " ", text).strip()


def _get(http: httpx.Client, url: str) -> str:
    try:
        response = http.get(url)
    except httpx.HTTPError as error:
        raise TechSpecError(f"Cannot reach {HOST}: {error}") from error
    if response.status_code in (301, 302, 303, 307, 308):
        target = response.headers.get("location", "")
        target = str(response.url.join(target))
        if urlsplit(target).hostname != HOST:
            raise TechSpecError("The page redirects to another site.")
        try:
            response = http.get(target)
        except httpx.HTTPError as error:
            raise TechSpecError(f"Cannot reach {HOST}: {error}") from error
    if response.status_code != 200:
        raise TechSpecError(f"{HOST} answered HTTP {response.status_code}.")
    return response.text
