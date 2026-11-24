"""Offer filtering and exact-identity human quote, with no side effects."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import InvalidOperation
import hashlib
import json

from .api import IMAGE, VastAPI, VastError, amount, decimal_text, integer, safe_text
from .offer_math import hourly_cost_for_minutes, rank_offers, round_estimate, verified_and_available

MAX_HOURLY = "2.00"
MAX_ESTIMATE = "8.00"


@dataclass(frozen=True)
class Limits:
    min_vram_mb: int = 16_000
    disk_gb: int = 24
    minutes: int = 30
    max_hourly_usd: str = "0.75"
    max_estimated_usd: str = "0.50"

    def __post_init__(self):
        integer(self.min_vram_mb, 80, 200_000, "VRAM MB")
        integer(self.disk_gb, 8, 100, "disk GB")
        integer(self.minutes, 1, 120, "planned minutes")
        amount(self.max_hourly_usd, "hourly cap", "0.01", MAX_HOURLY)
        amount(self.max_estimated_usd, "estimated total cap", "0.01", MAX_ESTIMATE)


def evaluate(row: dict, limits: Limits) -> dict | None:
    try:
        offer_id = integer(row.get("id"), 1, 2**63-1, "offer ID")
        host_id = integer(row.get("machine_id"), 1, 2**63-1, "machine ID")
        gpu = safe_text(row.get("gpu_name"))
        vram = integer(row.get("gpu_ram"), limits.min_vram_mb, 300_000, "VRAM MB")
        rate = amount(row.get("dph_total"), "Vast listed hourly rate", "0.00000001", MAX_HOURLY)
        disk = amount(row.get("disk_space"), "Vast available disk", str(limits.disk_gb))
        duration = amount(row.get("duration"), "Vast remaining duration", str(limits.minutes * 60), "100000000000")
        del disk, duration
        if not (
            gpu and type(row.get("num_gpus")) is int and row["num_gpus"] == 1
            and row.get("gpu_arch") == "nvidia" and verified_and_available(row)
            and (row.get("external") is None or row.get("external") is False)
            and ("is_bid" not in row or row.get("is_bid") is False)
            and type(row.get("direct_port_count")) is int and row["direct_port_count"] >= 1
            and rate <= amount(limits.max_hourly_usd, "hourly cap")
            and rate * limits.minutes <= 60 * amount(limits.max_estimated_usd, "estimated total cap")
        ):
            return None
        return {
            "offer_id": offer_id, "machine_id": host_id, "gpu": gpu, "vram_mb": vram,
            "usd_per_hour_listed": decimal_text(rate),
            "planned_compute_and_disk_estimate_usd": round_estimate(hourly_cost_for_minutes(rate, limits.minutes)),
            "planned_minutes": limits.minutes, "allocated_storage_gb": limits.disk_gb,
            "image": IMAGE, "ssh_mode": "ssh_direct",
        }
    except (ValueError, InvalidOperation):
        return None


def discover(api: VastAPI, limits: Limits, limit: int = 8, offer_id: int | None = None) -> list[dict]:
    integer(limit, 1, 20, "limit")
    if offer_id is not None:
        integer(offer_id, 1, 2**63-1, "offer ID")
    found = api.offers(limit=limit, min_vram_mb=limits.min_vram_mb, disk_gb=limits.disk_gb,
                       minutes=limits.minutes, rate_cap=amount(limits.max_hourly_usd, "hourly cap"),
                       offer_id=offer_id)
    output = [item for row in found if (item := evaluate(row, limits)) is not None
              and (offer_id is None or item["offer_id"] == offer_id)]
    try:
        return rank_offers(output, hourly_field="usd_per_hour_listed", limit=limit)
    except ValueError as exc:
        raise VastError(str(exc)) from None


def exact_quote(api: VastAPI, limits: Limits, offer_id: int) -> dict:
    offers = discover(api, limits, 1, offer_id)
    if len(offers) != 1:
        raise VastError("Exact offer unavailable, ineligible, malformed, or over either cap.")
    return offers[0]


def digest(quote: dict) -> str:
    return hashlib.sha256(json.dumps(quote, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
