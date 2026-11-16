"""Read-only access to netbox-community/devicetype-library on GitHub.

The index lists every file under ``device-types/`` of the configured
repository and branch (two GitHub API requests: the branch's root tree, then
the ``device-types`` subtree recursively). It is cached as JSON next to the
configuration. Files are downloaded on demand from raw.githubusercontent.com
and cached by their Git blob SHA, so a changed file is fetched again after the
index is refreshed. Only the repository, branch and file paths are sent;
nothing about the user's network.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from urllib.parse import quote

import httpx

from unifi2netbox.config import DeviceTypesConfig

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
ROOT = "device-types"
INDEX_FILE = "library-index.json"
TIMEOUT = 20.0
_SHA = re.compile(r"[0-9a-f]{40}")


class LibraryError(RuntimeError):
    pass


@dataclass(frozen=True)
class LibraryEntry:
    manufacturer: str
    name: str  # file name without suffix: the model or part number
    path: str  # relative to device-types/
    sha: str

    @property
    def repository_path(self) -> str:
        return f"{ROOT}/{self.path}"


@dataclass(frozen=True)
class LibraryIndex:
    repository: str
    branch: str
    retrieved_at: str
    entries: tuple[LibraryEntry, ...] = ()

    def manufacturers(self) -> tuple[str, ...]:
        return tuple(sorted({e.manufacturer for e in self.entries}, key=str.lower))


def user_agent() -> str:
    try:
        return f"unifi2netbox/{version('unifi2netbox')}"
    except PackageNotFoundError:
        return "unifi2netbox"


def client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """HTTPS client for public sources; redirects are not followed."""
    return httpx.Client(
        timeout=TIMEOUT,
        follow_redirects=False,
        headers={"User-Agent": user_agent()},
        transport=transport,
    )


class LibraryCache:
    """Index and downloaded files under ``folder``."""

    def __init__(self, folder: Path) -> None:
        self.folder = Path(folder)

    @property
    def index_path(self) -> Path:
        return self.folder / INDEX_FILE

    def load_index(self, config: DeviceTypesConfig) -> LibraryIndex | None:
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except OSError, ValueError:
            return None
        if (
            not isinstance(data, dict)
            or data.get("repository") != config.library_repository
            or data.get("branch") != config.library_branch
        ):
            return None
        entries = []
        for row in data.get("entries", ()):
            if isinstance(row, dict) and _SHA.fullmatch(str(row.get("sha", ""))):
                entries.append(
                    LibraryEntry(
                        str(row.get("manufacturer", "")),
                        str(row.get("name", "")),
                        str(row.get("path", "")),
                        str(row["sha"]),
                    )
                )
        return LibraryIndex(
            str(data["repository"]),
            str(data["branch"]),
            str(data.get("retrieved_at", "")),
            tuple(entries),
        )

    def save_index(self, index: LibraryIndex) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        data = {
            "repository": index.repository,
            "branch": index.branch,
            "retrieved_at": index.retrieved_at,
            "entries": [asdict(entry) for entry in index.entries],
        }
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8", newline="\n")
        tmp.replace(self.index_path)

    def file_path(self, entry: LibraryEntry) -> Path:
        return self.folder / "files" / f"{entry.sha}.yaml"

    def cached_text(self, entry: LibraryEntry) -> str | None:
        try:
            return self.file_path(entry).read_text(encoding="utf-8")
        except OSError:
            return None

    def store_text(self, entry: LibraryEntry, text: str) -> None:
        path = self.file_path(entry)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")


def fetch_index(config: DeviceTypesConfig, http: httpx.Client) -> LibraryIndex:
    """Download the file list of ``device-types/`` (raises ``LibraryError``)."""
    repo = config.library_repository
    root = _json(
        http,
        f"{API}/repos/{repo}/git/trees/{quote(config.library_branch, safe='')}",
    )
    sha = next(
        (
            item.get("sha")
            for item in root.get("tree", ())
            if isinstance(item, dict)
            and item.get("path") == ROOT
            and item.get("type") == "tree"
        ),
        None,
    )
    if not isinstance(sha, str) or not _SHA.fullmatch(sha):
        raise LibraryError(f"{repo} has no {ROOT} folder on {config.library_branch}.")
    tree = _json(http, f"{API}/repos/{repo}/git/trees/{sha}?recursive=1")
    if tree.get("truncated"):
        raise LibraryError("GitHub returned an incomplete file list; try again later.")
    entries = []
    for item in tree.get("tree", ()):
        if not isinstance(item, dict) or item.get("type") != "blob":
            continue
        path = str(item.get("path", ""))
        parts = path.split("/")
        blob = str(item.get("sha", ""))
        if (
            len(parts) == 2
            and parts[1].endswith((".yaml", ".yml"))
            and _SHA.fullmatch(blob)
        ):
            entries.append(
                LibraryEntry(parts[0], parts[1].rsplit(".", 1)[0], path, blob)
            )
    entries.sort(key=lambda e: (e.manufacturer.lower(), e.name.lower()))
    return LibraryIndex(
        repo,
        config.library_branch,
        datetime.now(UTC).isoformat(timespec="seconds"),
        tuple(entries),
    )


def fetch_text(
    config: DeviceTypesConfig,
    entry: LibraryEntry,
    http: httpx.Client,
    cache: LibraryCache | None = None,
) -> str:
    """The file's YAML text, from the cache when its blob SHA is known."""
    if cache is not None and (text := cache.cached_text(entry)) is not None:
        return text
    url = (
        f"{RAW}/{config.library_repository}/{quote(config.library_branch, safe='')}/"
        + "/".join(quote(part, safe="") for part in entry.repository_path.split("/"))
    )
    response = _get(http, url)
    text = response.text
    if cache is not None:
        cache.store_text(entry, text)
    return text


