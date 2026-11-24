"""Shared candidate ranking and quote arithmetic from the PTP offer planner."""
from collections.abc import Iterable
from decimal import Decimal, ROUND_UP

USD_PRECISION = Decimal("0.000001")


def verified_and_available(row: dict) -> bool:
    return (
        row.get("rentable") is True
        and row.get("rented") is False
        and (row.get("verification") == "verified"
             or ("verification" not in row and row.get("verified") is True))
        and ("verified" not in row or row.get("verified") is True)
    )


def hourly_cost_for_minutes(rate: Decimal, minutes: Decimal | int) -> Decimal:
    return rate * minutes / 60


def round_estimate(value: Decimal) -> str:
    return format(value.quantize(USD_PRECISION, rounding=ROUND_UP), "f")


def rank_offers(
    candidates: Iterable[dict], *, hourly_field: str, limit: int
) -> list[dict]:
    offers = list(candidates)
    if len({row["offer_id"] for row in offers}) != len(offers):
        raise ValueError("Duplicate offers; cannot establish exact quote identity.")
    return sorted(offers, key=lambda row: (Decimal(row[hourly_field]), row["offer_id"]))[:limit]
