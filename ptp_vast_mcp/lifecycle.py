"""One managed rental; uncertain requests hold the local slot until reconciled."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import json
import os
import sqlite3
import time
import uuid
import ipaddress

from .api import HOST_RE, VastAPI, VastError, amount, decimal_text, integer, safe_text
from .planner import Limits, digest, exact_quote

QUOTE_VALID_SECONDS = 90


class Ledger:
    def __init__(self, file: Path):
        self.file = Path(file)
        self.file.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS leases (label TEXT PRIMARY KEY, state TEXT NOT NULL, record TEXT NOT NULL)"
            )
        if os.name != "nt":
            self.file.chmod(0o600)

    @contextmanager
    def _connection(self):
        db = sqlite3.connect(self.file, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def open(self) -> dict | None:
        with self._connection() as db:
            rows = db.execute("SELECT record FROM leases WHERE state <> 'CLOSED'").fetchall()
        if len(rows) > 1:
            raise VastError("Multiple active local receipts; stop and reconcile in Vast console.")
        return json.loads(rows[0][0]) if rows else None

    def reserve(self, record: dict) -> None:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM leases WHERE state <> 'CLOSED'").fetchone():
                raise VastError("An active or unresolved local lease already exists; no new rental sent.")
            db.execute("INSERT INTO leases VALUES (?, ?, ?)",
                       (record["label"], record["state"], json.dumps(record)))

    def change(self, record: dict, next_state: str, **extra) -> dict:
        updated = {**record, **extra, "state": next_state, "updated_epoch": int(time.time())}
        with self._connection() as db:
            changed = db.execute("UPDATE leases SET state=?, record=? WHERE label=? AND state=? AND record=?",
                                 (next_state, json.dumps(updated), record["label"], record["state"],
                                  json.dumps(record))).rowcount
            if changed != 1:
                raise VastError("Local receipt changed concurrently. Refresh and reconcile before acting.")
        return updated


def prepare_rental(api: VastAPI, limits: Limits, offer_id: int) -> tuple[dict, float]:
    return exact_quote(api, limits, offer_id), time.monotonic() + QUOTE_VALID_SECONDS


def rent(api: VastAPI, ledger: Ledger, limits: Limits, quote: dict, deadline: float) -> dict:
    if time.monotonic() >= deadline:
        raise VastError("Human quote expired; request a fresh quote.")
    fresh = exact_quote(api, limits, quote["offer_id"])
    if time.monotonic() >= deadline or digest(fresh) != digest(quote):
        raise VastError("Quote changed or expired; no rental sent. Review a new quote.")
    label = "ptp-vast-" + uuid.uuid4().hex
    lease = {
        "label": label, "state": "CREATE_PENDING", "instance_id": None,
        "offer_id": quote["offer_id"], "quote": quote, "quote_sha256": digest(quote),
        "created_epoch": int(time.time()), "planned_destroy_by_epoch": int(time.time()) + 60 * limits.minutes,
    }
    ledger.reserve(lease)
    # One PUT only. Before it, the durable pending state is already committed.
    try:
        instance_id = api.create(quote["offer_id"], limits.disk_gb, label)
    except VastError:
        raise VastError(f"Create outcome unresolved for label {label}. Confirm in Vast console; do not retry.") from None
    return ledger.change(lease, "MANAGED", instance_id=instance_id)


def read_owned(api: VastAPI, record: dict) -> dict:
    if not record.get("instance_id"):
        raise VastError("Instance ID unknown; inspect Vast console for the full local receipt label.")
    row = api.show(record["instance_id"])
    if row.get("label") != record["label"]:
        raise VastError("Provider label does not match this local receipt; no mutation sent.")
    return row


def adopt(api: VastAPI, ledger: Ledger, record: dict, instance_id: int) -> dict:
    if record["state"] != "CREATE_PENDING":
        raise VastError("Adoption only resolves a pending create.")
    integer(instance_id, 1, 2**63-1, "instance ID")
    read_owned(api, {**record, "instance_id": instance_id})
    return ledger.change(record, "MANAGED", instance_id=instance_id)


def stop(api: VastAPI, ledger: Ledger, record: dict) -> dict:
    if record["state"] != "MANAGED":
        raise VastError("Resolve the pending operation before stopping.")
    remote = read_owned(api, record)
    if remote.get("actual_status") in {"stopped", "exited"}:
        return record
    pending = ledger.change(record, "STOP_PENDING")
    try:
        api.stop(record["instance_id"])
    except VastError:
        raise VastError("Stop outcome unresolved. Run status/reconcile and inspect Vast console; do not retry blindly.") from None
    # Acknowledgment is not proof of stopped GPU.
    try:
        return reconcile(api, ledger, pending)
    except VastError:
        return pending


def destroy(api: VastAPI, ledger: Ledger, record: dict) -> dict:
    if record["state"] != "MANAGED":
        raise VastError("Resolve the pending operation before destroying.")
    read_owned(api, record)
    pending = ledger.change(record, "DESTROY_PENDING")
    try:
        api.destroy(record["instance_id"])
    except VastError:
        raise VastError("Destroy outcome unresolved. Run reconcile and inspect Vast console; charges may continue.") from None
    acknowledged = ledger.change(pending, "DESTROY_ACKNOWLEDGED")
    for _ in range(4):
        result = reconcile(api, ledger, acknowledged)
        if result["state"] == "CLOSED":
            return result
        time.sleep(1)
    return acknowledged


def reconcile(api: VastAPI, ledger: Ledger, record: dict) -> dict:
    state = record["state"]
    if state == "CREATE_PENDING":
        matches = api.list_receipt_instances(record["label"])
        if len(matches) != 1:
            raise VastError("Pending create: no unique receipt label in complete listing. Use the owner console; no automatic retry.")
        return adopt(api, ledger, record, matches[0])
    try:
        row = read_owned(api, record)
    except VastError as exc:
        # Error or missing exact ID alone is not stronger than a complete authenticated listing.
        if state == "DESTROY_ACKNOWLEDGED" and exc.code == 404:
            if not api.list_receipt_instances(record["label"], record["instance_id"]):
                return ledger.change(record, "CLOSED", closure="destroy acknowledged; exact GET 404 and complete authenticated list absence")
            raise VastError("Vast still lists this receipt or ID; cleanup is not confirmed.") from None
        if state == "DESTROY_PENDING" and exc.code == 404:
            raise VastError("404 without positive destroy acknowledgment does not prove closure; verify the same Vast account and billing in console.") from None
        raise
    if state == "STOP_PENDING" and row.get("actual_status") in {"stopped", "exited"}:
        return ledger.change(record, "MANAGED", stop_observation="actual_status stopped/exited; storage may still bill")
    return record


def status(api: VastAPI, record: dict) -> dict:
    return _status_from_row(record, read_owned(api, record))


def _status_from_row(record: dict, remote: dict) -> dict:
    result = {k: record[k] for k in ("instance_id", "label", "state", "planned_destroy_by_epoch")}
    result["provider_actual_status"] = safe_text(remote.get("actual_status")) or "unknown"
    result["readiness"] = "SSH_GPU_CHECK_REQUIRED" if remote.get("actual_status") == "running" else "NOT_READY"
    result["planned_runtime_exceeded"] = time.time() >= record["planned_destroy_by_epoch"]
    result["live_rate_check"] = "UNAVAILABLE"
    try:
        live = amount(remote.get("dph_total"), "provider instance hourly rate", "0.00000001")
        quoted = amount(record["quote"]["usd_per_hour_listed"], "quoted hourly rate")
        result["live_usd_per_hour"] = decimal_text(live)
        result["live_rate_check"] = "ABOVE_QUOTE_STOP_OR_DESTROY" if live > quoted else "AT_OR_BELOW_QUOTE"
    except ValueError:
        pass
    return result


def connection(api: VastAPI, record: dict) -> dict:
    if record["state"] != "MANAGED":
        raise VastError("Connection refused while an operation is pending.")
    remote = read_owned(api, record)
    view = _status_from_row(record, remote)
    if view["live_rate_check"] == "ABOVE_QUOTE_STOP_OR_DESTROY":
        raise VastError("Instance reports a rate higher than the quote. Inspect pricing and stop/destroy before connecting.")
    if remote.get("actual_status") != "running":
        raise VastError("Provider has not reported the instance running.")
    host = remote.get("ssh_host")
    if not isinstance(host, str) or HOST_RE.fullmatch(host) is None:
        raise VastError("SSH host is not a supported Vast proxy hostname/IPv4.")
    if "." in host and not host.endswith(".vast.ai"):
        try:
            if not ipaddress.IPv4Address(host).is_global:
                raise ValueError
        except ValueError:
            raise VastError("SSH host is not a globally routable IPv4.") from None
    port = integer(remote.get("ssh_port"), 1, 65535, "SSH port")
    return {
        "instance_id": record["instance_id"], "host": host, "port": port, "user": "root",
        "ssh_argv_for_owner": ["ssh", "-p", str(port), "root@" + host],
        "gpu_probe_argv_for_owner": ["ssh", "-p", str(port), "root@" + host, "nvidia-smi", "-L"],
        "readiness": "SSH_GPU_CHECK_REQUIRED",
    }