def find(index: LibraryIndex, names: Iterable[str]) -> tuple[LibraryEntry, ...]:
    """Entries whose file name equals one of ``names`` (case-insensitive)."""
    wanted = {name.lower() for name in names if name}
    return tuple(e for e in index.entries if e.name.lower() in wanted)


def _json(http: httpx.Client, url: str) -> dict:
    response = _get(http, url, accept="application/vnd.github+json")
    try:
        data = response.json()
    except ValueError as error:
        raise LibraryError("GitHub returned an invalid answer.") from error
    if not isinstance(data, dict):
        raise LibraryError("GitHub returned an invalid answer.")
    return data


def _get(http: httpx.Client, url: str, accept: str | None = None) -> httpx.Response:
    if not url.startswith("https://"):
        raise LibraryError("Only HTTPS sources are allowed.")
    try:
        response = http.get(url, headers={"Accept": accept} if accept else None)
    except httpx.HTTPError as error:
        raise LibraryError(f"Cannot reach GitHub: {error}") from error
    if (
        response.status_code == 403
        and response.headers.get("x-ratelimit-remaining") == "0"
    ):
        raise LibraryError("GitHub rate limit reached; try again in an hour.")
    if response.status_code == 404:
        raise LibraryError("Not found on GitHub; check repository and branch.")
    if response.status_code != 200:
        raise LibraryError(f"GitHub answered HTTP {response.status_code}.")
    return response


CACHE_FOLDER = "devicetype-library-cache"


def cache_folder(config_path: Path) -> Path:
    """Where the index and downloaded files are kept (next to the config)."""
    return config_path.parent / CACHE_FOLDER


def refresh_index(config: DeviceTypesConfig, config_path: Path) -> LibraryIndex:
    """Download and cache the index (blocking; run it off the GUI thread)."""
    with client() as http:
        index = fetch_index(config, http)
    LibraryCache(cache_folder(config_path)).save_index(index)
    return index
