"""Locate the user manual and build its table of contents (Qt-free).

The manual is a folder of Markdown files (``manual/`` in the repository, next
to the executable's ``_internal`` data in packaged builds). Each folder has an
``index.md``; the first ``# `` heading of a file is its title. Entries sort by
file or folder name, so numeric prefixes (``01-...``) set the order. The root
``index.md`` is the overview shown first.
"""

from __future__ import annotations

import re
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


# -- search ------------------------------------------------------------------------

_MARKUP = (
    (re.compile(r"!\[[^\]]*\]\([^)]*\)"), " "),  # images
    (re.compile(r"\[([^\]]*)\]\([^)]*\)"), r"\1"),  # links keep their text
    # real html tags only; placeholders such as <host> stay
    (
        re.compile(r"</?(?:a|b|br|code|div|em|i|img|kbd|p|span|strong|sub|sup)[^>]*>"),
        " ",
    ),
    (re.compile(r"^\s*>+", re.MULTILINE), " "),  # quotes
    (re.compile(r"[`*_#|]+"), " "),  # code, emphasis, headings, tables
    (re.compile(r"^-{3,}$", re.MULTILINE), " "),
)


@dataclass(frozen=True)
class SearchHit:
    path: Path
    title: str
    chapter: str
    snippet: str
    score: int


def plain_text(markdown: str) -> str:
    """Readable text of a Markdown page (for searching and snippets)."""
    text = markdown
    for pattern, replacement in _MARKUP:
        text = pattern.sub(replacement, text)
    return re.sub(r"\s+", " ", text).strip()


def search_terms(query: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(t.lower() for t in query.split() if t.strip()))


def search_manual(root: Path, query: str, limit: int = 50) -> list[SearchHit]:
    """Pages that contain every word of ``query`` (case-insensitive), best
    first: words in the title count most, then in headings, then in text."""
    terms = search_terms(query)
    if not terms:
        return []
    hits = []
    for path, title, chapter, headings, text in _pages(root):
        lower = text.lower()
        if not all(term in lower or term in title.lower() for term in terms):
            continue
        score = 0
        for term in terms:
            score += 10 * title.lower().count(term)
            score += 3 * headings.lower().count(term)
            score += lower.count(term)
        hits.append(SearchHit(path, title, chapter, _snippet(text, terms), score))
    hits.sort(key=lambda h: (-h.score, h.chapter, h.title))
    return hits[:limit]


def _pages(root: Path):
    """(path, title, chapter, headings, text) of every page, cached per file."""
    result = []
    for path in sorted(root.rglob("*.md")):
        try:
            stamp = path.stat().st_mtime_ns
        except OSError:
            continue
        cached = _CACHE.get(path)
        if cached is None or cached[0] != stamp:
            markdown = path.read_text(encoding="utf-8")
            headings = " ".join(
                line.lstrip("#").strip()
                for line in markdown.splitlines()
                if line.startswith("#")
            )
            chapter = (
                title_of(path.parent / INDEX)
                if path.name != INDEX and path.parent != root
                else ""
            )
            cached = (stamp, title_of(path), chapter, headings, plain_text(markdown))
            _CACHE[path] = cached
        result.append((path, *cached[1:]))
    return result


_CACHE: dict[Path, tuple] = {}


def _snippet(text: str, terms: tuple[str, ...], width: int = 70) -> str:
    lower = text.lower()
    phrase = lower.find(" ".join(terms))  # the words together first
    positions = (
        [phrase]
        if phrase >= 0
        else [lower.find(t) for t in terms if lower.find(t) >= 0]
    )
    if not positions:
        return text[: 2 * width] + ("..." if len(text) > 2 * width else "")
    start = max(0, min(positions) - width)
    end = min(len(text), min(positions) + width)
    return (
        ("..." if start else "")
        + text[start:end].strip()
        + ("..." if end < len(text) else "")
    )
