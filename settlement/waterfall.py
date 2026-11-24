"""Apply an explicitly ordered distribution or loss waterfall."""

from dataclasses import dataclass

from settlement.window import require_amounts

PAYMENT_PRIORITY = ("Spark", "Core", "Adaptive", "Frontier")
FIRST_LOSS_PRIORITY = ("Frontier", "Adaptive", "Core", "Spark")


@dataclass(frozen=True)
class Allocation:
    applied: dict[str, int]
    remaining: int


def _allocate(amount, limits, priority):
    priority = tuple(priority)
    require_amounts(amount, *limits.values())
    if (len(priority) != len(set(priority)) or not set(limits).issubset(priority)
            or not set(priority).issubset(PAYMENT_PRIORITY)):
        raise ValueError("Priority must include each supplied tranche exactly once")
    applied = {}
    for tranche in priority:
        if tranche in limits:
            applied[tranche] = min(amount, limits[tranche])
            amount -= applied[tranche]
    return Allocation(applied, amount)


def distribute(base, claims, *, priority=PAYMENT_PRIORITY):
    """Allocate a nonnegative window base subject to the supplied tranche caps."""
    return _allocate(base, claims, priority)


def absorb_loss(loss, capital, *, priority=FIRST_LOSS_PRIORITY):
    """Write off capital in first-loss order and report any unabsorbed remainder."""
    return _allocate(loss, capital, priority)
