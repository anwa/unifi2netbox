"""Refresh the bundled devicetype-library JSON schema.

Usage (repository root, project .venv):

    python tools/update_devicetype_schema.py [git-ref]

Downloads ``schema/*.json`` of netbox-community/devicetype-library (CC0) at
``git-ref`` (default ``master``) into
``src/unifi2netbox/resources/devicetype-schema/`` and records the ref and date
in ``SOURCE.txt``. Review the diff before committing.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

REPO = "netbox-community/devicetype-library"
FILES = (
    "components.json",
    "devicetype.json",
    "generated_schema.json",
    "moduletype.json",
    "racktype.json",
    "reusable.json",
)
TARGET = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "unifi2netbox"
    / "resources"
    / "devicetype-schema"
)


def main() -> None:
    ref = sys.argv[1] if len(sys.argv) > 1 else "master"
    TARGET.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=20, follow_redirects=False) as client:
        for name in FILES:
            url = f"https://raw.githubusercontent.com/{REPO}/{ref}/schema/{name}"
            response = client.get(url)
            response.raise_for_status()
            data = json.loads(response.text)
            (TARGET / name).write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            print("wrote", name)
    (TARGET / "SOURCE.txt").write_text(
        f"https://github.com/{REPO}/tree/{ref}/schema\n"
        f"Retrieved {datetime.now(UTC).date().isoformat()}; license CC0-1.0.\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    main()
