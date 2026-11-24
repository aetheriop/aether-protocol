"""Issue high-entropy bearer credentials and store only their digests."""

import argparse
import hashlib
import os
import secrets
import sqlite3
from contextlib import closing


def connect(path):
    db = sqlite3.connect(path, timeout=5)
    db.execute("PRAGMA foreign_keys = ON")
    return db


def init_keys(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS client_keys (
            key_id TEXT PRIMARY KEY,
            digest BLOB NOT NULL UNIQUE,
            revoked_at TEXT
        )
    """)


def issue_key(db):
    key_id = secrets.token_hex(12)
    token = "ath_" + secrets.token_urlsafe(32)
    db.execute("INSERT INTO client_keys(key_id, digest) VALUES (?, ?)",
               (key_id, hashlib.sha256(token.encode()).digest()))
    return key_id, token


def lookup_key(db, authorization):
    scheme, _, token = authorization.partition(" ")
    if scheme.casefold() != "bearer" or not token.startswith("ath_") or len(token) != 47:
        return None
    row = db.execute(
        "SELECT key_id FROM client_keys WHERE digest = ? AND revoked_at IS NULL",
        (hashlib.sha256(token.encode()).digest(),),
    ).fetchone()
    return row[0] if row else None


def revoke_key(db, key_id):
    result = db.execute("""
        UPDATE client_keys SET revoked_at = CURRENT_TIMESTAMP
        WHERE key_id = ? AND revoked_at IS NULL
    """, (key_id,))
    return result.rowcount == 1


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="gateway.sqlite")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("issue")
    commands.add_parser("revoke").add_argument("key_id")
    args = parser.parse_args()
    with closing(connect(args.database)) as db:
        init_keys(db)
        with db:
            if args.command == "issue":
                key_id, token = issue_key(db)
                print(f"Key ID: {key_id}\nBearer token: {token}")
            elif not revoke_key(db, args.key_id):
                parser.exit(1, "Active key not found\n")


if __name__ == "__main__":
    main()
