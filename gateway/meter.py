

from dataclasses import dataclass


@dataclass(frozen=True)
class Tariff:
    input_per_million: int
    output_per_million: int

    def __post_init__(self):
        for value in (self.input_per_million, self.output_per_million):
            if type(value) is not int or not 0 <= value <= 10**12:
                raise ValueError("Tariffs must be nonnegative integer microdollars")


def init_meter(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS usage_entries (
            request_id TEXT PRIMARY KEY,
            key_id TEXT NOT NULL REFERENCES client_keys(key_id),
            model TEXT NOT NULL,
            input_tokens INTEGER NOT NULL CHECK(input_tokens >= 0),
            output_tokens INTEGER NOT NULL CHECK(output_tokens >= 0),
            charge_micros INTEGER NOT NULL CHECK(charge_micros >= 0),
            recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)


def charge_for_usage(usage, tariff):
    if not isinstance(usage, dict):
        raise ValueError("Upstream usage is missing")
    input_count = usage.get("prompt_tokens")
    output_count = usage.get("completion_tokens")
    for count in (input_count, output_count):
        if type(count) is not int or not 0 <= count <= 10**9:
            raise ValueError("Invalid upstream token counts")
    numerator = input_count * tariff.input_per_million + output_count * tariff.output_per_million
    return input_count, output_count, (numerator + 999999) // 1000000


def record_usage(db, request_id, key_id, model, usage, tariff):
    values = (key_id, model, *charge_for_usage(usage, tariff))
    with db:
        db.execute("""
            INSERT INTO usage_entries(request_id, key_id, model, input_tokens, output_tokens, charge_micros)
            VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(request_id) DO NOTHING
        """, (request_id, *values))
        stored = db.execute("""
            SELECT key_id, model, input_tokens, output_tokens, charge_micros
            FROM usage_entries WHERE request_id = ?
        """, (request_id,)).fetchone()
        if stored != values:
            raise ValueError("Request ID already has different metering data")
    return values[-1]
