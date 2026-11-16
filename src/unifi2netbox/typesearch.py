"""Search device types across NetBox, the local folder and the library.

Candidates carry what the picker shows and filters on. NetBox types and
library entries whose file was not downloaded yet have no component details;
component filters then cannot decide, so those candidates are left out and
counted as ``unchecked``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from unifi2netbox.devicetypes import TypeFile, load_yaml
from unifi2netbox.inventory import InventoryDeviceType
from unifi2netbox.library import LibraryCache, LibraryEntry, LibraryIndex
from unifi2netbox.matching import model_keys

NETBOX = "netbox"
LOCAL = "local"
LIBRARY = "library"
SOURCES = (NETBOX, LOCAL, LIBRARY)
SOURCE_LABELS = {NETBOX: "NetBox", LOCAL: "Local", LIBRARY: "Library"}

# Filter fields offered by the picker, in display order.
FILTER_FIELDS = (
    ("search", "Search"),
    ("manufacturer", "Manufacturer"),
    ("source", "Source"),
    ("part_number", "Part number"),
    ("u_height", "Rack height (U)"),
    ("is_full_depth", "Full depth"),
    ("airflow", "Airflow"),
    ("interfaces", "Has interfaces"),
    ("poe", "Has PoE ports"),
    ("sfp", "Has SFP/SFP+ ports"),
    ("console", "Has console ports"),
    ("power", "Has power ports"),
    ("module_bays", "Has module bays"),
    ("weight", "Weight"),
)
COMPONENT_FILTERS = frozenset(
    {"interfaces", "poe", "sfp", "console", "power", "module_bays"}
)
DETAIL_FILTERS = COMPONENT_FILTERS | {"u_height", "is_full_depth", "airflow", "weight"}


@dataclass(frozen=True)
class TypeCandidate:
    source: str
    manufacturer: str
    model: str
    part_number: str = ""
    netbox_id: str = ""
    path: str = ""
    entry: LibraryEntry | None = None
    detailed: bool = False
    u_height: float | None = None
    is_full_depth: bool | None = None
    airflow: str = ""
    weight: float | None = None
    weight_unit: str = ""
    counts: Mapping[str, int] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.source}:{self.netbox_id or self.path}"

    @property
    def title(self) -> str:
        return self.model or self.part_number or self.path

    def keys(self) -> frozenset[str]:
        names = (self.model, self.part_number)
        if self.entry is not None:
            names += (self.entry.name,)
        return frozenset().union(*(model_keys(n) for n in names if n))


@dataclass(frozen=True)
class TypeFilter:
    field: str
    value: str
    operator: str = "is"  # is, is not, contains


@dataclass(frozen=True)
class SearchResult:
    candidates: tuple[TypeCandidate, ...]
    unchecked: int = 0


# -- candidates ------------------------------------------------------------------


def netbox_candidates(types: Iterable[InventoryDeviceType]) -> list[TypeCandidate]:
    return [
        TypeCandidate(
            NETBOX, t.manufacturer, t.model, t.part_number, netbox_id=t.source_id
        )
        for t in types
    ]


def from_document(
    doc: Mapping, source: str, path: str = "", entry: LibraryEntry | None = None
) -> TypeCandidate:
    """A detailed candidate from a parsed definition."""
    interfaces = [i for i in doc.get("interfaces") or () if isinstance(i, Mapping)]

    def count(section: str) -> int:
        return len([i for i in doc.get(section) or () if isinstance(i, Mapping)])

    counts = {
        "interfaces": len(interfaces),
        "poe": sum(1 for i in interfaces if i.get("poe_mode") in ("pse", "pd")),
        "sfp": sum(1 for i in interfaces if "sfp" in str(i.get("type", ""))),
        "console": count("console-ports"),
        "power": count("power-ports"),
        "module_bays": count("module-bays"),
    }
    return TypeCandidate(
        source,
        str(doc.get("manufacturer") or (entry.manufacturer if entry else "")),
        str(doc.get("model") or ""),
        str(doc.get("part_number") or ""),
        path=path,
        entry=entry,
        detailed=True,
        u_height=_number(doc.get("u_height")),
        is_full_depth=doc.get("is_full_depth")
        if isinstance(doc.get("is_full_depth"), bool)
        else None,
        airflow=str(doc.get("airflow") or ""),
        weight=_number(doc.get("weight")),
        weight_unit=str(doc.get("weight_unit") or ""),
        counts=counts,
    )


def local_candidates(files: Iterable[TypeFile], read) -> list[TypeCandidate]:
    """Parsed local files; unreadable files become plain entries."""
    result = []
    for item in files:
        try:
            doc = read(item.path)
        except Exception:  # noqa: BLE001 - a broken file must not hide others
            result.append(
                TypeCandidate(LOCAL, item.manufacturer, item.name, path=str(item.path))
            )
            continue
        result.append(from_document(doc, LOCAL, path=str(item.path)))
    return result


def library_candidates(
    index: LibraryIndex | None, cache: LibraryCache | None = None
) -> list[TypeCandidate]:
    if index is None:
        return []
    result = []
    for entry in index.entries:
        text = cache.cached_text(entry) if cache is not None else None
        if text is not None:
            try:
                result.append(
                    from_document(load_yaml(text), LIBRARY, entry.path, entry)
                )
                continue
            except ValueError:
                pass
        result.append(
            TypeCandidate(
                LIBRARY,
                entry.manufacturer,
                "",
                entry.name,
                path=entry.path,
                entry=entry,
            )
        )
    return result


# -- search ----------------------------------------------------------------------


def search(
    candidates: Sequence[TypeCandidate],
    filters: Iterable[TypeFilter] = (),
    *,
    hint: str = "",
    hint_manufacturer: str = "",
    limit: int = 300,
) -> SearchResult:
    """Filter, then rank: matches for ``hint`` (the UniFi model) first."""
    filters = tuple(f for f in filters if f.value.strip())
    unchecked = 0
    kept: list[TypeCandidate] = []
    for candidate in candidates:
        decision = _matches(candidate, filters)
        if decision is None:
            unchecked += 1
        elif decision:
            kept.append(candidate)
    hint_keys = model_keys(hint) if hint else frozenset()
    query = next((f.value for f in filters if f.field == "search"), "")
    query_keys = model_keys(query) if query else frozenset()

    def rank(candidate: TypeCandidate) -> tuple:
        keys = candidate.keys()
        exact = bool(hint_keys & keys) or bool(query_keys & keys)
        same_maker = bool(hint_manufacturer) and (
            candidate.manufacturer.lower() == hint_manufacturer.lower()
        )
        return (
            not exact,
            not same_maker,
            SOURCES.index(candidate.source),
            candidate.manufacturer.lower(),
            candidate.title.lower(),
        )

    kept.sort(key=rank)
    return SearchResult(tuple(kept[:limit]), unchecked)


def is_suggested(candidate: TypeCandidate, hint: str) -> bool:
    return bool(hint) and bool(model_keys(hint) & candidate.keys())


def _matches(candidate: TypeCandidate, filters: tuple[TypeFilter, ...]) -> bool | None:
    for item in filters:
        value = item.value.strip()
        if item.field == "search":
            needle = value.lower()
            haystack = " ".join(
                (candidate.manufacturer, candidate.model, candidate.part_number)
                + ((candidate.entry.name,) if candidate.entry else ())
            ).lower()
            keys = model_keys(value)
            if needle not in haystack and not any(
                k in key for k in keys for key in candidate.keys()
            ):
                return False
        elif item.field == "manufacturer":
            same = candidate.manufacturer.lower() == value.lower()
            if same == (item.operator == "is not"):
                return False
        elif item.field == "source":
            same = candidate.source == value
            if same == (item.operator == "is not"):
                return False
        elif item.field == "part_number":
            if value.lower() not in candidate.part_number.lower():
                return False
        elif item.field in DETAIL_FILTERS:
            if not candidate.detailed:
                return None
            if item.field in COMPONENT_FILTERS:
                has = candidate.counts.get(item.field, 0) > 0
                if has != (value == "yes"):
                    return False
            elif item.field == "u_height":
                number = _number(value)
                if number is None or candidate.u_height != number:
                    return False
            elif item.field == "is_full_depth":
                if candidate.is_full_depth != (value == "yes"):
                    return False
            elif item.field == "airflow":
                if candidate.airflow != value:
                    return False
            elif item.field == "weight":
                number = _number(value)
                if (
                    number is None
                    or candidate.weight is None
                    or (candidate.weight > number)
                ):
                    return False
    return True


def _number(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except TypeError, ValueError:
        return None
