import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import httpx

from ptp_vast_mcp import cli
from ptp_vast_mcp.api import ORIGIN, VastAPI, VastError
from ptp_vast_mcp.lifecycle import Ledger, adopt, connection, destroy, prepare_rental, reconcile, rent, status, stop
from ptp_vast_mcp.planner import Limits, discover


def offer(**extra):
    return {"id": 123, "machine_id": 42, "gpu_name": "RTX 3090", "gpu_ram": 24576,
            "dph_total": 0.31, "disk_space": 64, "duration": 18000, "num_gpus": 1,
            "gpu_arch": "nvidia", "verification": "verified", "rentable": True,
            "rented": False, "direct_port_count": 2, **extra}


class Fake:
    def __init__(self):
        self.calls = []
        self.value = offer()
        self.row = None
        self.create_timeout = False
        self.destroy_ack = True
        self.destroy_delete = True
        self.list_pages = None

    def route(self, req):
        self.calls.append((req.method, req.url.path))
        assert req.url.host == "console.vast.ai"
        assert req.headers["Authorization"] == "Bearer fake-test-key"
        data = json.loads(req.content) if req.content else {}
        path = req.url.path
        if path == "/api/v0/bundles":
            assert req.method == "POST" and "api_key" not in str(data)
            assert data["type"] == "on-demand" and data["allocated_storage"] == 24
            if "id" in data:
                assert data["id"] == {"eq": 123}
            return httpx.Response(200, json={"offers": self.value})
        if path == "/api/v0/asks/123":
            assert req.method == "PUT"
            assert data["disk"] == 24 and data["runtype"] == "ssh_direct"
            assert data["cancel_unavail"] is True and "price" not in data and "env" not in data
            self.row = {"id": 88, "label": data["label"], "actual_status": "running", "ssh_host": "ssh123.vast.ai",
                        "ssh_port": 2022, "extra_env": "FAKE_SECRET", "dph_total": 0.31}
            if self.create_timeout:
                raise httpx.ReadTimeout("fake timeout, already committed", request=req)
            return httpx.Response(200, json={"success": True, "new_contract": 88})
        if path == "/api/v1/instances":
            assert req.method == "GET"
            if self.list_pages is not None:
                return httpx.Response(200, json=self.list_pages[req.url.params.get("after_token")])
            rows = [self.row] if self.row else []
            return httpx.Response(200, json={"success": True, "instances": rows, "total_instances": len(rows), "next_token": None})
        assert path == "/api/v0/instances/88"
        if req.method == "GET":
            return httpx.Response(200, json={"instances": self.row}) if self.row else httpx.Response(404)
        if req.method == "PUT":
            assert data == {"state": "stopped"}
            self.row["actual_status"] = "exited"
            return httpx.Response(200, json={"success": True})
        assert req.method == "DELETE"
        if self.destroy_delete:
            self.row = None
        return httpx.Response(200, json={"success": self.destroy_ack})


