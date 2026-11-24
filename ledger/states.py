"""Persist forward-only package transitions and their audit events."""

NEXT = {"queued": "production", "production": "QA", "QA": "invoiced", "invoiced": "settled"}


def advance_package(db, package_id, expected, target):
    if NEXT.get(expected) != target or target is None:
        raise ValueError(f"Invalid transition: {expected} → {target}")
    if db.in_transaction:
        raise ValueError("Package transition requires its own transaction")

    with db:
        changed = db.execute("""
            UPDATE packages
            SET status = ?, settled_at = CASE WHEN ? = 'settled' THEN CURRENT_TIMESTAMP ELSE NULL END
            WHERE package_id = ? AND status = ?
        """, (target, target, package_id, expected))
        if changed.rowcount != 1:
            return False
        db.execute("""
            INSERT INTO package_events(package_id, prior_state, new_state) VALUES (?, ?, ?)
        """, (package_id, expected, target))
    return True
