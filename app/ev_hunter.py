#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EV Hunter — hourly electric-vehicle deal scanner for Uzbek marketplaces.

Scans olx.uz, avtoelon.uz, avtobozor.uz, uzumavto.uz, mashina.uz and avto.uz for
electric / plug-in-hybrid cars matching your criteria and pushes new finds to
Telegram. Never sends the same ad twice.

Zero third-party dependencies — Python 3.8+ standard library only.

Usage
-----
  python ev_hunter.py                 # one scan, send new finds to Telegram
  python ev_hunter.py --loop          # run forever, scan once per hour
  python ev_hunter.py --dry-run       # scan + print, send nothing to Telegram
  python ev_hunter.py --diag          # save raw responses to debug/ for parser fixes
  python ev_hunter.py --test-telegram # send a test message and exit
  python ev_hunter.py --backfill 7    # force a N-day lookback on this run
  python ev_hunter.py --reset         # forget all seen ads and the last-run time
  python ev_hunter.py --stats         # show database stats and exit
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback
import unicodedata

import carfilters
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

APP_DIR = os.path.dirname(os.path.abspath(__file__))

# Everything that survives a redeploy — config, the seen-ads database, logs — lives in
# DATA_DIR. In Docker that is a mounted volume; running bare it defaults to the code
# directory, so local behaviour is unchanged.
DATA_DIR = os.environ.get("EV_HUNTER_DATA_DIR") or APP_DIR

CONFIG_PATH = os.environ.get("EV_HUNTER_CONFIG") or os.path.join(DATA_DIR, "config.json")
DB_PATH = os.path.join(DATA_DIR, "ev_hunter.db")
LOG_PATH = os.path.join(DATA_DIR, "ev_hunter.log")
DEBUG_DIR = os.path.join(DATA_DIR, "debug")

TASHKENT_TZ = timezone(timedelta(hours=5))  # Asia/Tashkent, no DST

# --------------------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------------------

_VERBOSE = True


def log(msg: str, level: str = "INFO") -> None:
    stamp = datetime.now(TASHKENT_TZ).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {level:<5} {msg}"
    if _VERBOSE or level != "DEBUG":
        try:
            print(line, flush=True)
        except UnicodeEncodeError:  # ancient Windows consoles
            print(line.encode("ascii", "replace").decode("ascii"), flush=True)
    try:
        with io.open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


# --------------------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "telegram": {"bot_token": "", "chat_id": "", "admin_chat_id": ""},
    "filters": {
        "max_price_usd": 15000,
        "min_year": 2005,
        "ideal_max_mileage_km": 50000,
        "hard_max_mileage_km": 1000000,
        "regions": ["tashkent", "toshkent", "ташкент", "тошкент"],
        "first_run_backfill_days": 7,
        "max_owners": 0,
        # Only things that are not a car you could drive. Small EVs — Seagull, Mini EV
        # and friends — are wanted, so they are deliberately absent from this list.
        # Changan Ben Ben / Benni / E-Star is excluded by request.
        "exclude_keywords": [
            "ben ben", "benben", "ben-ben", "benni", "бен бен", "бенбен", "бенни",
            "e-star", "estar", "е-стар",
            "гольф кар", "golf car", "elektro skuter", "скутер", "самокат",
            "мопед", "мотоцикл", "velosiped", "велосипед", "квадроцикл",
            "трицикл", "carbike",
        ],
    },
    "sources": {
        "olx": True,
        "avtoelon": True,
        "avtobozor": True,
        "uzumavto": True,
        "mashina": True,
        "avtouz": True,
    },
    "runtime": {
        "interval_minutes": 60,
        "request_timeout_seconds": 25,
        "max_items_per_message": 8,
        "usd_uzs_fallback_rate": 12800,
        "notify_on_source_failure": True,
        "catch_up_overlap_minutes": 120,
        "max_new_per_user_per_cycle": 10,
    },
}


def deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def apply_env_overrides(cfg: dict) -> dict:
    """Environment wins over config.json.

    Keeps the Telegram credentials out of the repository: on the server they come from
    the .env file that docker compose injects, and config.json ships with them blank.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if token:
        cfg["telegram"]["bot_token"] = token.strip()
    if chat_id:
        cfg["telegram"]["chat_id"] = chat_id.strip()

    admin = os.environ.get("ADMIN_CHAT_ID") or os.environ.get("TELEGRAM_ADMIN_ID")
    if admin:
        cfg["telegram"]["admin_chat_id"] = admin.strip()

    interval = os.environ.get("EV_HUNTER_INTERVAL_MINUTES")
    if interval and interval.strip().isdigit():
        cfg["runtime"]["interval_minutes"] = int(interval.strip())
    return cfg


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        try:
            os.makedirs(os.path.dirname(CONFIG_PATH) or ".", exist_ok=True)
            with io.open(CONFIG_PATH, "w", encoding="utf-8") as fh:
                json.dump(DEFAULT_CONFIG, fh, indent=2, ensure_ascii=False)
            log(f"Created a fresh config file at {CONFIG_PATH} — fill in your Telegram details.",
                "WARN")
        except OSError as exc:
            log(f"Could not write a default config to {CONFIG_PATH}: {exc}", "WARN")
        return apply_env_overrides(deep_merge(DEFAULT_CONFIG, {}))
    with io.open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        user_cfg = json.load(fh)
    return apply_env_overrides(deep_merge(DEFAULT_CONFIG, user_cfg))


# --------------------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------------------

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.4 Safari/605.1.15",
]

_DIAG = False
_DEBUG_SEQ = 0


def _charset_of(ctype: str) -> str:
    match = re.search(r"charset=([\w\-]+)", ctype or "", re.I)
    return match.group(1) if match else "utf-8"


def _decode(raw: bytes, ctype: str) -> str:
    try:
        return raw.decode(_charset_of(ctype), errors="replace")
    except LookupError:            # server named a charset Python doesn't know
        return raw.decode("utf-8", errors="replace")


def _decode_body(resp, raw: bytes) -> str:
    encoding = (resp.headers.get("Content-Encoding") or "").lower()
    if "gzip" in encoding:
        try:
            raw = gzip.decompress(raw)
        except OSError:
            pass
    elif "deflate" in encoding:
        try:
            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
        except zlib.error:
            pass
    return _decode(raw, resp.headers.get("Content-Type") or "")


# OLX sits behind a CloudFront WAF that rejects HTTP/1.1 outright — every request gets a
# 403 "Request blocked". Python's urllib speaks HTTP/1.1 only and can never satisfy it, so
# when curl is present we prefer it and ask for HTTP/2. Neither transport works everywhere
# (some hosts answer urllib but block curl), hence http_get tries both before giving up.
CURL_BIN = shutil.which("curl")


def _fetch_curl(url: str, timeout: int, headers: dict) -> tuple[int | None, str | None, str]:
    """Returns (status_code, body_text, error). status_code is None if curl never replied."""
    if not CURL_BIN:
        return None, None, "curl not installed"

    body_fd, body_path = tempfile.mkstemp(prefix="evh_body_")
    head_fd, head_path = tempfile.mkstemp(prefix="evh_head_")
    os.close(body_fd)
    os.close(head_fd)

    cmd = [CURL_BIN, "-sS", "--compressed", "--http2", "--location", "--max-redirs", "5",
           "--connect-timeout", str(max(5, min(20, timeout))), "--max-time", str(timeout),
           "-o", body_path, "-D", head_path, "-w", "%{http_code}"]
    for key, value in headers.items():
        # --compressed manages Accept-Encoding itself; a manual one breaks decompression.
        if key.lower() == "accept-encoding":
            continue
        cmd += ["-H", f"{key}: {value}"]
    cmd.append(url)

    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout + 20)
        status = int((proc.stdout or b"").decode("ascii", "replace").strip() or 0) or None
        with io.open(body_path, "rb") as fh:
            raw = fh.read()
        with io.open(head_path, "r", encoding="utf-8", errors="replace") as fh:
            head = fh.read()
        ctype = ""
        for line in head.splitlines():
            if line.lower().startswith("content-type:"):
                ctype = line.split(":", 1)[1].strip()
        if status is None:
            detail = (proc.stderr or b"").decode("utf-8", "replace").strip()[:120]
            return None, None, f"curl exit {proc.returncode}: {detail}"
        return status, _decode(raw, ctype), ""
    except (subprocess.TimeoutExpired, OSError, ValueError) as exc:
        return None, None, f"curl {type(exc).__name__}: {exc}"
    finally:
        for path in (body_path, head_path):
            try:
                os.unlink(path)
            except OSError:
                pass


def _fetch_urllib(url: str, timeout: int, headers: dict) -> tuple[int | None, str | None, str]:
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, _decode_body(resp, resp.read()), ""
    except urllib.error.HTTPError as exc:
        try:
            body = _decode_body(exc, exc.read())
        except Exception:  # noqa: BLE001
            body = ""
        return exc.code, body, ""
    except Exception as exc:  # noqa: BLE001 - network layer, anything can happen
        return None, None, f"{type(exc).__name__}: {exc}"


def http_get(url: str, timeout: int = 25, referer: str = None, extra_headers: dict = None,
             tag: str = "") -> str | None:
    """GET a URL with browser-ish headers. Returns body text, or None on failure."""
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,uz;q=0.8,en-US;q=0.7,en;q=0.6",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "close",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
    }
    if referer:
        headers["Referer"] = referer
        headers["Sec-Fetch-Site"] = "same-origin"
    if extra_headers:
        headers.update(extra_headers)

    transports = [("curl", _fetch_curl)] if CURL_BIN else []
    transports.append(("urllib", _fetch_urllib))

    last_error = None
    for attempt in range(3):
        for name, fetch in transports:
            status, body, error = fetch(url, timeout, headers)

            if status == 200 and body is not None:
                if _DIAG and tag:
                    save_debug(tag, url, body)
                return body

            if status is None:
                last_error = f"{error} [{name}]"
                continue

            last_error = f"HTTP {status} [{name}]"
            if _DIAG and tag:
                save_debug(f"{tag}_error{status}", url, body or "")
            # The page is genuinely gone — no transport or retry will conjure it up.
            if status in (404, 410, 451):
                log(f"  fetch failed ({last_error}): {url}", "DEBUG")
                return None
        if attempt < 2:
            # Jitter, so a blocked run doesn't retry in a machine-gun rhythm.
            time.sleep(1.5 * (attempt + 1) + random.uniform(0, 0.8))

    log(f"  fetch failed ({last_error}): {url}", "DEBUG")
    return None


def http_get_json(url: str, timeout: int = 25, referer: str = None, tag: str = ""):
    body = http_get(
        url, timeout=timeout, referer=referer, tag=tag,
        extra_headers={"Accept": "application/json, text/plain, */*",
                       "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors",
                       "X-Requested-With": "XMLHttpRequest"},
    )
    if not body:
        return None
    try:
        return json.loads(body)
    except (ValueError, TypeError):
        return None


def save_debug(tag: str, url: str, body: str) -> None:
    try:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        global _DEBUG_SEQ
        _DEBUG_SEQ += 1
        safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", tag)[:60]
        stamp = datetime.now(TASHKENT_TZ).strftime("%H%M%S")
        path = os.path.join(DEBUG_DIR, f"{safe}_{stamp}_{_DEBUG_SEQ:03d}.txt")
        with io.open(path, "w", encoding="utf-8") as fh:
            fh.write(f"URL: {url}\n{'=' * 80}\n")
            fh.write(body[:1_500_000])
        log(f"  diag saved -> {os.path.basename(path)}", "DEBUG")
    except OSError:
        pass


# --------------------------------------------------------------------------------------
# Text / value parsing helpers
# --------------------------------------------------------------------------------------

def norm(text) -> str:
    """Lowercase, strip accents, collapse whitespace. Safe on None."""
    if text is None:
        return ""
    text = str(text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip().lower()


def strip_tags(html: str) -> str:
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
            .replace("&quot;", '"').replace("&#039;", "'")
            .replace("&lt;", "<").replace("&gt;", ">"))
    return re.sub(r"\s+", " ", text).strip()


def to_int(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    digits = re.sub(r"[^\d]", "", str(value))
    return int(digits) if digits else None


def parse_year(text) -> int | None:
    value = to_int(text)
    if value and 1980 <= value <= datetime.now().year + 1:
        return value
    match = re.search(r"\b(19[89]\d|20[0-4]\d)\b", str(text or ""))
    return int(match.group(1)) if match else None


MILEAGE_RE = re.compile(
    r"(\d[\d\s.,\u00a0]{0,12})\s*(km|км|kм|k m|ming km|тыс\.?\s*км|тыс км|mln km)",
    re.I,
)


def _disambiguate_mileage(number: int | None) -> int | None:
    """A used-car ad showing '45' means 45 000 km; '12' really can mean a new car.

    Anything between 31 and 999 is treated as thousands — no real used listing sits
    in that range, while values up to 30 km are plausible for a brand-new car.
    """
    if number is None:
        return None
    if 30 < number < 1000:
        return number * 1000
    return number if 0 <= number <= 1_500_000 else None


def parse_mileage_km(text) -> int | None:
    """Understands '45 000 км', '45,000 km', '45 тыс. км', bare integers."""
    if text is None:
        return None
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return _disambiguate_mileage(int(text))
    raw = str(text)
    match = MILEAGE_RE.search(raw)
    if match:
        number = to_int(match.group(1))
        unit = norm(match.group(2))
        if number is None:
            return None
        if "тыс" in unit or unit.startswith("ming"):
            number *= 1000
        return number
    return _disambiguate_mileage(to_int(raw))


CURRENCY_PATTERNS = [
    (re.compile(r"(?:\$|usd|у\.?е\.?|у\.е)", re.I), "USD"),
    (re.compile(r"(?:so'?m|sum|сум|сўм|uzs)", re.I), "UZS"),
]


def detect_currency(text: str) -> str | None:
    for pattern, code in CURRENCY_PATTERNS:
        if pattern.search(text or ""):
            return code
    return None


def parse_price(text, default_currency: str = None) -> tuple[int | None, str | None]:
    """Return (amount, currency_code) from messy price strings."""
    if text is None:
        return None, None
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return int(text), default_currency
    raw = str(text)
    currency = detect_currency(raw) or default_currency

    # Prefer the number that actually sits next to a currency marker \u2014 listing text
    # like "BYD Yuan Up 2024 13 900 $ 12 000 \u043a\u043c" is full of decoy numbers.
    amount = None
    number_token = r"\d{1,3}(?:[\s\u00a0.,]\d{3})+|\d+"
    currency_token = r"\$|usd|\u0443\.?\s?\u0435\.?|so'?m|sum|\u0441\u0443\u043c|\u0441\u045e\u043c|uzs"
    anchored = (re.search(r"(" + number_token + r")\s*(?:" + currency_token + r")", raw, re.I)
                or re.search(r"(?:\$|usd)\s*(" + number_token + r")", raw, re.I))
    if anchored:
        amount = to_int(anchored.group(1))
    else:
        cleaned = re.sub(r"[^\d\s.,\u00a0]", " ", raw)
        match = re.search(r"\d[\d\s.,\u00a0]*", cleaned)
        if not match:
            return None, currency
        amount = to_int(match.group(0))
    if amount is None:
        return None, currency
    # Heuristic: a huge number without a currency marker is almost certainly so'm.
    if currency is None and amount > 300_000:
        currency = "UZS"
    return amount, currency


def to_usd(amount: int | None, currency: str | None, rate: float) -> int | None:
    if amount is None:
        return None
    if currency == "UZS" or (currency is None and amount > 300_000):
        return int(round(amount / rate))
    return int(amount)


def fmt_money(value: int | None) -> str:
    return f"${value:,}".replace(",", " ") if value is not None else "price on request"


def fmt_km(value: int | None) -> str:
    return f"{value:,} km".replace(",", " ") if value is not None else "mileage n/a"


# --------------------------------------------------------------------------------------
# Date parsing (absolute + relative, ru/uz/en)
# --------------------------------------------------------------------------------------

MONTHS = {
    "jan": 1, "янв": 1, "yan": 1, "feb": 2, "фев": 2, "mar": 3, "мар": 3,
    "apr": 4, "апр": 4, "may": 5, "мая": 5, "май": 5, "jun": 6, "июн": 6, "iyun": 6,
    "jul": 7, "июл": 7, "iyul": 7, "aug": 8, "авг": 8, "avg": 8,
    "sep": 9, "сен": 9, "sen": 9, "oct": 10, "окт": 10, "okt": 10,
    "nov": 11, "ноя": 11, "dec": 12, "дек": 12, "dek": 12,
}


def parse_datetime(value) -> datetime | None:
    """Parse ISO timestamps, epoch seconds/ms, and relative ru/uz phrases."""
    if value is None:
        return None
    now = datetime.now(TASHKENT_TZ)

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value)
        if seconds > 1e11:
            seconds /= 1000.0
        try:
            return datetime.fromtimestamp(seconds, TASHKENT_TZ)
        except (OverflowError, OSError, ValueError):
            return None

    raw = str(value).strip()
    if not raw:
        return None

    iso = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(iso)
        return parsed.astimezone(TASHKENT_TZ) if parsed.tzinfo else parsed.replace(tzinfo=TASHKENT_TZ)
    except ValueError:
        pass

    for pattern in (r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})",
                    r"(\d{2})\.(\d{2})\.(\d{4})[ ,]*(\d{2}):(\d{2})"):
        match = re.search(pattern, raw)
        if match:
            groups = [int(g) for g in match.groups()]
            if pattern.startswith(r"(\d{4})"):
                y, mo, d, h, mi = groups
            else:
                d, mo, y, h, mi = groups
            try:
                return datetime(y, mo, d, h, mi, tzinfo=TASHKENT_TZ)
            except ValueError:
                return None

    low = norm(raw)

    match = re.search(r"(\d+)\s*(min|мин|daqiqa)", low)
    if match:
        return now - timedelta(minutes=int(match.group(1)))
    match = re.search(r"(\d+)\s*(hour|hr|час|соат|soat)", low)
    if match:
        return now - timedelta(hours=int(match.group(1)))
    match = re.search(r"(\d+)\s*(day|дн|ден|кун|kun)", low)
    if match:
        return now - timedelta(days=int(match.group(1)))

    if any(word in low for word in ("сегодня", "bugun", "today")):
        match = re.search(r"(\d{1,2}):(\d{2})", low)
        if match:
            return now.replace(hour=int(match.group(1)), minute=int(match.group(2)),
                               second=0, microsecond=0)
        return now.replace(hour=12, minute=0, second=0, microsecond=0)
    if any(word in low for word in ("вчера", "kecha", "yesterday")):
        base = now - timedelta(days=1)
        match = re.search(r"(\d{1,2}):(\d{2})", low)
        if match:
            return base.replace(hour=int(match.group(1)), minute=int(match.group(2)),
                                second=0, microsecond=0)
        return base.replace(hour=12, minute=0, second=0, microsecond=0)

    match = re.search(r"(\d{1,2})\s+([a-zа-яё]{3,10})\.?\s*(\d{4})?[ ,]*(\d{1,2}):?(\d{2})?", low)
    if match:
        day = int(match.group(1))
        month = None
        token = match.group(2)[:3]
        for key, num in MONTHS.items():
            if token.startswith(key[:3]):
                month = num
                break
        if month:
            year = int(match.group(3)) if match.group(3) else now.year
            hour = int(match.group(4) or 12)
            minute = int(match.group(5) or 0)
            try:
                guess = datetime(year, month, day, hour, minute, tzinfo=TASHKENT_TZ)
                if guess > now + timedelta(days=1):
                    guess = guess.replace(year=year - 1)
                return guess
            except ValueError:
                return None
    return None


# --------------------------------------------------------------------------------------
# Embedded-JSON extractors (Next.js / Nuxt / JSON-LD / generic state blobs)
# --------------------------------------------------------------------------------------

def extract_script_json(html: str, script_id: str) -> dict | None:
    pattern = re.compile(
        r"<script[^>]*id=[\"']" + re.escape(script_id) + r"[\"'][^>]*>(.*?)</script>",
        re.S | re.I,
    )
    match = pattern.search(html or "")
    if not match:
        return None
    try:
        return json.loads(match.group(1).strip())
    except ValueError:
        return None


def extract_assigned_json(html: str, var_names: list[str]) -> dict | None:
    """Pull `window.__X__ = {...};` or `window.__X__ = "escaped json";` blobs."""
    for name in var_names:
        pattern = re.compile(
            re.escape(name) + r"\s*=\s*(\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|\{)",
            re.S,
        )
        match = pattern.search(html or "")
        if not match:
            continue
        head = match.group(1)
        if head in ("{",):
            blob = _balanced_json(html, match.start(1))
            if blob:
                try:
                    return json.loads(blob)
                except ValueError:
                    continue
        else:
            try:
                inner = json.loads(head) if head.startswith('"') else head[1:-1]
                return json.loads(inner)
            except ValueError:
                continue
    return None


def _balanced_json(text: str, start: int) -> str | None:
    depth, in_string, escape = 0, False, False
    for index in range(start, min(len(text), start + 4_000_000)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return None


def extract_json_ld(html: str) -> list:
    blocks = re.findall(
        r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        html or "", re.S | re.I,
    )
    out = []
    for block in blocks:
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        out.extend(data if isinstance(data, list) else [data])
    return out


def walk(obj, want_keys: tuple[str, ...], max_depth: int = 14):
    """Yield every dict nested anywhere in obj that has all of want_keys."""
    stack = [(obj, 0)]
    while stack:
        node, depth = stack.pop()
        if depth > max_depth:
            continue
        if isinstance(node, dict):
            keys = {k.lower() for k in node.keys()}
            if all(k in keys for k in want_keys):
                yield node
            for value in node.values():
                if isinstance(value, (dict, list)):
                    stack.append((value, depth + 1))
        elif isinstance(node, list):
            for value in node:
                if isinstance(value, (dict, list)):
                    stack.append((value, depth + 1))


def dig(node: dict, *names, default=None):
    """Case-insensitive multi-key lookup on a dict."""
    lowered = {str(k).lower(): v for k, v in node.items()}
    for name in names:
        if name.lower() in lowered and lowered[name.lower()] not in (None, "", []):
            return lowered[name.lower()]
    return default


# --------------------------------------------------------------------------------------
# Listing model
# --------------------------------------------------------------------------------------

_URL_RE = re.compile(r"https?://\S+|/[\w./-]{12,}")
_HEXY_RE = re.compile(r"\b(?=[a-z0-9]*\d)(?=[a-z0-9]*[a-f])[a-f0-9]{6,}\b")


def _clean_blob(text: str) -> str:
    """Normalised ad text with URLs and hex/uuid noise removed.

    Image filenames are full of fragments like `...-c11f...` or `...e2a8...`, which
    would otherwise be read as the model names c11 and e2.
    """
    cleaned = _URL_RE.sub(" ", str(text or ""))
    cleaned = norm(cleaned)
    return _HEXY_RE.sub(" ", cleaned)


def _word_re(words) -> "re.Pattern":
    """Match any of `words` as a standalone token, so `e2` never matches inside `e29`."""
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(w) for w in words) + r")(?![a-z0-9])")


class Listing:
    __slots__ = ("source", "ad_id", "url", "title", "price_usd", "price_raw", "year",
                 "mileage_km", "city", "posted_at", "fuel", "owners", "blob")

    def __init__(self, source, ad_id, url, title, **kwargs):
        self.source = source
        self.ad_id = str(ad_id)
        self.url = url
        self.title = (title or "").strip()
        self.price_usd = kwargs.get("price_usd")
        self.price_raw = kwargs.get("price_raw")
        self.year = kwargs.get("year")
        self.mileage_km = kwargs.get("mileage_km")
        self.city = kwargs.get("city") or ""
        self.posted_at = kwargs.get("posted_at")
        self.fuel = kwargs.get("fuel") or ""
        self.owners = kwargs.get("owners")
        self.blob = _clean_blob(" ".join(str(x) for x in [title, kwargs.get("city"),
                                                          kwargs.get("fuel"),
                                                          kwargs.get("raw_text") or ""]))

    @property
    def key(self) -> str:
        return f"{self.source}:{self.ad_id}"

    def __repr__(self) -> str:
        return f"<{self.key} {self.title[:40]!r} {self.price_usd} {self.year} {self.mileage_km}>"


# --------------------------------------------------------------------------------------
# Electric / PHEV recognition
# --------------------------------------------------------------------------------------

EV_FUEL_WORDS = ("electric", "электро", "elektr", "ev", "bev", "電", "elektrik", "toq")
PHEV_WORDS = ("dm-i", "dmi", "dm i", "phev", "plug-in", "plug in", "гибрид", "gibrid",
              "hybrid", "dm-p", "champion edition")

EV_MODEL_WORDS = (
    # BYD
    "byd", "yuan", "dolphin", "atto", "seal", "seagull", "song", "qin", "han", "tang",
    "chazor", "e2", "e3", "e6", "destroyer", "frigate", "sealion", "razor", "yuan up",
    # Leapmotor / Chinese EV brands
    "leapmotor", "leap motor", "c11", "c01", "c10", "t03", "b10", "a12",
    "zeekr", "neta", "nezha", "aion", "hongqi", "avatr", "deepal", "voyah",
    "xpeng", "li auto", "lixiang", "nio", "ora", "geometry", "arcfox", "jac",
    "jetour", "chery", "exeed", "omoda", "jaecoo", "changan", "lumin",
    "wuling", "baojun", "mg4", "mg 4", "roewe", "maxus", "skywell", "livan",
    "dongfeng", "nammi", "forthing", "kaiyi", "bestune", "gac", "trumpchi",
    # global EVs
    "tesla", "model 3", "model y", "ioniq", "kona electric", "niro ev", "ev6", "ev5",
    "leaf", "bolt", "id.4", "id4", "id.6", "id6", "e-tron", "etron", "taycan",
    "i3 ", "i4 ", "ix3", "eqa", "eqb", "eqc", "eqe", "eqs", "polestar", "lucid",
    "bz4x", "solterra", "e-208", "e-2008", "zoe", "spring", "mokka-e",
)

NON_EV_HINTS = ("бензин", "benzin", "petrol", "gasoline", "дизель", "dizel", "diesel",
                "метан", "пропан", "gas ballon", "gaz-ballon")


def classify_powertrain(listing: Listing) -> str | None:
    """Return 'EV', 'PHEV' or None."""
    text = f"{listing.blob} {norm(listing.fuel)}"

    if _word_re(PHEV_WORDS).search(text):
        if any(word in text for word in ("dm-i", "dmi", "dm i", "phev", "plug-in", "plug in", "dm-p")):
            return "PHEV"
        if any(word in text for word in EV_FUEL_WORDS):
            return "PHEV"

    fuel_norm = _clean_blob(listing.fuel)
    if fuel_norm and _word_re(EV_FUEL_WORDS).search(fuel_norm) \
            and not any(word in fuel_norm for word in NON_EV_HINTS):
        return "EV"

    if re.search(r"\b(electric|электро|elektr\w*|elektromobil|электромобиль|токда|"
                 r"full ev|bev|ev)\b", text):
        if not any(word in text for word in NON_EV_HINTS):
            return "EV"

    # Model-name recognition: these nameplates are EV-only in the UZ market.
    ev_only = ("dolphin", "atto 3", "seal", "yuan", "seagull", "e2", "e3", "e6",
               "leapmotor", "t03", "c11", "c01", "c10", "b10", "zeekr", "neta", "nezha",
               "aion", "tesla", "model 3", "model y", "ioniq 5", "ioniq 6", "ev6", "ev5",
               "leaf", "id.4", "id4", "id.6", "id6", "bz4x", "kona electric", "niro ev",
               "e-tron", "etron", "lumin", "nammi", "ora", "mg4", "mg 4")
    if _word_re(ev_only).search(text) and not any(word in text for word in NON_EV_HINTS):
        return "EV"

    if any(word in text for word in ("chazor", "qin plus dm", "song plus dm", "destroyer 05",
                                     "seal 06 dm", "sealion 06")):
        return "PHEV"
    return None


def looks_like_a_car(listing: Listing) -> bool:
    """Filter out scooters, bikes, chargers, parts and other non-car EV listings."""
    text = listing.blob
    junk = ("зарядн", "zaryad", "charger", "аккумулятор", "batareya", "запчаст",
            "ehtiyot qism", "чехол для", "куплю", "sotib olaman")
    if any(word in text for word in junk) and not any(
            word in text for word in ("автомобиль", "avtomobil", "mashina", "car")):
        return False
    return True


# --------------------------------------------------------------------------------------
# Source adapters
# --------------------------------------------------------------------------------------

SEARCH_TERMS = ["byd", "leapmotor", "chazor", "elektromobil", "электромобиль", "tesla", "zeekr"]


class SourceResult:
    def __init__(self, name: str):
        self.name = name
        self.listings: list[Listing] = []
        self.ok = False
        self.note = ""


# ---------------------------------- OLX.uz --------------------------------------------

OLX_API = "https://www.olx.uz/api/v1/offers/"
OLX_CAR_CATEGORY = 108          # parent "Легковые автомобили"; brands sit in child categories
OLX_REGION_TASHKENT = 5
OLX_FUEL_ELECTRIC = "546"       # enum id behind the "Электро" filter
OLX_FUEL_HYBRID = "544"         # "Гибрид" — covers DM-i / PHEV

# Model names worth querying directly: OLX only returns 1000 rows per search, so a
# broad "newest cars" sweep buries electric cars under Nexias and Cobalts.
OLX_QUERY_TERMS = [
    "byd", "byd e2", "yuan", "dolphin", "seagull", "atto", "seal", "song", "qin", "chazor",
    "leapmotor", "zeekr", "neta", "aion", "hongqi", "nammi",
    "geometry", "tesla", "xpeng", "elektromobil", "электромобиль", "elektr",
]


def parse_olx_offer(offer: dict, rate: float) -> Listing | None:
    ad_id = dig(offer, "id")
    url = dig(offer, "url", "link")
    if not ad_id or not url:
        return None

    params = {}
    raw_params = dig(offer, "params", default=[]) or []
    if isinstance(raw_params, list):
        for param in raw_params:
            if not isinstance(param, dict):
                continue
            key = norm(dig(param, "key", "name"))
            value = dig(param, "value")
            if isinstance(value, dict):
                label = dig(value, "label", "key", "value")
                params[key] = label
                if key == "price":
                    params["_price_value"] = dig(value, "value")
                    params["_price_currency"] = dig(value, "currency")
                    params["_price_converted"] = dig(value, "converted_value")
                    params["_price_converted_currency"] = dig(value, "converted_currency")
            else:
                params[key] = value

    amount = params.get("_price_value")
    currency = params.get("_price_currency")
    if params.get("_price_converted") and norm(params.get("_price_converted_currency")) == "usd":
        price_usd = to_int(params["_price_converted"])
        price_raw = f"{amount} {currency}" if amount else None
    else:
        parsed_amount, parsed_currency = parse_price(amount if amount is not None else params.get("price"),
                                                     currency)
        price_usd = to_usd(parsed_amount, parsed_currency, rate)
        price_raw = f"{parsed_amount} {parsed_currency}" if parsed_amount else None

    location = dig(offer, "location", default={}) or {}
    city = ""
    if isinstance(location, dict):
        city_node = dig(location, "city", default={}) or {}
        region_node = dig(location, "region", default={}) or {}
        city = " ".join(filter(None, [
            dig(city_node, "name") if isinstance(city_node, dict) else str(city_node),
            dig(region_node, "name") if isinstance(region_node, dict) else str(region_node),
        ]))

    posted = parse_datetime(dig(offer, "created_time", "created_at", "last_refresh_time",
                                "pushup_time", "valid_to"))

    return Listing(
        "OLX", ad_id, url, dig(offer, "title", "name", default=""),
        price_usd=price_usd, price_raw=price_raw,
        year=parse_year(params.get("motor_year") or params.get("year")),
        mileage_km=parse_mileage_km(params.get("motor_mileage") or params.get("mileage")),
        city=city, posted_at=posted,
        fuel=params.get("fuel_type") or params.get("petrol") or params.get("fuel") or "",
        owners=to_int(params.get("owners") or params.get("owner")),
        raw_text=" ".join(f"{k}={v}" for k, v in params.items() if not k.startswith("_")),
    )


def _olx_collect(params: dict, pages: int, cfg, rate, seen: set, result) -> None:
    """Walk the pages of one OLX query, adding anything new to `result`."""
    timeout = cfg["runtime"]["request_timeout_seconds"]
    for page in range(pages):
        query = dict(params, offset=page * 50, limit=50)
        url = OLX_API + "?" + urllib.parse.urlencode(query)
        data = http_get_json(url, timeout=timeout, referer="https://www.olx.uz/", tag="olx_api")
        rows = data.get("data") if isinstance(data, dict) else None
        if not isinstance(rows, list) or not rows:
            return
        result.ok = True
        for offer in rows:
            if not isinstance(offer, dict):
                continue
            listing = parse_olx_offer(offer, rate)
            if listing and listing.ad_id not in seen:
                seen.add(listing.ad_id)
                result.listings.append(listing)
        if len(rows) < 50:
            return
        time.sleep(0.3)


def fetch_olx(cfg, rate):
    result = SourceResult("OLX")
    seen = set()
    pages = int(cfg["runtime"].get("olx_pages_per_query", 3))
    base = {"category_id": OLX_CAR_CATEGORY, "region_id": OLX_REGION_TASHKENT,
            "sort_by": "created_at:desc"}

    # The fuel filter is rejected on some category levels, so try the variants and
    # keep whichever the API accepts — a failure here costs one request.
    for fuel in (OLX_FUEL_ELECTRIC, OLX_FUEL_HYBRID):
        _olx_collect(dict(base, **{"filter_enum_fuel_type[0]": fuel}), pages, cfg, rate, seen, result)
        _olx_collect({"region_id": OLX_REGION_TASHKENT, "sort_by": "created_at:desc",
                      "filter_enum_fuel_type[0]": fuel}, pages, cfg, rate, seen, result)

    # Newest cars overall, then each electric nameplate by name.
    _olx_collect(base, pages, cfg, rate, seen, result)
    for term in OLX_QUERY_TERMS:
        _olx_collect(dict(base, query=term), 2, cfg, rate, seen, result)
        time.sleep(0.25)

    result.note = f"{len(result.listings)} raw listings"
    return result


# --------------------------- Generic marketplace adapter -------------------------------

class AnchorHarvester(HTMLParser):
    """Collects <a href> elements plus the visible text of their subtree."""

    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.items: list[tuple[str, str]] = []
        self._stack: list[dict] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href") or ""
            self._stack.append({"href": urllib.parse.urljoin(self.base_url, href), "text": []})
        elif self._stack and tag == "img":
            alt = dict(attrs).get("alt")
            if alt:
                self._stack[-1]["text"].append(alt)

    def handle_endtag(self, tag):
        if tag == "a" and self._stack:
            node = self._stack.pop()
            text = re.sub(r"\s+", " ", " ".join(node["text"])).strip()
            if node["href"] and text:
                self.items.append((node["href"], text))

    def handle_data(self, data):
        if self._stack and data.strip():
            self._stack[-1]["text"].append(data.strip())


def listings_from_json_state(html: str, source: str, base_url: str, rate: float) -> list[Listing]:
    """Best-effort: mine any embedded JSON state in an HTML page for ad-shaped objects."""
    states = []
    for candidate in (extract_script_json(html, "__NEXT_DATA__"),
                      extract_script_json(html, "__NUXT_DATA__"),
                      extract_assigned_json(html, ["window.__NUXT__", "window.__INITIAL_STATE__",
                                                   "window.__PRELOADED_STATE__", "window.__DATA__",
                                                   "window.__PRERENDERED_STATE__"])):
        if candidate:
            states.append(candidate)
    for block in extract_json_ld(html):
        states.append(block)
    return listings_from_state_objects(states, source, base_url, rate)


def listings_from_state_objects(states: list, source: str, base_url: str,
                                rate: float) -> list[Listing]:
    """Mine already-parsed JSON (an API response, or a page's state blob) for ads."""
    out: list[Listing] = []
    seen = set()
    for state in states:
        for node in walk(state, ("id",)):
            title = dig(node, "title", "name", "caption", "model_name", "full_name")
            if not title or not isinstance(title, str) or len(title) < 3:
                continue
            price_node = dig(node, "price", "cost", "price_value", "amount")
            if price_node is None and dig(node, "year", "issue_year", "manufacture_year") is None:
                continue
            ad_id = dig(node, "id", "slug", "code")
            url_node = dig(node, "url", "link", "href", "permalink", "slug")
            url = urllib.parse.urljoin(base_url, str(url_node)) if url_node else None
            if not url or not ad_id:
                continue
            if isinstance(price_node, dict):
                amount = dig(price_node, "value", "amount", "price")
                currency = dig(price_node, "currency", "currency_code", "cur")
            else:
                amount, currency = price_node, dig(node, "currency", "currency_code", "cur")
            amount, currency = parse_price(amount, currency if isinstance(currency, str) else None)
            key = f"{ad_id}"
            if key in seen:
                continue
            seen.add(key)
            out.append(Listing(
                source, ad_id, url, str(title),
                price_usd=to_usd(amount, currency, rate),
                price_raw=f"{amount} {currency}" if amount else None,
                year=parse_year(dig(node, "year", "issue_year", "manufacture_year", "car_year")),
                mileage_km=parse_mileage_km(dig(node, "mileage", "run", "probeg", "odometer", "km")),
                city=str(dig(node, "city", "region", "location", "address", default="") or "")[:80],
                posted_at=parse_datetime(dig(node, "created_at", "created_date", "published_at",
                                             "date", "publish_date", "updated_at")),
                fuel=str(dig(node, "fuel", "fuel_type", "engine_type", "motor", default="") or ""),
                owners=to_int(dig(node, "owners", "owners_count", "owner_count")),
                raw_text=json.dumps(node, ensure_ascii=False)[:1200],
            ))
    return out


def listings_from_html_anchors(html: str, source: str, base_url: str, rate: float,
                               link_pattern: re.Pattern) -> list[Listing]:
    harvester = AnchorHarvester(base_url)
    try:
        harvester.feed(html)
    except Exception:  # noqa: BLE001 - malformed markup happens
        return []

    out: list[Listing] = []
    seen = set()
    for href, text in harvester.items:
        if not link_pattern.search(href):
            continue
        if len(text) < 6:
            continue
        ad_id_match = re.search(r"(\d{5,})", href)
        ad_id = ad_id_match.group(1) if ad_id_match else href.rstrip("/").rsplit("/", 1)[-1][:60]
        if ad_id in seen:
            continue
        seen.add(ad_id)
        amount, currency = parse_price(text)
        title = re.split(r"\d[\d\s.,]*\s*(?:\$|у\.е|сум|so'm|usd)", text, 1)[0].strip()
        out.append(Listing(
            source, ad_id, href, title[:120] or text[:120],
            price_usd=to_usd(amount, currency, rate),
            price_raw=f"{amount} {currency}" if amount else None,
            year=parse_year(re.search(r"\b(20[12]\d)\b", text).group(1)
                            if re.search(r"\b(20[12]\d)\b", text) else None),
            mileage_km=parse_mileage_km(text if MILEAGE_RE.search(text) else None),
            city=text, posted_at=parse_datetime(text), fuel=text, raw_text=text,
        ))
    return out


def fetch_generic(name: str, urls: list[str], link_pattern: re.Pattern, cfg: dict,
                  rate: float, json_apis: list[str] = None) -> SourceResult:
    result = SourceResult(name)
    timeout = cfg["runtime"]["request_timeout_seconds"]
    seen = set()

    for api_url in (json_apis or []):
        data = http_get_json(api_url, timeout=timeout, tag=f"{name.lower()}_api")
        if not data:
            continue
        base = "{0.scheme}://{0.netloc}".format(urllib.parse.urlsplit(api_url))
        for listing in listings_from_state_objects([data], name, base, rate):
            if listing.key not in seen:
                seen.add(listing.key)
                result.listings.append(listing)
                result.ok = True

    for url in urls:
        html = http_get(url, timeout=timeout, tag=f"{name.lower()}_html")
        if not html:
            continue
        result.ok = True
        base = "{0.scheme}://{0.netloc}".format(urllib.parse.urlsplit(url))
        found = listings_from_json_state(html, name, base, rate)
        if not found:
            found = listings_from_html_anchors(html, name, base, rate, link_pattern)
        for listing in found:
            if listing.key not in seen:
                seen.add(listing.key)
                result.listings.append(listing)
        time.sleep(0.8)

    result.note = f"{len(result.listings)} raw listings"
    return result


# ------------------------------ Avtoelon.uz -------------------------------------------
# Every advert is emitted as a `listing.items.push({...})` blob next to a
# `<div id="advert-NNN">` card. The blob carries url/price/city/brand/model/timestamp;
# the card's visible text carries year, fuel and mileage.

AVTOELON_ITEM_RE = re.compile(r"listing\.items\.push\((\{.*?\})\)\s*;", re.S)
AVTOELON_CARD_RE = re.compile(r'id="advert-(\d+)"')


def _avtoelon_cards(html: str) -> dict:
    cards, marks = {}, list(AVTOELON_CARD_RE.finditer(html))
    for index, match in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else match.end() + 14000
        cards[match.group(1)] = strip_tags(html[match.end():end])
    return cards


def parse_avtoelon_html(html: str, rate: float) -> list:
    cards = _avtoelon_cards(html)
    out, seen = [], set()
    for match in AVTOELON_ITEM_RE.finditer(html):
        try:
            item = json.loads(match.group(1))
        except ValueError:
            continue
        url = str(item.get("url") or "")
        id_match = re.search(r"/a/show/(\d+)", url)
        if not id_match:
            continue
        ad_id = id_match.group(1)
        if ad_id in seen:
            continue
        seen.add(ad_id)

        attrs = item.get("attributes") or {}
        title = " ".join(str(attrs.get(k) or "") for k in ("brand", "model")).strip()
        text = cards.get(ad_id, "")

        year = None
        year_match = re.search(r"(20[0-2]\d|19[89]\d)\s*(?:г|y|yil)", text)
        if year_match:
            year = parse_year(year_match.group(1))

        mileage = None
        km_match = re.search(r"(\d[\d\s\u00a0]{2,})\s*км", text)
        if km_match:
            mileage = parse_mileage_km(km_match.group(0))

        price = to_int(item.get("unitPrice"))          # avtoelon quotes in y.e. (USD)
        city = str(item.get("city") or "").replace("gorod-", "").replace("-", " ")

        out.append(Listing(
            "Avtoelon", ad_id, url, f"{title} {year or ''}".strip(),
            price_usd=price, price_raw=f"{price} y.e." if price else None,
            year=year, mileage_km=mileage, city=city,
            posted_at=parse_datetime(item.get("lastUpdate")),
            fuel=text[:400], raw_text=text[:900],
        ))
    return out


def fetch_avtoelon(cfg, rate):
    result = SourceResult("Avtoelon")
    timeout = cfg["runtime"]["request_timeout_seconds"]
    seen = set()
    for url in ("https://avtoelon.uz/avto/gorod-tashkent/?sort=-created_date",
                "https://avtoelon.uz/avto/?sort=-created_date&fuel=elektro",
                "https://avtoelon.uz/avto/byd/?sort=-created_date",
                "https://avtoelon.uz/avto/?sort=-created_date&q=elektromobil"):
        html = http_get(url, timeout=timeout, tag="avtoelon_html")
        if not html:
            continue
        result.ok = True
        for listing in parse_avtoelon_html(html, rate):
            if listing.ad_id not in seen:
                seen.add(listing.ad_id)
                result.listings.append(listing)
        time.sleep(0.8)
    result.note = f"{len(result.listings)} raw listings"
    return result


# ------------------------- auto.uz platform (avto.uz + mashina.uz) --------------------
# Both domains serve the same auto.uz application, which publishes a schema.org
# ItemList of Vehicle objects — url, name, year, odometer and price, all structured.

def parse_autouz_jsonld(html: str, source: str, base_url: str, rate: float) -> list:
    out, seen = [], set()
    for block in extract_json_ld(html):
        if not isinstance(block, dict):
            continue
        elements = block.get("itemListElement")
        if not isinstance(elements, list):
            continue
        for element in elements:
            item = element.get("item") if isinstance(element, dict) else None
            if not isinstance(item, dict):
                continue
            if str(item.get("@type", "")).lower() not in ("vehicle", "car", "product"):
                continue
            url = item.get("url") or item.get("@id")
            if not url:
                continue
            id_match = re.search(r"/o_(\d+)", str(url))
            ad_id = id_match.group(1) if id_match else str(url).rstrip("/").rsplit("/", 1)[-1]
            if ad_id in seen:
                continue
            seen.add(ad_id)

            offers = item.get("offers") if isinstance(item.get("offers"), dict) else {}
            amount, currency = parse_price(offers.get("price"), offers.get("priceCurrency"))

            odometer = item.get("mileageFromOdometer")
            if isinstance(odometer, dict):
                odometer = odometer.get("value")

            out.append(Listing(
                source, ad_id, urllib.parse.urljoin(base_url, str(url)),
                str(item.get("name") or ""),
                price_usd=to_usd(amount, currency, rate),
                price_raw=f"{amount} {currency}" if amount else None,
                year=parse_year(item.get("vehicleModelDate") or item.get("productionDate")
                                or item.get("name")),
                mileage_km=parse_mileage_km(odometer),
                city=str(item.get("location") or ""),
                posted_at=parse_datetime(item.get("datePosted") or item.get("dateModified")),
                fuel=str(item.get("fuelType") or ""),
                raw_text=" ".join(str(item.get(k) or "") for k in
                                  ("name", "fuelType", "vehicleEngine",
                                   "bodyType", "description"))[:400],
            ))
    return out


def _fetch_autouz_platform(name: str, pages: list, cfg, rate) -> SourceResult:
    result = SourceResult(name)
    timeout = cfg["runtime"]["request_timeout_seconds"]
    seen = set()

    # The site's own backend, discovered in its page payload.
    for api in ("https://panel.auto.uz/api/v2/offer/list/?page=1&page_size=60",):
        data = http_get_json(api, timeout=timeout, tag=f"{name.lower()}_api")
        rows = data.get("results") if isinstance(data, dict) else None
        if isinstance(rows, list) and rows:
            for listing in listings_from_state_objects(rows, name, "https://avto.uz", rate):
                if listing.key not in seen:
                    seen.add(listing.key)
                    result.listings.append(listing)
                    result.ok = True

    for url in pages:
        html = http_get(url, timeout=timeout, tag=f"{name.lower()}_html")
        if not html:
            continue
        result.ok = True
        for listing in parse_autouz_jsonld(html, name, url, rate):
            if listing.key not in seen:
                seen.add(listing.key)
                result.listings.append(listing)
        time.sleep(0.8)

    result.note = f"{len(result.listings)} raw listings"
    return result


def fetch_avtouz(cfg, rate):
    return _fetch_autouz_platform("Avto.uz", [
        "https://avto.uz/cars/all?page=1",
        "https://avto.uz/cars/",
        "https://avto.uz/cars/all?fuel=electric",
    ], cfg, rate)


def fetch_mashina(cfg, rate):
    # mashina.uz serves the same auto.uz catalogue; kept only if explicitly enabled.
    return _fetch_autouz_platform("Mashina.uz", [
        "https://mashina.uz/cars?sort=date_desc",
    ], cfg, rate)


# ------------------------------ Avtobozor / Uzum --------------------------------------

def fetch_avtobozor(cfg, rate):
    # The bare domain presents a certificate issued for the www host, so lead with www.
    return fetch_generic(
        "Avtobozor",
        ["https://www.avtobozor.uz/avtomobili?sort=new",
         "https://www.avtobozor.uz/",
         "https://www.avtobozor.uz/search?q=byd"],
        re.compile(r"/(avto|car|e?lon|ads?|product)/", re.I), cfg, rate,
    )


def fetch_uzumavto(cfg, rate):
    # uzumavto.uz renders entirely in the browser; only its JSON backend is usable.
    return fetch_generic(
        "Uzum Avto", [], re.compile(r"/(car|cars|auto|ad)/", re.I), cfg, rate,
        json_apis=["https://uzumavto.uz/api/v1/cars?limit=50",
                   "https://uzumavto.uz/api/cars?limit=50",
                   "https://api.uzumavto.uz/v1/cars?limit=50"],
    )


SOURCES = {
    "olx": ("OLX", fetch_olx),
    "avtoelon": ("Avtoelon", fetch_avtoelon),
    "avtobozor": ("Avtobozor", fetch_avtobozor),
    "uzumavto": ("Uzum Avto", fetch_uzumavto),
    "mashina": ("Mashina.uz", fetch_mashina),
    "avtouz": ("Avto.uz", fetch_avtouz),
}


# --------------------------------------------------------------------------------------
# Currency rate
# --------------------------------------------------------------------------------------

def get_usd_rate(cfg: dict) -> float:
    fallback = float(cfg["runtime"]["usd_uzs_fallback_rate"])
    data = http_get_json("https://cbu.uz/uz/arkhiv-kursov-valyut/json/USD/",
                         timeout=cfg["runtime"]["request_timeout_seconds"])
    try:
        if isinstance(data, list) and data:
            rate = float(str(data[0].get("Rate")).replace(",", "."))
            if 5000 < rate < 60000:
                log(f"USD/UZS rate from CBU: {rate:,.2f}")
                return rate
    except (ValueError, TypeError, AttributeError, KeyError):
        pass
    log(f"Using fallback USD/UZS rate: {fallback:,.2f}", "WARN")
    return fallback


# --------------------------------------------------------------------------------------
# Filtering
# --------------------------------------------------------------------------------------

def in_target_region(listing: Listing, regions: list[str]) -> bool:
    # An empty region list means "anywhere". Subscribers narrow by location themselves
    # now, so the scanner no longer needs to be the one drawing the map.
    if not regions:
        return True
    haystack = f"{norm(listing.city)} {listing.blob} {norm(listing.url)}"
    if any(norm(region) in haystack for region in regions):
        return True
    # Other named oblasts are a definite no; an unknown location is given the benefit
    # of the doubt (many listings simply omit it).
    other_regions = ("samarkand", "samarqand", "самарканд", "buxoro", "bukhara", "бухар",
                     "andijan", "andijon", "андижан", "fergana", "farg", "ферган",
                     "namangan", "наманган", "qashqadaryo", "кашкадар", "surxondaryo",
                     "сурхандар", "navoiy", "навои", "jizzax", "джизак", "sirdaryo",
                     "сырдар", "xorazm", "хорезм", "urganch", "ургенч", "nukus", "нукус",
                     "karakalpak", "каракалпак", "termiz", "термез", "qoqon", "коканд")
    if any(word in haystack for word in other_regions):
        return False
    return not listing.city


# Grouping is defined once in carfilters and shared with the bot and the database.
def mileage_tier(km: int | None) -> str:
    return carfilters.mileage_band(km)


def evaluate(listing: Listing, cfg: dict) -> tuple[bool, str, str]:
    """Return (keep, tier, reason). tier is 'top' or 'stretch'."""
    filters = cfg["filters"]

    if not looks_like_a_car(listing):
        return False, "", "not a car"

    for word in filters["exclude_keywords"]:
        if norm(word) and norm(word) in listing.blob:
            return False, "", f"excluded keyword '{word}'"

    # Powertrain is no longer a gate - every kind of car qualifies. It is still
    # classified, because the renderer shows a different icon for electrics.
    powertrain = classify_powertrain(listing) or "ICE"

    if listing.year is not None and listing.year < filters["min_year"]:
        return False, "", f"year {listing.year} < {filters['min_year']}"

    if listing.price_usd is not None and listing.price_usd > filters["max_price_usd"]:
        return False, "", f"price ${listing.price_usd} over budget"
    if listing.price_usd is not None and listing.price_usd < 500:
        return False, "", "price implausibly low (likely a part, not a car)"

    if listing.mileage_km is not None and listing.mileage_km > filters["hard_max_mileage_km"]:
        return False, "", f"mileage {listing.mileage_km} km too high"

    # "0 km" on OLX is almost always a dealer/import listing rather than a real used car,
    # and it is the shape most scam ads take.
    min_km = int(filters.get("min_mileage_km", 0))
    if min_km and listing.mileage_km is not None and listing.mileage_km < min_km:
        return False, "", "0 km / as-new listing"

    if not in_target_region(listing, filters["regions"]):
        return False, "", f"outside Tashkent ({listing.city[:40]})"

    listing.fuel = listing.fuel or powertrain
    return True, mileage_tier(listing.mileage_km), powertrain


def score(listing: Listing) -> tuple:
    """Sort key — lower is better."""
    mileage = listing.mileage_km if listing.mileage_km is not None else 60000
    year = listing.year or 2022
    price = listing.price_usd if listing.price_usd is not None else 15000
    return (mileage, -year, price)


# --------------------------------------------------------------------------------------
# State
# --------------------------------------------------------------------------------------

class State:
    def __init__(self, path: str = DB_PATH):
        self.conn = sqlite3.connect(path)
        self.conn.execute("""CREATE TABLE IF NOT EXISTS seen (
            key TEXT PRIMARY KEY, source TEXT, ad_id TEXT, url TEXT, title TEXT,
            price_usd INTEGER, first_seen TEXT, posted_at TEXT)""")
        self.conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        self.conn.commit()

    def get_meta(self, key: str, default=None):
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute("INSERT INTO meta(key,value) VALUES(?,?) "
                          "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
        self.conn.commit()

    def last_run(self) -> datetime | None:
        raw = self.get_meta("last_run")
        return parse_datetime(raw) if raw else None

    def is_seen(self, key: str) -> bool:
        return self.conn.execute("SELECT 1 FROM seen WHERE key=?", (key,)).fetchone() is not None

    def mark_seen(self, listing: Listing) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO seen(key,source,ad_id,url,title,price_usd,first_seen,posted_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (listing.key, listing.source, listing.ad_id, listing.url, listing.title,
             listing.price_usd, datetime.now(TASHKENT_TZ).isoformat(),
             listing.posted_at.isoformat() if listing.posted_at else None))

    def commit(self) -> None:
        self.conn.commit()

    def stats(self) -> dict:
        total = self.conn.execute("SELECT COUNT(*) FROM seen").fetchone()[0]
        by_source = self.conn.execute(
            "SELECT source, COUNT(*) FROM seen GROUP BY source ORDER BY 2 DESC").fetchall()
        return {"total": total, "by_source": by_source, "last_run": self.get_meta("last_run")}


# --------------------------------------------------------------------------------------
# Telegram
# --------------------------------------------------------------------------------------

def telegram_send(cfg: dict, text: str) -> bool:
    token = cfg["telegram"]["bot_token"].strip()
    chat_id = str(cfg["telegram"]["chat_id"]).strip()
    if not token or not chat_id:
        log("Telegram bot_token / chat_id missing in config.json", "ERROR")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode("utf-8")

    for attempt in range(3):
        try:
            req = urllib.request.Request(
                url, data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded",
                         "User-Agent": "ev-hunter/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                json.loads(resp.read().decode("utf-8"))
                return True
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8")[:300]
            except Exception:
                pass
            log(f"Telegram HTTP {exc.code}: {detail}", "ERROR")
            if exc.code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            if exc.code in (400, 401, 403):
                return False
        except Exception as exc:  # noqa: BLE001
            log(f"Telegram send failed: {type(exc).__name__}: {exc}", "ERROR")
        time.sleep(3 * (attempt + 1))
    return False


def esc(text: str) -> str:
    return (str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


SOURCE_TAG = {"OLX": "OLX", "Avtoelon": "Avtoelon", "Avtobozor": "Avtobozor",
              "Uzum Avto": "Uzum", "Mashina.uz": "Mashina", "Avto.uz": "Avto.uz"}


def render_listing(listing: Listing, index: int, tier: str) -> str:
    title = esc(listing.title[:90] or "Listing")
    lines = [f"<b>{index}.</b> 🔋 <a href=\"{esc(listing.url)}\">{title}</a>"]

    facts = [f"💵 <b>{fmt_money(listing.price_usd)}</b>"]
    if listing.year:
        facts.append(f"📅 {listing.year}")
    facts.append(f"🛣 {fmt_km(listing.mileage_km)}")
    lines.append("      " + "  ·  ".join(facts))

    extras = []
    if listing.city:
        city = re.sub(r"\s+", " ", listing.city).strip()[:45]
        extras.append(f"📍 {esc(city)}")
    if listing.owners:
        extras.append(f"👤 {listing.owners} owner" + ("s" if listing.owners > 1 else ""))
    extras.append(f"🏷 {esc(SOURCE_TAG.get(listing.source, listing.source))}")
    if listing.posted_at:
        extras.append(f"🕒 {listing.posted_at.strftime('%d %b %H:%M')}")
    lines.append("      " + "  ·  ".join(extras))

    if tier == "stretch":
        lines.append("      <i>⚠️ stretch match — check mileage / details</i>")
    return "\n".join(lines)


def build_messages(top: list, stretch: list, cfg: dict, window_note: str) -> list:
    """Return [(message_text, listings_in_it)] so delivery can be committed per message."""
    chunk_size = max(1, int(cfg["runtime"]["max_items_per_message"]))
    total = len(top) + len(stretch)
    header = (f"\U0001F698 <b>{total} new EV listing{'s' if total != 1 else ''}</b>\n"
              f"<i>{esc(window_note)}</i>")

    messages, parts, carried = [], [header], []
    counter = 0

    def flush():
        if carried:
            messages.append(("\n\n".join(parts), list(carried)))

    for tier, group, title in (("top", top, "\n<b>\u2501\u2501 TOP MATCHES (under 50 000 km) \u2501\u2501</b>"),
                               ("stretch", stretch, "\n<b>\u2501\u2501 ALSO WORTH A LOOK \u2501\u2501</b>")):
        if not group:
            continue
        parts.append(title)
        for listing in group:
            counter += 1
            block = render_listing(listing, counter, tier)
            too_long = sum(len(p) + 2 for p in parts) + len(block) > 3800
            if carried and (len(carried) >= chunk_size or too_long):
                flush()
                parts, carried[:] = ["\U0001F698 <b>\u2026continued</b>", title], []
            parts.append(block)
            carried.append(listing)
    flush()
    return messages


# --------------------------------------------------------------------------------------
# Main scan
# --------------------------------------------------------------------------------------

def run_scan(cfg: dict, state: State, dry_run: bool = False,
             backfill_days: int | None = None) -> int:
    now = datetime.now(TASHKENT_TZ)
    last = state.last_run()

    one_time = cfg["runtime"].get("one_time_backfill_days")
    if backfill_days is None and one_time:
        backfill_days = int(one_time)
        log(f"One-time {backfill_days}-day catch-up requested by config; consuming it now.")
        try:
            saved = json.load(io.open(CONFIG_PATH, encoding="utf-8"))
            saved.get("runtime", {}).pop("one_time_backfill_days", None)
            io.open(CONFIG_PATH, "w", encoding="utf-8").write(
                json.dumps(saved, indent=2, ensure_ascii=False))
        except (OSError, ValueError) as exc:
            log(f"Could not clear one_time_backfill_days: {exc}", "WARN")

    if backfill_days is not None:
        since = now - timedelta(days=backfill_days)
        window_note = f"first {backfill_days}-day sweep · {since:%d %b} → {now:%d %b %H:%M}"
    elif last is None:
        days = cfg["filters"]["first_run_backfill_days"]
        since = now - timedelta(days=days)
        window_note = f"first run — everything posted in the last {days} days"
    else:
        since = last
        gap_hours = (now - since).total_seconds() / 3600.0
        if gap_hours > 2:
            window_note = (f"catching up on {gap_hours:.0f}h offline · "
                           f"since {since:%d %b %H:%M}")
        else:
            window_note = f"since {since:%d %b %H:%M}"
    # Sites index ads a few minutes after their stated post time, and sellers bump old
    # ads. Widening the window backwards costs nothing — the seen-ads database is what
    # actually guarantees you never get the same car twice.
    max_age_days = int(cfg["filters"].get("max_age_days", 0))
    if backfill_days is not None:
        cutoff = now - timedelta(days=backfill_days)
    elif last is None:
        cutoff = now - timedelta(days=cfg["filters"]["first_run_backfill_days"])
    elif max_age_days > 0:
        cutoff = now - timedelta(days=max_age_days)
    else:
        cutoff = None
        window_note = "everything new since the last check"
    log(f"Age cut-off: {cutoff:%Y-%m-%d %H:%M}" if cutoff else
        "Age cut-off: none — anything not already sent counts as new")

    rate = get_usd_rate(cfg)

    all_listings: list[Listing] = []
    failures: list[str] = []
    for key, (label, fetcher) in SOURCES.items():
        if not cfg["sources"].get(key, False):
            continue
        log(f"Fetching {label}…")
        try:
            result = fetcher(cfg, rate)
        except Exception as exc:  # noqa: BLE001 - one broken site must not kill the run
            log(f"  {label} crashed: {type(exc).__name__}: {exc}", "ERROR")
            log(traceback.format_exc(), "DEBUG")
            failures.append(label)
            continue
        if not result.ok or not result.listings:
            log(f"  {label}: no data ({result.note})", "WARN")
            failures.append(label)
        else:
            log(f"  {label}: {result.note}")
        all_listings.extend(result.listings)

    log(f"Collected {len(all_listings)} raw listings from all sources.")

    top, stretch, fresh = [], [], []
    rejected = {}
    for listing in all_listings:
        keep, tier, reason = evaluate(listing, cfg)
        if not keep:
            rejected[reason] = rejected.get(reason, 0) + 1
            continue
        if state.is_seen(listing.key):
            continue
        if cutoff is not None and listing.posted_at is not None and listing.posted_at < cutoff:
            continue
        fresh.append(listing)
        (top if tier == "top" else stretch).append(listing)

    top.sort(key=score)
    stretch.sort(key=score)

    if rejected:
        summary = ", ".join(f"{count}× {reason}" for reason, count in
                            sorted(rejected.items(), key=lambda kv: -kv[1])[:6])
        log(f"Filtered out: {summary}")
    log(f"Matches to send: {len(top)} top + {len(stretch)} stretch")

    if not fresh:
        if not dry_run:
            state.set_meta("last_run", now.isoformat())
            if failures and cfg["runtime"]["notify_on_source_failure"]:
                maybe_warn_about_failures(cfg, state, failures, now)
        log("Nothing new — staying quiet.")
        return 0

    messages = build_messages(top, stretch, cfg, window_note)

    if dry_run:
        print("\n" + "=" * 70)
        for message, _ in messages:
            print(re.sub(r"<[^>]+>", "", message))
            print("-" * 70)
        print("=" * 70 + "\n")
        log(f"[dry-run] {len(fresh)} listings would have been sent; nothing saved.")
        return len(fresh)

    # Commit each message as it lands. If message 5 of 16 fails, the first four stay
    # marked as sent, so the retry picks up where it stopped instead of repeating them.
    delivered = 0
    sent_all = True
    for message, items in messages:
        if not telegram_send(cfg, message):
            sent_all = False
            break
        for listing in items:
            state.mark_seen(listing)
        state.commit()
        delivered += len(items)
        time.sleep(1.2)

    if delivered:
        log(f"Sent {delivered} listings to Telegram and marked them as seen.")
    if sent_all:
        state.set_meta("last_run", now.isoformat())
        if failures and cfg["runtime"]["notify_on_source_failure"]:
            maybe_warn_about_failures(cfg, state, failures, now)
    else:
        log(f"Delivery stopped after {delivered}/{len(fresh)} listings — the rest retry "
            f"next hour, already-sent ones will not repeat.", "ERROR")
    return len(fresh)


def maybe_warn_about_failures(cfg: dict, state: State, failures: list[str], now: datetime) -> None:
    """Warn about dead sources at most once every 24 hours."""
    last_warn = parse_datetime(state.get_meta("last_failure_warn"))
    if last_warn and (now - last_warn) < timedelta(hours=24):
        return
    telegram_send(cfg, "⚠️ <b>EV Hunter notice</b>\nNo results from: "
                       + esc(", ".join(failures))
                       + "\n<i>The site may have changed its layout or blocked the request. "
                         "Other sources are still working.</i>")
    state.set_meta("last_failure_warn", now.isoformat())


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------

def main() -> int:
    global _DIAG, _VERBOSE

    parser = argparse.ArgumentParser(description="EV Hunter — Uzbek EV deal scanner")
    parser.add_argument("--loop", action="store_true", help="run continuously, once per interval")
    parser.add_argument("--dry-run", action="store_true", help="print results, send nothing")
    parser.add_argument("--diag", action="store_true", help="dump raw responses into debug/")
    parser.add_argument("--test-telegram", action="store_true", help="send a test message and exit")
    parser.add_argument("--backfill", type=int, metavar="DAYS", help="force an N-day lookback")
    parser.add_argument("--reset", action="store_true", help="clear the seen-ads database")
    parser.add_argument("--stats", action="store_true", help="print database stats and exit")
    parser.add_argument("--quiet", action="store_true", help="log to file only")
    args = parser.parse_args()

    _DIAG = args.diag
    _VERBOSE = not args.quiet

    cfg = load_config()
    state = State()

    if args.stats:
        stats = state.stats()
        print(f"Ads remembered : {stats['total']}")
        print(f"Last run       : {stats['last_run'] or 'never'}")
        for source, count in stats["by_source"]:
            print(f"  {source:<12} {count}")
        return 0

    if args.reset:
        state.conn.execute("DELETE FROM seen")
        state.conn.execute("DELETE FROM meta")
        state.commit()
        log("Database cleared — the next run will do a full backfill.")
        return 0

    if args.test_telegram:
        ok = telegram_send(cfg, "✅ <b>EV Hunter is connected.</b>\n"
                                "You'll get a message here whenever a new matching EV appears.")
        log("Test message sent." if ok else "Test message FAILED — check bot_token / chat_id.",
            "INFO" if ok else "ERROR")
        return 0 if ok else 1

    if not cfg["telegram"]["bot_token"] or not cfg["telegram"]["chat_id"]:
        log("config.json is missing your Telegram bot_token / chat_id.", "ERROR")
        return 1

    interval = max(5, int(cfg["runtime"]["interval_minutes"])) * 60

    if not args.loop:
        run_scan(cfg, state, dry_run=args.dry_run, backfill_days=args.backfill)
        return 0

    log(f"Loop mode: scanning every {interval // 60} minutes. Ctrl+C to stop.")
    backfill = args.backfill
    while True:
        started = time.time()
        try:
            run_scan(cfg, state, dry_run=args.dry_run, backfill_days=backfill)
        except KeyboardInterrupt:
            log("Stopped by user.")
            return 0
        except Exception as exc:  # noqa: BLE001 - the loop must survive anything
            log(f"Scan crashed: {type(exc).__name__}: {exc}", "ERROR")
            log(traceback.format_exc(), "DEBUG")
        backfill = None
        sleep_for = max(60, interval - (time.time() - started))
        log(f"Next scan in {sleep_for / 60:.0f} minutes.")
        try:
            time.sleep(sleep_for)
        except KeyboardInterrupt:
            log("Stopped by user.")
            return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)


# --------------------------------------------------------------------------------------
# Multi-user support
# --------------------------------------------------------------------------------------

def collect_matches(cfg: dict) -> tuple[list, dict]:
    """Scan every enabled source and return (matching listings, diagnostics).

    Sends nothing and writes nothing. This is what the multi-user bot drives; run_scan()
    above is still the single-chat CLI path used by --dry-run and friends.
    """
    rate = get_usd_rate(cfg)
    all_listings: list[Listing] = []
    failures: list[str] = []

    for key, (label, fetcher) in SOURCES.items():
        if not cfg["sources"].get(key, False):
            continue
        log(f"Fetching {label}…")
        try:
            result = fetcher(cfg, rate)
        except Exception as exc:  # noqa: BLE001 - one broken site must not kill the run
            log(f"  {label} crashed: {type(exc).__name__}: {exc}", "ERROR")
            failures.append(label)
            continue
        if not result.ok or not result.listings:
            log(f"  {label}: no data ({result.note})", "WARN")
            failures.append(label)
        else:
            log(f"  {label}: {result.note}")
        all_listings.extend(result.listings)

    matches, rejected = [], {}
    for listing in all_listings:
        keep, tier, reason = evaluate(listing, cfg)
        if keep:
            matches.append((tier, listing))
        else:
            rejected[reason] = rejected.get(reason, 0) + 1

    matches.sort(key=lambda pair: score(pair[1]))
    log(f"Collected {len(all_listings)} raw listings, {len(matches)} match the filters.")
    return matches, {"raw": len(all_listings), "failures": failures, "rejected": rejected}
