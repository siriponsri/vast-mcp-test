from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastmcp.exceptions import ToolError
from pydantic import Field, StringConstraints

from ptp_vast_mcp.offer_math import (
    hourly_cost_for_minutes, rank_offers, round_estimate, verified_and_available,
)

D = Decimal
Disk = Annotated[int, Field(ge=1, le=16384, strict=True)]
Hours = Annotated[Decimal, Field(gt=0, le=8760, decimal_places=4)]
Transfer = Annotated[Decimal, Field(ge=0, le=100000, decimal_places=4)]
Hourly = Annotated[Decimal, Field(gt=0, le=10000, decimal_places=6)]
Reliability = Annotated[Decimal, Field(ge=0, le=1)]
Country = Annotated[str, StringConstraints(pattern=r"^[A-Za-z]{2}$")]
GpuName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9 _.-]{1,48}$")]
OfferId = Annotated[str, StringConstraints(pattern=r"^mock-[0-9]{3}$")]


def usd(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return round_estimate(value)


@dataclass(frozen=True)
class Offer:
    id: str
    gpu: str
    vram_mib: int
    gpu_count: int
    country: str
    reliability: Decimal
    disk_capacity_gb: int
    compute_per_hour: Decimal
    storage_per_gb_hour: Decimal
    upload_per_gb: Decimal | None
    download_per_gb: Decimal | None
    verified: bool = True
    rentable: bool = True

    def hourly(self, disk_gb: int) -> Decimal:
        return self.compute_per_hour + self.storage_per_gb_hour * disk_gb

    @property
    def available(self) -> bool:
        return verified_and_available({
            "verified": self.verified, "rentable": self.rentable, "rented": False,
        })


MOCK_OFFERS = (
    Offer("mock-101", "RTX 3090", 24576, 1, "US", D(".99"), 250,
          D(".24"), D(".0001"), D(".02"), D(".04")),
    Offer("mock-102", "RTX 4090", 24576, 1, "DE", D(".998"), 500,
          D(".44"), D(".0002"), D(".01"), D(".03")),
    Offer("mock-103", "RTX 4090", 24576, 2, "US", D(".995"), 1000,
          D(".80"), D(".0002"), D(".02"), None),
    Offer("mock-104", "A100 PCIe", 81920, 1, "JP", D(".997"), 1200,
          D("1.25"), D(".0003"), D(".03"), D(".05")),
    Offer("mock-105", "RTX 4090", 24576, 1, "US", D(".90"), 250,
          D(".15"), D(".0001"), D(".01"), D(".02"), verified=False),
    Offer("mock-106", "RTX 4090", 24576, 1, "US", D(".99"), 250,
          D(".15"), D(".0001"), D(".01"), D(".02"), rentable=False),
)


def timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def search_gpu_offers(
    gpu_name: GpuName | None = None,
    min_vram_mib: Annotated[int, Field(ge=1, le=1048576, strict=True)] = 1,
    min_gpu_count: Annotated[int, Field(ge=1, le=64, strict=True)] = 1,
    disk_gb: Disk = 40,
    country_code: Country | None = None,
    min_reliability: Reliability = D("0.95"),
    max_hourly_usd: Hourly | None = None,
    limit: Annotated[int, Field(ge=1, le=20, strict=True)] = 3,
) -> dict:
    """Find verified, rentable synthetic offers sorted by compute plus allocated disk.

    VRAM is per GPU in MiB. Country is a two-letter code. The hourly filter excludes transfers.
    """
    gpu = gpu_name.replace("_", " ").strip().casefold() if gpu_name else None
    country = country_code.upper() if country_code else None
    matches = (
        offer for offer in MOCK_OFFERS
        if offer.available
        and (gpu is None or gpu in offer.gpu.casefold())
        and offer.vram_mib >= min_vram_mib and offer.gpu_count >= min_gpu_count
        and offer.disk_capacity_gb >= disk_gb and offer.reliability >= min_reliability
        and (country is None or country == offer.country)
        and (max_hourly_usd is None or offer.hourly(disk_gb) <= max_hourly_usd)
    )
    quotes = (
        {
            "offer_id": offer.id,
            "gpu_name": offer.gpu,
            "vram_mib_per_gpu": offer.vram_mib,
            "gpu_count": offer.gpu_count,
            "country_code": offer.country,
            "reliability": str(offer.reliability),
            "verified": offer.verified,
            "rentable": offer.rentable,
            "disk_gb": disk_gb,
            "host_disk_capacity_gb": offer.disk_capacity_gb,
            "hourly_including_disk_usd": usd(offer.hourly(disk_gb)),
            "upload_to_host_usd_per_gb": usd(offer.upload_per_gb),
            "download_from_host_usd_per_gb": usd(offer.download_per_gb),
        }
        for offer in matches
    )
    return {
        "source": "synthetic",
        "snapshot_utc": timestamp(),
        "currency": "USD",
        "offers": rank_offers(quotes, hourly_field="hourly_including_disk_usd", limit=limit),
    }


def estimate_run_cost(
    offer_id: OfferId,
    disk_gb: Disk,
    hours: Hours,
    upload_to_host_gb: Transfer,
    download_from_host_gb: Transfer,
) -> dict:
    """Estimate a synthetic offer using its search allocation and explicit transfer volumes.

    Pass zero for a transfer direction you do not plan to use. A missing rate for
    planned traffic produces a known subtotal and an unknown total.
    """
    offer = next((row for row in MOCK_OFFERS if row.id == offer_id and row.available), None)
    if offer is None:
        raise ToolError("Select a verified, rentable offer from the synthetic search.")
    if disk_gb > offer.disk_capacity_gb:
        raise ToolError("The requested disk allocation exceeds this offer's capacity.")
    compute = hours * offer.compute_per_hour
    storage = hours * offer.storage_per_gb_hour * disk_gb
    upload = transfer_cost(upload_to_host_gb, offer.upload_per_gb)
    download = transfer_cost(download_from_host_gb, offer.download_per_gb)
    known_subtotal = (hourly_cost_for_minutes(offer.hourly(disk_gb), hours * 60)
                      + (upload or D(0)) + (download or D(0)))
    unknown = [name for name, cost in (
        ("upload_to_host", upload), ("download_from_host", download)
    ) if cost is None]
    return {
        "source": "synthetic",
        "snapshot_utc": timestamp(),
        "offer_id": offer.id,
        "currency": "USD",
        "hours": str(hours),
        "disk_gb": disk_gb,
        "upload_to_host_gb": str(upload_to_host_gb),
        "download_from_host_gb": str(download_from_host_gb),
        "hourly_including_disk_usd": usd(offer.hourly(disk_gb)),
        "compute_usd": usd(compute),
        "allocated_disk_usd": usd(storage),
        "upload_to_host_usd": usd(upload),
        "download_from_host_usd": usd(download),
        "known_subtotal_usd": usd(known_subtotal),
        "estimated_total_usd": None if unknown else usd(known_subtotal),
        "unknown_charges": unknown,
        "billing_note": "Synthetic estimate. Planned hours do not cap spend or stop billing.",
    }


def transfer_cost(volume: Decimal, rate: Decimal | None) -> Decimal | None:
    if volume == 0:
        return D(0)
    return None if rate is None else volume * rate
