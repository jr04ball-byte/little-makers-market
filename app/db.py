"""SQLite storage. One file, no server: easy for judges to run."""
from __future__ import annotations

import json
import secrets
import sqlite3
import time
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS shops (
  id TEXT PRIMARY KEY, slug TEXT UNIQUE, kind TEXT NOT NULL DEFAULT 'family',   -- family | fundraiser
  name TEXT NOT NULL, owner_name TEXT, owner_email TEXT, blurb TEXT,
  cause_name TEXT, cause_email TEXT, cause_pct INTEGER DEFAULT 0, goal_cents INTEGER DEFAULT 0,
  club_plan_id TEXT, club_cents INTEGER DEFAULT 900, created REAL
);
CREATE TABLE IF NOT EXISTS makers (
  id TEXT PRIMARY KEY, shop_id TEXT NOT NULL, nickname TEXT NOT NULL, age INTEGER, emoji TEXT,
  family_name TEXT, payout_email TEXT,
  goal_name TEXT, goal_cents INTEGER DEFAULT 0,
  save_pct INTEGER DEFAULT 50, spend_pct INTEGER DEFAULT 30, give_pct INTEGER DEFAULT 20, created REAL
);
CREATE TABLE IF NOT EXISTS creations (
  id TEXT PRIMARY KEY, shop_id TEXT NOT NULL, maker_id TEXT NOT NULL, status TEXT DEFAULT 'draft',
  character_name TEXT, kind TEXT, title TEXT, story TEXT, quirks TEXT, analysis TEXT, answers TEXT,
  drawing TEXT, cutout TEXT, model TEXT, stl TEXT, sticker TEXT, print TEXT, created REAL
);
CREATE TABLE IF NOT EXISTS products (
  id TEXT PRIMARY KEY, creation_id TEXT NOT NULL, kind TEXT NOT NULL, name TEXT, description TEXT,
  price_cents INTEGER NOT NULL, physical INTEGER DEFAULT 0, active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS orders (
  id TEXT PRIMARY KEY, paypal_order_id TEXT UNIQUE, shop_id TEXT, items TEXT, total_cents INTEGER,
  status TEXT, buyer_name TEXT, buyer_email TEXT, capture_id TEXT, channel TEXT DEFAULT 'web',
  agent_name TEXT, message TEXT, created REAL, captured REAL
);
CREATE TABLE IF NOT EXISTS ledger (
  id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT, shop_id TEXT, maker_id TEXT,
  bucket TEXT, cents INTEGER, note TEXT, created REAL      -- bucket: save | spend | give | cause | refund
);
CREATE TABLE IF NOT EXISTS subscriptions (
  id TEXT PRIMARY KEY, shop_id TEXT, paypal_subscription_id TEXT UNIQUE, subscriber_name TEXT,
  status TEXT, created REAL
);
CREATE TABLE IF NOT EXISTS payouts (
  id TEXT PRIMARY KEY, shop_id TEXT, paypal_batch_id TEXT, items TEXT, status TEXT, total_cents INTEGER, created REAL
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, shop_id TEXT, kind TEXT, text TEXT, data TEXT, created REAL
);
"""


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(8).replace('-', 'x').replace('_', 'y')}"


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(config.DB_PATH, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


@contextmanager
def tx():
    con = connect()
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init() -> None:
    with tx() as con:
        con.executescript(SCHEMA)


def rows(sql: str, *args) -> list[dict]:
    with tx() as con:
        return [dict(r) for r in con.execute(sql, args).fetchall()]


def row(sql: str, *args) -> dict | None:
    r = rows(sql, *args)
    return r[0] if r else None


def insert(table: str, data: dict) -> dict:
    data = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in data.items()}
    cols = ", ".join(data)
    marks = ", ".join("?" for _ in data)
    with tx() as con:
        con.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(data.values()))
    return data


def update(table: str, key: str, data: dict) -> None:
    data = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in data.items()}
    sets = ", ".join(f"{k} = ?" for k in data)
    with tx() as con:
        con.execute(f"UPDATE {table} SET {sets} WHERE id = ?", (*data.values(), key))


def log_event(shop_id: str | None, kind: str, text: str, data: dict | None = None) -> None:
    insert("events", {"shop_id": shop_id, "kind": kind, "text": text, "data": data or {}, "created": time.time()})


def loads(v, default=None):
    if v in (None, ""):
        return default
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return default
