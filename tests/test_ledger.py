import sqlite3
from pathlib import Path

import pytest

from ledger.states import advance_package


@pytest.fixture
def ledger():
    db = sqlite3.connect(":memory:")
    db.executescript(Path("ledger/schema.sql").read_text())
    with db:
        db.execute("INSERT INTO packages(package_id, title, budget_cents) VALUES ('test-package','Test package',10000)")
    yield db
    db.close()


def test_full_lifecycle_and_timestamps(ledger):
    for current, target in [("queued", "production"), ("production", "QA"), ("QA", "invoiced"), ("invoiced", "settled")]:
        assert advance_package(ledger, "test-package", current, target)
    status, settled_at = ledger.execute("SELECT status, settled_at FROM packages").fetchone()
    assert status == "settled" and settled_at
    assert ledger.execute("SELECT COUNT(*) FROM package_events").fetchone()[0] == 4


@pytest.mark.parametrize("current,target", [("queued", "QA"), ("invoiced", "production"), ("settled", "settled")])
def test_invalid_package_transition(ledger, current, target):
    with pytest.raises(ValueError):
        advance_package(ledger, "test-package", current, target)


def test_revision_conflict_does_not_create_extra_event(ledger):
    assert advance_package(ledger, "test-package", "queued", "production")
    assert not advance_package(ledger, "test-package", "queued", "production")
    assert ledger.execute("SELECT COUNT(*) FROM package_events").fetchone()[0] == 1


def test_budget_is_checked_and_report_uses_collected_cash(ledger):
    advance_package(ledger, "test-package", "queued", "production")
    with ledger:
        ledger.execute("INSERT INTO charges(operation_id, package_id, category, amount_cents) VALUES ('first','test-package','models',9000)")
        ledger.execute("INSERT INTO receipts(payment_ref, package_id, amount_cents) VALUES ('cleared','test-package',14000)")
    with pytest.raises(sqlite3.IntegrityError, match="budget exceeded"), ledger:
        ledger.execute("INSERT INTO charges(operation_id, package_id, category, amount_cents) VALUES ('second','test-package','review',1500)")
    assert ledger.execute("SELECT expense_cents, received_cents FROM package_cash_summary").fetchone() == (9000, 14000)


def test_queued_package_cannot_be_charged(ledger):
    with pytest.raises(sqlite3.IntegrityError, match="does not accept charges"), ledger:
        ledger.execute("INSERT INTO charges(operation_id, package_id, category, amount_cents) VALUES ('first','test-package','models',100)")


def test_duplicate_operation_cannot_replace_a_charge(ledger):
    advance_package(ledger, "test-package", "queued", "production")
    statement = " INTO charges(operation_id, package_id, category, amount_cents) VALUES ('first','test-package','models',?)"
    with ledger:
        ledger.execute("INSERT" + statement, (3000,))
    with pytest.raises(sqlite3.IntegrityError, match="already recorded"), ledger:
        ledger.execute("INSERT OR REPLACE" + statement, (12000,))
    assert ledger.execute("SELECT expense_cents FROM package_cash_summary").fetchone()[0] == 3000
