"""Reserve cash in priority order and within the positive margin available."""

from settlement.window import require_amounts


def allocate_reserves(net_margin, *, disputes=0, rework=0, unpaid=0, cap=None):
    if type(net_margin) is not int:
        raise ValueError("Net margin must be an integer")
    requested = {"disputes": disputes, "rework": rework, "unpaid": unpaid}
    require_amounts(*requested.values())
    available = max(0, net_margin)
    if cap is not None:
        require_amounts(cap)
        available = min(available, cap)
    reserved = {}
    for reason, amount in requested.items():
        reserved[reason] = min(available, amount)
        available -= reserved[reason]
    return reserved
