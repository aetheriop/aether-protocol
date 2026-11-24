import pytest

from settlement.carry import turnover_reward
from settlement.reserves import allocate_reserves
from settlement.waterfall import absorb_loss, distribute
from settlement.window import Window, calculate_window


@pytest.mark.parametrize("receipts,models,review,fees,reserve,expected", [
    (100_000, 42_000, 18_000, 10_000, 6_000, Window(30_000, 6_000, 24_000)),
    (20_000, 30_000, 2_500, 0, 1_000, Window(-12_500, 0, 0)),
    (10_000, 8_000, 2_000, 0, 4_000, Window(0, 0, 0)),
    (10_000, 6_000, 0, 0, 9_000, Window(4_000, 4_000, 0)),
    (10_000, 1_000, 500, 0, 0, Window(8_500, 0, 8_500)),
])
def test_window(receipts, models, review, fees, reserve, expected):
    assert calculate_window(receipts, models, review, fees, reserve) == expected


@pytest.mark.parametrize("value", [-1, 1.5, True, None])
def test_window_rejects_invalid_cents(value):
    with pytest.raises(ValueError):
        calculate_window(value, 0, 0, 0, 0)


def test_dispute_uses_available_base_before_other_reserves():
    reserved = allocate_reserves(9_000, disputes=10_000, rework=2_000, unpaid=4_000)
    assert reserved == {"disputes": 9_000, "rework": 0, "unpaid": 0}
    assert calculate_window(10_000, 1_000, 0, 0, sum(reserved.values())).distributable_base == 0


def test_reserves_obey_policy_cap():
    assert allocate_reserves(9_000, disputes=4_000, rework=3_000, unpaid=2_000, cap=5_000) == {
        "disputes": 4_000, "rework": 1_000, "unpaid": 0
    }


def test_no_reserve_is_withheld_in_loss_window():
    assert sum(allocate_reserves(-1_000, disputes=500).values()) == 0


def test_negative_window_allocates_zero():
    base = calculate_window(1_000, 2_000, 0, 0, 0).distributable_base
    assert distribute(base, {"Core": 99, "Frontier": 99}).applied == {"Core": 0, "Frontier": 0}


def test_distribution_follows_priority_and_caps():
    result = distribute(180, {"Frontier": 100, "Core": 100, "Spark": 50, "Adaptive": 40})
    assert result.applied == {"Spark": 50, "Core": 100, "Adaptive": 30, "Frontier": 0}
    assert result.remaining == 0


def test_surplus_distribution_remains_unallocated():
    result = distribute(125, {"Core": 100})
    assert result.applied == {"Core": 100}
    assert result.remaining == 25


def test_frontier_absorbs_loss_first():
    result = absorb_loss(120, {"Spark": 90, "Core": 100, "Adaptive": 80, "Frontier": 100})
    assert result.applied == {"Frontier": 100, "Adaptive": 20, "Core": 0, "Spark": 0}
    assert result.remaining == 0


def test_loss_above_total_capital_is_reported():
    result = absorb_loss(700, {"Frontier": 300, "Adaptive": 250})
    assert result.applied == {"Frontier": 300, "Adaptive": 250}
    assert result.remaining == 150


@pytest.mark.parametrize("priority", [("Core", "Core"), ("Frontier",), ("Core", "Unknown")])
def test_invalid_priority_is_rejected(priority):
    with pytest.raises(ValueError):
        distribute(10, {"Core": 100}, priority=priority)


@pytest.mark.parametrize("capital,rate,unlocked,expected", [
    (10_000, 500, False, 500),
    (10_000, 500, True, 250),
    (20_000, 3, True, 3),
    (0, 500, True, 0),
    (20_000, 0, False, 0),
])
def test_turnover_reward(capital, rate, unlocked, expected):
    assert turnover_reward(capital, rate, unlocked=unlocked) == expected
