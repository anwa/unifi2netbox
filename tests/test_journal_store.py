import sqlite3

import pytest

from unifi2netbox.journal_store import (
    JournalStore,
    JournalStoreError,
    StoredOutcome,
    StoredRun,
)


def run(run_id, started_at, *, dry_run=False, statuses=("success",)):
    return StoredRun(
        run_id=run_id,
        started_at=started_at,
        finished_at=started_at,
        dry_run=dry_run,
        outcomes=tuple(
            StoredOutcome(
                device_key=f"create:unifi_network:{index}",
                label=f"ap-{index}",
                operation_type="create_device",
                status=status,
                message="Created device in NetBox.",
                netbox_object_id=str(100 + index),
                verification="verified" if status == "success" else "",
            )
            for index, status in enumerate(statuses)
        ),
    )


def test_saved_runs_come_back_newest_first(tmp_path):
    store = JournalStore(tmp_path / "write-journal.sqlite3")
    store.save(run("r1", "2026-11-14T10:00:00+01:00", dry_run=True))
    store.save(run("r2", "2026-11-14T11:00:00+01:00", statuses=("success", "failed")))

    runs = store.recent()

    assert [item.run_id for item in runs] == ["r2", "r1"]
    assert runs[0].summary() == "1 success, 1 failed, 0 skipped, 1 verified"
    assert runs[1].dry_run is True
    assert runs[0].outcomes[0].label == "ap-0"
    assert store.recent(limit=1)[0].run_id == "r2"


def test_missing_history_file_is_empty_and_not_created(tmp_path):
    path = tmp_path / "write-journal.sqlite3"

    assert JournalStore(path).recent() == ()
    assert not path.exists()


def test_unknown_schema_version_is_rejected(tmp_path):
    path = tmp_path / "write-journal.sqlite3"
    store = JournalStore(path)
    store.save(run("r1", "2026-11-14T10:00:00+01:00"))
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE metadata SET value = '99'")

    with pytest.raises(JournalStoreError):
        store.recent()


def test_corrupt_outcomes_are_reported(tmp_path):
    path = tmp_path / "write-journal.sqlite3"
    store = JournalStore(path)
    store.save(run("r1", "2026-11-14T10:00:00+01:00"))
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE write_runs SET outcomes_json = 'not json'")

    with pytest.raises(JournalStoreError):
        store.recent()
