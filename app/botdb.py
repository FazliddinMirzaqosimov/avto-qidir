#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Storage for the multi-user bot: subscribers, their brand subscriptions, the listing
catalogue and per-user delivery history.

The poller thread and the scanner thread both touch this database, so every call opens
its own short-lived connection in WAL mode rather than sharing one across threads.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

TASHKENT_TZ = timezone(timedelta(hours=5))

DATA_DIR = os.environ.get("EV_HUNTER_DATA_DIR") or os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(DATA_DIR, "ev_hunter.db")

# SQLite handles concurrent readers fine in WAL, but two writers still collide; this
# lock keeps the two threads in this process from ever trying at the same moment.
_WRITE_LOCK = threading.Lock()


def now_iso() -> str:
    return datetime.now(TASHKENT_TZ).isoformat()


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_id         INTEGER PRIMARY KEY,
    username      TEXT,
    first_name    TEXT,
    last_name     TEXT,
    phone         TEXT,
    language_code TEXT,
    is_premium    INTEGER DEFAULT 0,
    is_admin      INTEGER DEFAULT 0,
    blocked       INTEGER DEFAULT 0,
    state         TEXT DEFAULT 'new',
    joined_at     TEXT,
    last_seen     TEXT
);

CREATE TABLE IF NOT EXISTS user_brands (
    tg_id INTEGER NOT NULL,
    brand TEXT NOT NULL,
    PRIMARY KEY (tg_id, brand)
);

CREATE TABLE IF NOT EXISTS listings (
    key        TEXT PRIMARY KEY,
    source     TEXT,
    ad_id      TEXT,
    url        TEXT,
    title      TEXT,
    price_usd  INTEGER,
    year       INTEGER,
    mileage_km INTEGER,
    city       TEXT,
    fuel       TEXT,
    owners     INTEGER,
    brand      TEXT,
    tier       TEXT,
    posted_at  TEXT,
    first_seen TEXT
);

