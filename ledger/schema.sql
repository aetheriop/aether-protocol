PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS packages (
    package_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'production', 'QA', 'invoiced', 'settled')),
    budget_cents INTEGER NOT NULL CHECK (typeof(budget_cents) = 'integer' AND budget_cents >= 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    settled_at TEXT,
    CHECK ((status = 'settled') = (settled_at IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS charges (
    operation_id TEXT PRIMARY KEY,
    package_id TEXT NOT NULL REFERENCES packages(package_id),
    category TEXT NOT NULL CHECK (category IN ('models', 'review', 'infrastructure', 'fees')),
    amount_cents INTEGER NOT NULL CHECK (typeof(amount_cents) = 'integer' AND amount_cents > 0),
    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS charges_package ON charges(package_id);

CREATE TRIGGER IF NOT EXISTS check_new_charge
BEFORE INSERT ON charges
BEGIN
    SELECT CASE WHEN EXISTS (SELECT 1 FROM charges WHERE operation_id = NEW.operation_id)
      THEN RAISE(ABORT, 'Operation already recorded') END;
    SELECT CASE WHEN (
        SELECT status FROM packages WHERE package_id = NEW.package_id
    ) IN ('queued', 'settled') THEN RAISE(ABORT, 'Package does not accept charges') END;
    SELECT CASE WHEN NEW.amount_cents + COALESCE((
        SELECT SUM(amount_cents) FROM charges WHERE package_id = NEW.package_id
    ), 0) > (SELECT budget_cents FROM packages WHERE package_id = NEW.package_id)
      THEN RAISE(ABORT, 'Package budget exceeded') END;
END;

CREATE TABLE IF NOT EXISTS receipts (
    payment_ref TEXT PRIMARY KEY,
    package_id TEXT NOT NULL REFERENCES packages(package_id),
    amount_cents INTEGER NOT NULL CHECK (typeof(amount_cents) = 'integer' AND amount_cents > 0),
    cleared_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS receipts_package ON receipts(package_id);

CREATE TABLE IF NOT EXISTS package_events (
    event_id INTEGER PRIMARY KEY,
    package_id TEXT NOT NULL REFERENCES packages(package_id),
    prior_state TEXT NOT NULL,
    new_state TEXT NOT NULL,
    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE VIEW IF NOT EXISTS package_cash_summary AS
SELECT p.package_id, p.status, p.budget_cents,
       COALESCE((SELECT SUM(c.amount_cents) FROM charges c WHERE c.package_id = p.package_id), 0) AS expense_cents,
       COALESCE((SELECT SUM(r.amount_cents) FROM receipts r WHERE r.package_id = p.package_id), 0) AS received_cents
FROM packages p;
