"""Local SQLite history of write runs.

Each run stores when it ran, whether it was a dry run and one outcome per
device. The file lives next to the configuration, outside the repository; it
holds device names and result messages, never credentials.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

JOURNAL_SCHEMA_VERSION = 1
JOURNAL_FILENAME = "write-journal.sqlite3"


class JournalStoreError(ValueError):
    pass


@dataclass(frozen=True)
class StoredOutcome:
    device_key: str
    label: str
    operation_type: str
    status: str
    message: str
    netbox_object_id: str = ""
    verification: str = ""
    verification_detail: str = ""


@dataclass(frozen=True)
class StoredRun:
    run_id: str
    started_at: str
    finished_at: str
    dry_run: bool
    outcomes: tuple[StoredOutcome, ...]

    def count(self, status: str) -> int:
        return sum(outcome.status == status for outcome in self.outcomes)

    def verified(self) -> int:
        return sum(outcome.verification == "verified" for outcome in self.outcomes)

    def summary(self) -> str:
        parts = [
            f"{self.count('success')} success",
            f"{self.count('failed')} failed",
            f"{self.count('skipped')} skipped",
        ]
        if self.count("success"):
            parts.append(f"{self.verified()} verified")
        return ", ".join(parts)


class JournalStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS metadata "
                "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS write_runs (
                    run_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    dry_run INTEGER NOT NULL,
                    outcomes_json TEXT NOT NULL
                )
                """
            )
            row = connection.execute(
                "SELECT value FROM metadata WHERE key = 'schema_version'"
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO metadata(key, value) VALUES('schema_version', ?)",
                    (str(JOURNAL_SCHEMA_VERSION),),
                )
            elif row[0] != str(JOURNAL_SCHEMA_VERSION):
                raise JournalStoreError("Unsupported write journal schema version.")

    def save(self, run: StoredRun) -> None:
        self.initialize()
        encoded = json.dumps([asdict(item) for item in run.outcomes], sort_keys=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO write_runs(run_id, started_at, finished_at, dry_run,
                                       outcomes_json)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    finished_at = excluded.finished_at,
                    outcomes_json = excluded.outcomes_json
                """,
                (
                    run.run_id,
                    run.started_at,
                    run.finished_at,
                    int(run.dry_run),
                    encoded,
                ),
            )

    def recent(self, limit: int = 50) -> tuple[StoredRun, ...]:
        if not self.path.exists():
            return ()
        self.initialize()
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                """
                SELECT run_id, started_at, finished_at, dry_run, outcomes_json
                FROM write_runs ORDER BY started_at DESC, rowid DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        try:
            return tuple(
                StoredRun(
                    run_id=str(row[0]),
                    started_at=str(row[1]),
                    finished_at=str(row[2]),
                    dry_run=bool(row[3]),
                    outcomes=tuple(
                        StoredOutcome(**item) for item in json.loads(row[4])
                    ),
                )
                for row in rows
            )
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise JournalStoreError("Stored write journal data is invalid.") from error
