"""Locate the user manual and build its table of contents (Qt-free).

The manual is a folder of Markdown files (``manual/`` in the repository, next
to the executable's ``_internal`` data in packaged builds). Each folder has an
``index.md``; the first ``# `` heading of a file is its title. Entries sort by
file or folder name, so numeric prefixes (``01-...``) set the order. The root
``index.md`` is the overview shown first.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

INDEX = "index.md"


@dataclass(frozen=True)
class ManualEntry:
    title: str
    path: Path
    children: tuple[ManualEntry, ...] = ()


def manual_root() -> Path | None:
    """The manual folder of a source checkout or a packaged build."""
    candidates = []
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        candidates.append(Path(bundle) / "manual")
    candidates.append(Path(__file__).resolve().parents[2] / "manual")
    for candidate in candidates:
        if (candidate / INDEX).is_file():
            return candidate
    return None


def title_of(path: Path) -> str:
    """The first level-1 heading, else a title made from the file name."""
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("# "):
                    return line[2:].strip()
    except OSError:
        pass
    stem = path.parent.name if path.name == INDEX else path.stem
    return _plain(stem)


def build_toc(root: Path) -> ManualEntry:
    """The overview with the folders and pages below it."""
    return ManualEntry(title_of(root / INDEX), root / INDEX, _children(root))


def _children(folder: Path) -> tuple[ManualEntry, ...]:
    entries = []
    for item in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
        if item.is_dir() and (item / INDEX).is_file():
            entries.append(
                ManualEntry(title_of(item / INDEX), item / INDEX, _children(item))
            )
        elif item.is_file() and item.suffix == ".md" and item.name != INDEX:
            entries.append(ManualEntry(title_of(item), item))
    return tuple(entries)


def _plain(stem: str) -> str:
    head, _, tail = stem.partition("-")
    text = tail if head.isdigit() and tail else stem
    return text.replace("-", " ").strip().capitalize()
