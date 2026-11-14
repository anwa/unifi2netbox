"""Cable creates against a synthetic NetBox backend."""

import requests

from unifi2netbox.cable_execute import execute_cable_plan
from unifi2netbox.cables import build_cable_plan
from unifi2netbox.inventory import InventoryInterface, InventoryPort
from unifi2netbox.links import LLDP, UPLINK, InventoryLink
from unifi2netbox.write_execute import AmbiguousWriteError

LINKS = (
    InventoryLink("rps", 1, "udm", 5, UPLINK),
    InventoryLink("udm", 5, "rps", None, LLDP),
)


def make_plan():
    return build_cable_plan(
        LINKS,
        {"udm": "UDM", "rps": "RPS"},
        {"udm": "1", "rps": "2"},
        (InventoryPort("udm", 5, "RJ45", 1000), InventoryPort("rps", 1, "RJ45", 1000)),
        (
            InventoryInterface("15", "1", "port.5", "1000base-t"),
            InventoryInterface("21", "2", "eth0", "1000base-t"),
        ),
    )


class FakeNetBox:
    def __init__(self):
        self.rows = {
            "/api/dcim/interfaces/15/": {"id": 15, "cable": None, "link_peers": []},
            "/api/dcim/interfaces/21/": {"id": 21, "cable": None, "link_peers": []},
        }
        self.created = []
        self.fail = None
        self.apply_anyway = False

    def read_object(self, path):
        return self.rows.get(path)

    def _connect(self, cable_id, payload):
        a = payload["a_terminations"][0]["object_id"]
        b = payload["b_terminations"][0]["object_id"]
        for here, there in ((a, b), (b, a)):
            self.rows[f"/api/dcim/interfaces/{here}/"] = {
                "id": here,
                "cable": {"id": cable_id},
                "link_peers_type": "dcim.interface",
                "link_peers": [{"id": there}],
            }

    def create_object(self, path, payload):
        assert path == "/api/dcim/cables/"
        if self.fail:
            if self.apply_anyway:
                self._connect(77, payload)
            raise self.fail
        self.created.append(payload)
        self._connect(70, payload)
        return "70"

    def update_object(self, path, payload):
        raise AssertionError("cables are never updated")

    def find_ids(self, path, **filters):
        return ()


def test_cable_is_created_between_both_interfaces_and_verified():
    backend = FakeNetBox()

    (outcome,) = execute_cable_plan(make_plan(), backend, source_links=LINKS)

    assert backend.created == [
        {
            "a_terminations": [{"object_type": "dcim.interface", "object_id": 21}],
            "b_terminations": [{"object_type": "dcim.interface", "object_id": 15}],
            "status": "connected",
        }
    ]
    assert (outcome.status, outcome.verification, outcome.object_id) == (
        "success",
        "verified",
        "70",
    )


def test_existing_cable_between_them_writes_nothing():
    backend = FakeNetBox()
    execute_cable_plan(make_plan(), backend)

    (outcome,) = execute_cable_plan(make_plan(), backend)

    assert len(backend.created) == 1
    assert outcome.status == "success" and "already exists" in outcome.message


def test_other_cable_is_never_replaced():
    backend = FakeNetBox()
    backend.rows["/api/dcim/interfaces/15/"] = {"id": 15, "cable": {"id": 5}}

    (outcome,) = execute_cable_plan(make_plan(), backend)

    assert backend.created == []
    assert outcome.status == "skipped" and "never replaced" in outcome.message


def test_dry_run_and_vanished_evidence_write_nothing():
    backend = FakeNetBox()

    (dry,) = execute_cable_plan(make_plan(), backend, dry_run=True)
    (gone,) = execute_cable_plan(
        make_plan(), backend, source_links=(InventoryLink("rps", 1, "udm", 4, UPLINK),)
    )
    (offline,) = execute_cable_plan(make_plan(), backend, source_error="timeout")

    assert backend.created == []
    assert dry.message == "Dry-run mode: not created."
    assert "no longer reports" in gone.message
    assert "could not be re-read" in offline.message


def test_interrupted_create_is_looked_up_not_retried():
    applied = FakeNetBox()
    applied.fail = AmbiguousWriteError("timeout")
    applied.apply_anyway = True
    lost = FakeNetBox()
    lost.fail = AmbiguousWriteError("timeout")

    (found,) = execute_cable_plan(make_plan(), applied)
    (missing,) = execute_cable_plan(make_plan(), lost)

    assert (found.status, found.object_id, found.verification) == (
        "success",
        "77",
        "verified",
    )
    assert "interrupted" in found.message
    assert missing.status == "failed" and "shows no cable" in missing.message


def test_transport_failure_is_reported():
    backend = FakeNetBox()
    backend.fail = requests.exceptions.ConnectionError("down")

    (outcome,) = execute_cable_plan(make_plan(), backend)

    assert outcome.status == "failed"
