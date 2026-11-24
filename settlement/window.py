"""Reconcile collected cash before allocating a participation share. Amounts are in cents."""

from dataclasses import dataclass


def require_amounts(*values):
    if any(type(value) is not int or value < 0 for value in values):
        raise ValueError("Amounts must be nonnegative integers")


@dataclass(frozen=True)
class Window:
    net_margin: int
    held_reserve: int
    distributable_base: int


def calculate_window(receipts, models, review, fees, reserve):
    require_amounts(receipts, models, review, fees, reserve)
    net_margin = receipts - models - review - fees
    available = max(0, net_margin)
    held_reserve = min(reserve, available)
    return Window(net_margin, held_reserve, available - held_reserve)