CREATE TABLE IF NOT EXISTS user_sent (
    tg_id       INTEGER NOT NULL,
    listing_key TEXT NOT NULL,
    sent_at     TEXT,
    PRIMARY KEY (tg_id, listing_key)
);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE INDEX IF NOT EXISTS idx_listings_brand ON listings(brand);
CREATE INDEX IF NOT EXISTS idx_listings_seen  ON listings(first_seen);
CREATE INDEX IF NOT EXISTS idx_user_sent_user ON user_sent(tg_id);
"""


def init(admin_id: int | None = None) -> None:
    with _WRITE_LOCK:
        conn = connect()
        try:
            conn.executescript(SCHEMA)
            # The single-chat version kept a `seen` table. Carry those ad keys over so the
            # admin is not re-sent 200+ listings they already received.
            has_seen = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='seen'").fetchone()
            migrated = conn.execute(
                "SELECT value FROM meta WHERE key='seen_migrated'").fetchone()
            if has_seen and not migrated:
                rows = conn.execute(
                    "SELECT key, source, ad_id, url, title, price_usd, first_seen, posted_at "
                    "FROM seen").fetchall()
                for r in rows:
                    conn.execute(
                        "INSERT OR IGNORE INTO listings"
                        "(key,source,ad_id,url,title,price_usd,posted_at,first_seen) "
                        "VALUES(?,?,?,?,?,?,?,?)",
                        (r["key"], r["source"], r["ad_id"], r["url"], r["title"],
                         r["price_usd"], r["posted_at"], r["first_seen"]))
                    if admin_id:
                        conn.execute(
                            "INSERT OR IGNORE INTO user_sent(tg_id,listing_key,sent_at) "
                            "VALUES(?,?,?)", (admin_id, r["key"], r["first_seen"]))
                conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('seen_migrated',?)",
                             (str(len(rows)),))
            conn.commit()
        finally:
            conn.close()


# ---------------------------------------------------------------------------- meta ---

def get_meta(key: str, default=None):
    conn = connect()
    try:
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default
    finally:
        conn.close()


def set_meta(key: str, value) -> None:
    with _WRITE_LOCK:
        conn = connect()
        try:
            conn.execute("INSERT INTO meta(key,value) VALUES(?,?) "
                         "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                         (key, str(value)))
            conn.commit()
        finally:
            conn.close()


# --------------------------------------------------------------------------- users ---

def upsert_user(tg_user: dict, is_admin: bool = False) -> dict:
    """Insert or refresh a Telegram user. Returns the stored row and whether it is new."""
    tg_id = tg_user.get("id")
    with _WRITE_LOCK:
        conn = connect()
        try:
            existing = conn.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,)).fetchone()
            if existing is None:
                conn.execute(
                    "INSERT INTO users(tg_id,username,first_name,last_name,language_code,"
                    "is_premium,is_admin,blocked,state,joined_at,last_seen) "
                    "VALUES(?,?,?,?,?,?,?,0,'new',?,?)",
                    (tg_id, tg_user.get("username"), tg_user.get("first_name"),
                     tg_user.get("last_name"), tg_user.get("language_code"),
                     1 if tg_user.get("is_premium") else 0, 1 if is_admin else 0,
                     now_iso(), now_iso()))
            else:
                conn.execute(
                    "UPDATE users SET username=?,first_name=?,last_name=?,language_code=?,"
                    "is_premium=?,last_seen=? WHERE tg_id=?",
                    (tg_user.get("username"), tg_user.get("first_name"),
                     tg_user.get("last_name"), tg_user.get("language_code"),
                     1 if tg_user.get("is_premium") else 0, now_iso(), tg_id))
            conn.commit()
            row = conn.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,)).fetchone()
            return {"user": dict(row), "is_new": existing is None}
        finally:
            conn.close()


def get_user(tg_id: int) -> dict | None:
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def set_user_field(tg_id: int, field: str, value) -> None:
    if field not in ("phone", "state", "blocked", "is_admin", "last_seen"):
        raise ValueError(f"refusing to update unknown column {field!r}")
    with _WRITE_LOCK:
        conn = connect()
        try:
            conn.execute(f"UPDATE users SET {field}=? WHERE tg_id=?", (value, tg_id))
            conn.commit()
        finally:
            conn.close()


def active_users() -> list[dict]:
    """Registered, not blocked, and past the phone-sharing step."""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT * FROM users WHERE blocked=0 AND state='active'").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def all_users() -> list[dict]:
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM users ORDER BY joined_at DESC").fetchall()]
    finally:
        conn.close()


# ---------------------------------------------------------------------- user brands ---

def get_brands(tg_id: int) -> set[str]:
    conn = connect()
    try:
        return {r["brand"] for r in conn.execute(
            "SELECT brand FROM user_brands WHERE tg_id=?", (tg_id,)).fetchall()}
    finally:
        conn.close()


def toggle_brand(tg_id: int, brand: str) -> bool:
    """Add or remove one brand. Returns True if it is now selected."""
    with _WRITE_LOCK:
        conn = connect()
        try:
            hit = conn.execute("SELECT 1 FROM user_brands WHERE tg_id=? AND brand=?",
                               (tg_id, brand)).fetchone()
            if hit:
                conn.execute("DELETE FROM user_brands WHERE tg_id=? AND brand=?",
                             (tg_id, brand))
                selected = False
            else:
                conn.execute("INSERT OR IGNORE INTO user_brands(tg_id,brand) VALUES(?,?)",
                             (tg_id, brand))
                selected = True
            conn.commit()
            return selected
        finally:
            conn.close()


def set_brands(tg_id: int, brands: list[str]) -> None:
    with _WRITE_LOCK:
        conn = connect()
        try:
            conn.execute("DELETE FROM user_brands WHERE tg_id=?", (tg_id,))
            conn.executemany("INSERT OR IGNORE INTO user_brands(tg_id,brand) VALUES(?,?)",
                             [(tg_id, b) for b in brands])
            conn.commit()
        finally:
            conn.close()


# ------------------------------------------------------------------------ listings ---

def upsert_listing(listing, brand: str | None, tier: str) -> bool:
    """Store a matched listing. Returns True if it was not in the catalogue before."""
    with _WRITE_LOCK:
        conn = connect()
        try:
            exists = conn.execute("SELECT 1 FROM listings WHERE key=?",
                                  (listing.key,)).fetchone()
            conn.execute(
                "INSERT OR IGNORE INTO listings(key,source,ad_id,url,title,price_usd,year,"
                "mileage_km,city,fuel,owners,brand,tier,posted_at,first_seen) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (listing.key, listing.source, listing.ad_id, listing.url, listing.title,
                 listing.price_usd, listing.year, listing.mileage_km, listing.city,
                 listing.fuel, listing.owners, brand, tier,
                 listing.posted_at.isoformat() if listing.posted_at else None, now_iso()))

            # Rows carried over from the old single-chat `seen` table have no brand, year
            # or mileage. Without this backfill they can never satisfy a brand filter, so
            # a subscriber would see an empty feed until brand-new ads appeared.
            # COALESCE keeps whatever is already there and only fills the gaps.
            conn.execute(
                "UPDATE listings SET brand=COALESCE(brand,?), tier=COALESCE(tier,?), "
                "year=COALESCE(year,?), mileage_km=COALESCE(mileage_km,?), "
                "city=COALESCE(NULLIF(city,''),?), fuel=COALESCE(NULLIF(fuel,''),?), "
                "owners=COALESCE(owners,?) WHERE key=?",
                (brand, tier, listing.year, listing.mileage_km, listing.city,
                 listing.fuel, listing.owners, listing.key))
            conn.commit()
            return exists is None
        finally:
            conn.close()


def undelivered_for(tg_id: int, brands: set[str] | None, limit: int) -> list[dict]:
    """Newest catalogue entries this user has not been sent yet.

    An empty brand set means "everything" - a user who has not picked yet still gets fed.
    """
    conn = connect()
    try:
        sql = ("SELECT l.* FROM listings l "
               "LEFT JOIN user_sent s ON s.listing_key = l.key AND s.tg_id = ? "
               "WHERE s.listing_key IS NULL ")
        params: list = [tg_id]
        if brands:
            sql += "AND l.brand IN (%s) " % ",".join("?" * len(brands))
            params += sorted(brands)
        sql += "ORDER BY l.first_seen DESC, l.price_usd ASC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def latest_for(tg_id: int, brands: set[str] | None, limit: int) -> list[dict]:
    """Newest catalogue entries regardless of delivery - powers /latest."""
    conn = connect()
    try:
        sql = "SELECT * FROM listings WHERE 1=1 "
        params: list = []
        if brands:
            sql += "AND brand IN (%s) " % ",".join("?" * len(brands))
            params += sorted(brands)
        sql += "ORDER BY first_seen DESC, price_usd ASC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def mark_sent(tg_id: int, keys: list[str]) -> None:
    if not keys:
        return
    with _WRITE_LOCK:
        conn = connect()
        try:
            conn.executemany(
                "INSERT OR IGNORE INTO user_sent(tg_id,listing_key,sent_at) VALUES(?,?,?)",
                [(tg_id, k, now_iso()) for k in keys])
            conn.commit()
        finally:
            conn.close()


def stats() -> dict:
    conn = connect()
    try:
        one = lambda q: conn.execute(q).fetchone()[0]  # noqa: E731
        return {
            "users": one("SELECT COUNT(*) FROM users"),
            "active": one("SELECT COUNT(*) FROM users WHERE blocked=0 AND state='active'"),
            "blocked": one("SELECT COUNT(*) FROM users WHERE blocked=1"),
            "listings": one("SELECT COUNT(*) FROM listings"),
            "deliveries": one("SELECT COUNT(*) FROM user_sent"),
        }
    finally:
        conn.close()
