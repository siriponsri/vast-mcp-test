from decimal import Decimal as D

import pytest
from fastmcp.exceptions import ToolError

from vast_mcp.offers import estimate_run_cost, search_gpu_offers


def test_filters_and_unknown_rate():
    result = search_gpu_offers(
        gpu_name="rtx_4090", country_code="us", min_gpu_count=2, min_vram_mib=24576,
        min_reliability=D(".99"), max_hourly_usd=D(".82"), disk_gb=100,
    )
    assert len(result["offers"]) == 1
    offer = result["offers"][0]
    assert offer["offer_id"] == "mock-103"
    assert offer["download_from_host_usd_per_gb"] is None
    assert offer["hourly_including_disk_usd"] == "0.820000"
    cost = estimate_run_cost("mock-103", 100, D(3), D(10), D(4))
    assert cost["known_subtotal_usd"] == "2.660000"
    assert cost["estimated_total_usd"] is None
    assert cost["unknown_charges"] == ["download_from_host"]
    assert estimate_run_cost("mock-103", 100, D(3), D(10), D(0))[
        "estimated_total_usd"
    ] == "2.660000"


def test_estimate_bills_allocated_disk_once():
    cost = estimate_run_cost("mock-102", 250, D("7.5"), D("2.5"), D("5"))
    assert cost["compute_usd"] == "3.300000"
    assert cost["allocated_disk_usd"] == "0.375000"
    assert cost["upload_to_host_usd"] == "0.025000"
    assert cost["download_from_host_usd"] == "0.150000"
    assert cost["estimated_total_usd"] == "3.850000"


@pytest.mark.parametrize(("offer_id", "disk"), [("mock-101", 251), ("mock-105", 20),
                                               ("mock-106", 20), ("mock-999", 20)])
def test_estimate_rejects_unrentable_unknown_or_excess_disk(offer_id, disk):
    with pytest.raises(ToolError):
        estimate_run_cost(offer_id, disk, D(1), D(0), D(0))
