"""Fixed-origin Vast API adapter. A POST to bundles is a search, not a rental."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json
import os
import re

import httpx

ORIGIN = "https://console.vast.ai"
MAX_JSON = 2_000_000
KEY_RE = re.compile(r"[!-~]{8,1024}", re.ASCII)
SAFE_TEXT = re.compile(r"[A-Za-z0-9 ._(),/++:-]{1,100}", re.ASCII)
HOST_RE = re.compile(r"(?:ssh[0-9]+\.vast\.ai|(?:[0-9]{1,3}\.){3}[0-9]{1,3})", re.ASCII)
IMAGE = "vastai/base-image:@vastai-automatic-tag"


class VastError(RuntimeError):
    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


def integer(value, low: int, high: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{field} must be an integer in [{low}, {high}].")
    return value


def amount(value, field: str, low: str = "0", high: str = "1000000") -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)) or len(str(value)) > 32:
        raise ValueError(f"{field} must be a bounded decimal.")
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"{field} must be a bounded decimal.") from None
    if not result.is_finite() or not Decimal(low) <= result <= Decimal(high):
        raise ValueError(f"{field} must be in [{low}, {high}].")
    return result


def decimal_text(value: Decimal) -> str:
    return str(value.normalize())


def safe_text(value) -> str | None:
    return value if isinstance(value, str) and SAFE_TEXT.fullmatch(value) else None


def get_key(variable: str) -> str:
    key = os.environ.get(variable)
    if key is None or KEY_RE.fullmatch(key) is None:
        raise VastError(f"Missing or malformed {variable}; configure it locally.")
    return key


class VastAPI:
    def __init__(self, key: str, *, transport: httpx.BaseTransport | None = None, writable: bool = False):
        self._key = key
        self._writable = writable
        self._client = httpx.Client(
            base_url=ORIGIN, follow_redirects=False, trust_env=False, transport=transport,
            timeout=httpx.Timeout(12, connect=5), headers={"Accept": "application/json"},
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._client.close()

    def _request(self, method: str, path: str, payload: dict | None = None, *, params: dict | None = None) -> dict:
        try:
            with self._client.stream(
                method, path, json=payload, params=params, headers={"Authorization": "Bearer " + self._key}
            ) as response:
                if not 200 <= response.status_code < 300:
                    raise VastError(f"Vast HTTP {response.status_code}; provider body omitted.", response.status_code)
                chunks = bytearray()
                for chunk in response.iter_bytes():
                    if len(chunks) + len(chunk) > MAX_JSON:
                        raise VastError("Vast response exceeded the size limit.")
                    chunks.extend(chunk)
            parsed = json.loads(chunks, parse_float=Decimal)
        except (httpx.HTTPError, json.JSONDecodeError, UnicodeError, ValueError) as exc:
            raise VastError(f"Vast response unavailable or invalid ({type(exc).__name__}).") from None
        if not isinstance(parsed, dict) or parsed.get("success") is False or "error" in parsed:
            raise VastError("Vast did not confirm success; provider body omitted.")
        return parsed

    def offers(self, *, limit: int, min_vram_mb: int, disk_gb: int, minutes: int,
               rate_cap: Decimal, offer_id: int | None = None) -> list[dict]:
        query = {
            "limit": limit, "type": "on-demand", "order": [["dph_total", "asc"]],
            "verified": {"eq": True}, "rentable": {"eq": True},
            "rented": {"eq": False}, "external": {"eq": False},
            "num_gpus": {"eq": 1}, "gpu_arch": {"eq": "nvidia"}, "direct_port_count": {"gte": 1},
            "gpu_ram": {"gte": min_vram_mb}, "disk_space": {"gte": disk_gb},
            "allocated_storage": disk_gb, "duration": {"gte": minutes * 60},
            "dph_total": {"lte": float(rate_cap)},
        }
        if offer_id is not None:
            query["id"] = {"eq": offer_id}
        offers = self._request("POST", "/api/v0/bundles", query).get("offers")
        # Docs' example uses an object; the formal schema lists an array.
        if isinstance(offers, dict):
            offers = [offers]
        if not isinstance(offers, list) or len(offers) > 100 or any(not isinstance(o, dict) for o in offers):
            raise VastError("Unexpected Vast offers response.")
        return offers

    def create(self, offer_id: int, disk_gb: int, label: str) -> int:
        self._require_write()
        outcome = self._request("PUT", f"/api/v0/asks/{offer_id}", {
            "image": IMAGE, "disk": disk_gb, "label": label, "runtype": "ssh_direct",
            "target_state": "running", "cancel_unavail": True,
        })
        if outcome.get("success") is not True:
            raise VastError("Vast did not positively confirm an instance creation.")
        try:
            return integer(outcome.get("new_contract"), 1, 2**63 - 1, "instance ID")
        except ValueError:
            raise VastError("Vast returned an invalid instance ID.") from None

    def show(self, instance_id: int) -> dict:
        parsed = self._request("GET", f"/api/v0/instances/{instance_id}").get("instances")
        if isinstance(parsed, list) and len(parsed) == 1:
            parsed = parsed[0]
        if not isinstance(parsed, dict) or type(parsed.get("id")) is not int or parsed["id"] != instance_id:
            raise VastError("Vast did not return the requested instance.")
        return parsed

    def list_receipt_instances(self, label: str, instance_id: int | None = None) -> list[int]:
        """Traverse up to 10 unfiltered pages; incomplete/error never implies absence."""
        seen_ids: set[int] = set()
        seen_tokens: set[str] = set()
        matches: list[int] = []
        cursor = None
        for _ in range(10):
            filters = {"limit": 25}
            if cursor is not None:
                filters["after_token"] = cursor
            page = self._request("GET", "/api/v1/instances", params=filters)
            rows, next_cursor = page.get("instances"), page.get("next_token")
            if page.get("success") is not True or not isinstance(rows, list) or len(rows) > 25 or "next_token" not in page:
                raise VastError("Vast instance listing is incomplete or malformed.")
            for row in rows:
                if not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] < 1 or "label" not in row:
                    raise VastError("Vast returned an unverifiable instance listing.")
                key = row["id"]
                if key in seen_ids:
                    raise VastError("Duplicate instance in pagination; absence cannot be verified.")
                seen_ids.add(key)
                if row["label"] == label or key == instance_id:
                    matches.append(key)
            if next_cursor is None:
                total = page.get("total_instances")
                if type(total) is not int or total != len(seen_ids):
                    raise VastError("Vast listing total does not match the complete traversal.")
                return matches
            if not isinstance(next_cursor, str) or len(next_cursor) > 1024 or not next_cursor or next_cursor in seen_tokens:
                raise VastError("Vast pagination did not provide a safe new cursor.")
            seen_tokens.add(next_cursor)
            cursor = next_cursor
        raise VastError("Vast list exceeded the 250-instance safety bound; use the owner console.")

    def stop(self, instance_id: int) -> None:
        self._require_write()
        response = self._request("PUT", f"/api/v0/instances/{instance_id}", {"state": "stopped"})
        if response.get("success") is not True:
            raise VastError("Vast did not positively acknowledge the stop request.")

    def destroy(self, instance_id: int) -> None:
        self._require_write()
        response = self._request("DELETE", f"/api/v0/instances/{instance_id}")
        if response.get("success") is not True:
            raise VastError("Vast did not positively acknowledge the destroy request.")

    def _require_write(self) -> None:
        if not self._writable:
            raise VastError("Mutation disabled on this client.")
