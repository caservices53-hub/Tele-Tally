from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS companies (
  company TEXT PRIMARY KEY,
  studied_from TEXT,
  studied_to TEXT,
  ledger_snapshot_json TEXT NOT NULL DEFAULT '[]',
  stock_snapshot_json TEXT NOT NULL DEFAULT '[]',
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company TEXT NOT NULL,
  pattern TEXT NOT NULL,
  voucher_type TEXT NOT NULL,
  party_ledger TEXT NOT NULL DEFAULT '',
  bank_ledger TEXT NOT NULL DEFAULT '',
  template_json TEXT NOT NULL,
  template_hash TEXT NOT NULL,
  source TEXT NOT NULL,
  confidence REAL NOT NULL,
  occurrences INTEGER NOT NULL DEFAULT 1,
  verified INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  UNIQUE(company, pattern, voucher_type, template_hash)
);

CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  company TEXT NOT NULL,
  source_name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  status TEXT NOT NULL,
  approved INTEGER NOT NULL DEFAULT 0,
  note TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS job_rows (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  source_row INTEGER NOT NULL,
  raw_json TEXT NOT NULL,
  voucher_json TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0,
  reason TEXT NOT NULL DEFAULT '',
  fingerprint TEXT NOT NULL DEFAULT '',
  tally_result TEXT NOT NULL DEFAULT '',
  UNIQUE(job_id, source_row)
);

CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  company TEXT NOT NULL,
  job_id TEXT NOT NULL,
  row_id INTEGER,
  action TEXT NOT NULL,
  detail_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_rules_lookup ON rules(company, pattern, voucher_type);
CREATE INDEX IF NOT EXISTS ix_job_rows_status ON job_rows(job_id, status);
"""


class Database:
    def __init__(self, path: str):
        self.path = str(Path(path).expanduser().resolve())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def save_company_snapshot(self, company: str, ledgers: list[str], stocks: list[str], from_date: str = "", to_date: str = "") -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as c:
            c.execute(
                """INSERT INTO companies(company,studied_from,studied_to,ledger_snapshot_json,stock_snapshot_json,updated_at)
                VALUES(?,?,?,?,?,?) ON CONFLICT(company) DO UPDATE SET studied_from=excluded.studied_from,
                studied_to=excluded.studied_to,ledger_snapshot_json=excluded.ledger_snapshot_json,
                stock_snapshot_json=excluded.stock_snapshot_json,updated_at=excluded.updated_at""",
                (company, from_date, to_date, json.dumps(ledgers), json.dumps(stocks), now),
            )

    def company_snapshot(self, company: str) -> dict:
        with self.connect() as c:
            r = c.execute("SELECT * FROM companies WHERE company=?", (company,)).fetchone()
        if not r:
            return {"ledgers": [], "stocks": []}
        return {"ledgers": json.loads(r["ledger_snapshot_json"]), "stocks": json.loads(r["stock_snapshot_json"]),
                "studied_from": r["studied_from"], "studied_to": r["studied_to"]}

    def create_job(self, company: str, source_name: str, note: str = "") -> str:
        jid = uuid.uuid4().hex[:12]
        with self.connect() as c:
            c.execute("INSERT INTO jobs(id,company,source_name,created_at,status,note) VALUES(?,?,?,?,?,?)",
                      (jid, company, source_name, datetime.now().isoformat(timespec="seconds"), "draft", note))
        return jid

    def add_job_row(self, job_id: str, source_row: int, raw: dict, voucher: dict | None, status: str, confidence: float, reason: str, fingerprint: str = "") -> int:
        with self.connect() as c:
            cur = c.execute("""INSERT INTO job_rows(job_id,source_row,raw_json,voucher_json,status,confidence,reason,fingerprint)
                             VALUES(?,?,?,?,?,?,?,?)""",
                            (job_id, source_row, json.dumps(raw, ensure_ascii=False), json.dumps(voucher or {}, ensure_ascii=False), status, confidence, reason, fingerprint))
            return int(cur.lastrowid)

    def job(self, job_id: str):
        with self.connect() as c:
            return c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()

    def rows(self, job_id: str, statuses: tuple[str, ...] | None = None):
        with self.connect() as c:
            if statuses:
                q = ",".join("?" for _ in statuses)
                return c.execute(f"SELECT * FROM job_rows WHERE job_id=? AND status IN ({q}) ORDER BY source_row", (job_id, *statuses)).fetchall()
            return c.execute("SELECT * FROM job_rows WHERE job_id=? ORDER BY source_row", (job_id,)).fetchall()

    def update_row(self, row_id: int, **fields) -> None:
        allowed = {"voucher_json", "status", "confidence", "reason", "fingerprint", "tally_result"}
        fields = {k: v for k, v in fields.items() if k in allowed}
        if not fields:
            return
        cols = ",".join(f"{k}=?" for k in fields)
        vals = list(fields.values()) + [row_id]
        with self.connect() as c:
            c.execute(f"UPDATE job_rows SET {cols} WHERE id=?", vals)

    def set_job(self, job_id: str, status: str | None = None, approved: bool | None = None) -> None:
        parts=[]; vals=[]
        if status is not None: parts.append("status=?"); vals.append(status)
        if approved is not None: parts.append("approved=?"); vals.append(1 if approved else 0)
        if not parts: return
        vals.append(job_id)
        with self.connect() as c:
            c.execute(f"UPDATE jobs SET {','.join(parts)} WHERE id=?", vals)

    def audit(self, company: str, job_id: str, action: str, detail: dict, row_id: int | None = None) -> None:
        with self.connect() as c:
            c.execute("INSERT INTO audit(ts,company,job_id,row_id,action,detail_json) VALUES(?,?,?,?,?,?)",
                      (datetime.now().isoformat(timespec="seconds"), company, job_id, row_id, action, json.dumps(detail, ensure_ascii=False)))
