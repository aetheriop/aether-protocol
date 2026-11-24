"""Compute a configured turnover reward for capital still active in a window."""

from settlement.window import require_amounts


def turnover_reward(active_capital, rate_bps, *, unlocked=False):
    require_amounts(active_capital, rate_bps)
    if type(unlocked) is not bool:
        raise ValueError("Unlock status must be boolean")
    if rate_bps > 10_000:
        raise ValueError("Rate must be applicable as basis points")
    # Halve the rate before the final rounding; this preserves half basis points.
    denominator = 20_000 if unlocked else 10_000
    return active_capital * rate_bps // denominator
