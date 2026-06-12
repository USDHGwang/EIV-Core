"""
EIV — ValidationStore

Two implementations:

  ValidationStore     — in-memory + optional JSON files (default, zero-config)
  SqliteValidationStore — SQLite-backed with indexed queries (production)

Both expose the same core interface: put / get / list.
SqliteValidationStore adds query() for filtered lookups (by signer, verdict,
time range) — the foundation for the reputation layer.

Thread safety: both are safe for use with ThreadingHTTPServer.
"""

from __future__ import annotations

import glob
import json
import os
import sqlite3
import threading
from typing import Optional


class ValidationStore:
    """In-memory store with optional JSON-file persistence."""

    def __init__(self, store_dir: Optional[str] = None) -> None:
        self.store_dir = store_dir
        self._mem: dict[str, dict] = {}
        self._lock = threading.Lock()
        if store_dir:
            os.makedirs(store_dir, exist_ok=True)
            self._load_existing()

    def _load_existing(self) -> None:
        assert self.store_dir is not None
        for path in glob.glob(os.path.join(self.store_dir, "*.json")):
            try:
                with open(path, encoding="utf-8") as f:
                    rec = json.load(f)
                vid = rec.get("validation_id")
                if vid:
                    self._mem[vid] = rec
            except (OSError, json.JSONDecodeError):
                continue

    def put(self, record: dict) -> None:
        vid = record["validation_id"]
        with self._lock:
            self._mem[vid] = record
        if self.store_dir:
            path = os.path.join(self.store_dir, f"{vid}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, indent=2)

    def get(self, validation_id: str) -> Optional[dict]:
        with self._lock:
            return self._mem.get(validation_id)

    def list(self) -> list[dict]:
        with self._lock:
            snapshot = list(self._mem.values())
        return sorted(snapshot, key=lambda r: r.get("created_at", ""), reverse=True)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS validations (
    validation_id TEXT PRIMARY KEY,
    tx_ref        TEXT NOT NULL,
    signer        TEXT,
    verdict       TEXT NOT NULL,
    n_violations  INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    record        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_val_signer     ON validations(signer);
CREATE INDEX IF NOT EXISTS idx_val_verdict    ON validations(verdict);
CREATE INDEX IF NOT EXISTS idx_val_created_at ON validations(created_at DESC);
"""


class SqliteValidationStore:
    """SQLite-backed store with indexed queries for reputation lookups."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._local = threading.local()
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path)
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn is not None:
            self._local.conn.close()
            self._local.conn = None

    def _init_schema(self) -> None:
        conn = self._conn()
        conn.executescript(_SCHEMA)
        conn.commit()

    def put(self, record: dict) -> None:
        vid = record["validation_id"]
        result = record.get("result", {})
        conn = self._conn()
        conn.execute(
            "INSERT OR REPLACE INTO validations "
            "(validation_id, tx_ref, signer, verdict, n_violations, created_at, record) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                vid,
                record.get("tx_ref", ""),
                record.get("signer"),
                result.get("verdict", "UNKNOWN"),
                len(result.get("violations", [])),
                record.get("created_at", ""),
                json.dumps(record, ensure_ascii=False),
            ),
        )
        conn.commit()

    def get(self, validation_id: str) -> Optional[dict]:
        row = self._conn().execute(
            "SELECT record FROM validations WHERE validation_id = ?",
            (validation_id,),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def list(self) -> list[dict]:
        rows = self._conn().execute(
            "SELECT record FROM validations ORDER BY created_at DESC"
        ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def query(
        self,
        signer: Optional[str] = None,
        verdict: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        clauses: list[str] = []
        params: list = []
        if signer:
            clauses.append("signer = ?")
            params.append(signer)
        if verdict:
            clauses.append("verdict = ?")
            params.append(verdict)
        if since:
            clauses.append("created_at >= ?")
            params.append(since)
        if until:
            clauses.append("created_at <= ?")
            params.append(until)
        where = " AND ".join(clauses) if clauses else "1=1"
        rows = self._conn().execute(
            f"SELECT record FROM validations WHERE {where} "
            f"ORDER BY created_at DESC LIMIT ?",
            params + [limit],
        ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def count(
        self,
        signer: Optional[str] = None,
    ) -> dict:
        clauses: list[str] = []
        params: list = []
        if signer:
            clauses.append("signer = ?")
            params.append(signer)
        where = " AND ".join(clauses) if clauses else "1=1"
        rows = self._conn().execute(
            f"SELECT verdict, COUNT(*) FROM validations WHERE {where} GROUP BY verdict",
            params,
        ).fetchall()
        counts = {row[0]: row[1] for row in rows}
        return {
            "total": sum(counts.values()),
            "pass": counts.get("PASS", 0),
            "fail": counts.get("FAIL", 0),
        }