class TestCore(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.TemporaryDirectory()
        self.addCleanup(self.ws.cleanup)
        self.ledger = Ledger(Path(self.ws.name) / "leases.sqlite3")
        self.fake = Fake()
        self.api = VastAPI("fake-test-key", writable=True, transport=httpx.MockTransport(self.fake.route))
        self.addCleanup(self.api._client.close)
        self.limits = Limits()

    def ready(self):
        q, d = prepare_rental(self.api, self.limits, 123)
        return rent(self.api, self.ledger, self.limits, q, d)

    def test_rent_run_connection_stop_destroy_confirmed(self):
        record = self.ready()
        self.assertRegex(record["label"], "^ptp-vast-[0-9a-f]{32}$")
        self.assertTrue(self.ledger.open())
        view = status(self.api, record)
        self.assertEqual(view["live_rate_check"], "AT_OR_BELOW_QUOTE")
        self.assertNotIn("FAKE_SECRET", str(view))
        argv = connection(self.api, record)["gpu_probe_argv_for_owner"]
        self.assertEqual(argv[-2:], ["nvidia-smi", "-L"])
        stopped = stop(self.api, self.ledger, record)
        self.assertEqual(stopped["state"], "MANAGED")
        self.assertIn("storage may still bill", stopped["stop_observation"])
        closed = destroy(self.api, self.ledger, stopped)
        self.assertEqual(closed["state"], "CLOSED")
        self.assertIsNone(self.ledger.open())
        self.assertEqual(self.fake.calls.count(("PUT", "/api/v0/asks/123")), 1)

    def test_quote_change_within_cap_blocks_exact_purchase(self):
        q, d = prepare_rental(self.api, self.limits, 123)
        self.fake.value["dph_total"] = 0.32
        with self.assertRaisesRegex(VastError, "changed"):
            rent(self.api, self.ledger, self.limits, q, d)
        self.assertIsNone(self.ledger.open())
        self.assertNotIn(("PUT", "/api/v0/asks/123"), self.fake.calls)

    def test_expired_and_over_plan_total_block(self):
        q, d = prepare_rental(self.api, self.limits, 123)
        with self.assertRaisesRegex(VastError, "expired"):
            rent(self.api, self.ledger, self.limits, q, time.monotonic() - 0.1)
        self.assertEqual(discover(self.api, Limits(max_estimated_usd="0.10")), [])

    def test_offer_local_validation_rejects_invalid_even_if_provider_ignores_filters(self):
        self.fake.value = [offer(gpu_arch="amd"), offer(id=2, dph_total=0.76), offer(id=3, direct_port_count=0),
                           offer(id=4, gpu_ram=8000), offer(id=5, rented=True), offer(id=6, dph_total="NaN")]
        self.assertEqual(discover(self.api, self.limits), [])

    def test_timeout_after_remote_commit_and_next_page_recovery(self):
        self.fake.create_timeout = True
        with self.assertRaisesRegex(VastError, "unresolved"):
            self.ready()
        pending = self.ledger.open()
        self.assertEqual(pending["state"], "CREATE_PENDING")
        with self.assertRaisesRegex(VastError, "active or unresolved"):
            self.ready()
        self.fake.list_pages = {None: {"success": True, "instances": [{"id": 99, "label": "other"}],
                                      "total_instances": 2, "next_token": "safe-next"},
                                "safe-next": {"success": True, "instances": [self.fake.row],
                                              "total_instances": 2, "next_token": None}}
        lease = reconcile(self.api, self.ledger, pending)
        self.assertEqual(lease["instance_id"], 88)
        self.assertEqual(self.fake.calls.count(("PUT", "/api/v0/asks/123")), 1)

    def test_wrong_label_refuses_destroy_and_adopt(self):
        record = self.ready()
        self.fake.row["label"] = "wrong-owner"
        with self.assertRaisesRegex(VastError, "label does not match"):
            destroy(self.api, self.ledger, record)
        self.assertNotIn(("DELETE", "/api/v0/instances/88"), self.fake.calls)

    def test_ambiguous_destroy_preserves_slot_despite_404(self):
        record = self.ready()
        self.fake.destroy_ack = False
        with self.assertRaisesRegex(VastError, "unresolved"):
            destroy(self.api, self.ledger, record)
        pending = self.ledger.open()
        self.assertEqual(pending["state"], "DESTROY_PENDING")
        with self.assertRaisesRegex(VastError, "404 without positive"):
            reconcile(self.api, self.ledger, pending)
        with self.assertRaisesRegex(VastError, "active or unresolved"):
            self.ready()
        self.assertEqual(self.fake.calls.count(("DELETE", "/api/v0/instances/88")), 1)

    def test_destroy_ack_and_404_not_enough_when_list_is_incomplete(self):
        record = self.ready()
        self.fake.list_pages = {None: {"success": True, "instances": [], "total_instances": 2, "next_token": None}}
        with self.assertRaisesRegex(VastError, "listing total"):
            destroy(self.api, self.ledger, record)
        self.assertEqual(self.ledger.open()["state"], "DESTROY_ACKNOWLEDGED")

    def test_running_not_gpu_proof_and_price_or_host_refuses_connection(self):
        record = self.ready()
        self.fake.row["dph_total"] = 0.32
        with self.assertRaisesRegex(VastError, "higher"):
            connection(self.api, record)
        self.fake.row["dph_total"] = 0.31
        self.fake.row["ssh_host"] = "127.0.0.1"
        with self.assertRaisesRegex(VastError, "globally routable"):
            connection(self.api, record)

    def test_noninteractive_rent_never_reads_lifecycle_key(self):
        path = Path(self.ws.name) / "cli.sqlite"
        with patch.object(cli, "state_path", return_value=path), patch.object(cli, "get_key") as key, patch("sys.stdin", io.StringIO()):
            with self.assertRaisesRegex(VastError, "human terminal"):
                cli.execute(cli.parser().parse_args(["rent", "123"]))
            key.assert_not_called()

    def test_read_client_never_sends_create(self):
        with VastAPI("fake-test-key", transport=httpx.MockTransport(self.fake.route)) as read:
            with self.assertRaisesRegex(VastError, "Mutation disabled"):
                read.create(123, 24, "fake")
        self.assertEqual(self.fake.calls, [])

    def test_redirect_and_error_body_not_followed_or_exposed(self):
        seen = []
        def reply(request):
            seen.append(str(request.url))
            return httpx.Response(307, headers={"Location": "https://external.invalid/"}, content=b"SECRET-FAKE")
        with VastAPI("fake-test-key", transport=httpx.MockTransport(reply)) as read:
            with self.assertRaisesRegex(VastError, "body omitted"):
                discover(read, self.limits)
        self.assertEqual(seen, [ORIGIN + "/api/v0/bundles"])
