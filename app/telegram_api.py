#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal Telegram Bot API client (standard library only)."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.telegram.org/bot{token}/{method}"


class TelegramError(Exception):
    pass


class Telegram:
    def __init__(self, token: str, logger=None):
        self.token = (token or "").strip()
        self.log = logger or (lambda msg, level="INFO": None)

    def call(self, method: str, timeout: int = 30, **params):
        """POST to the Bot API. Returns the `result` payload, or None on failure."""
        return self.request(method, timeout=timeout, **params)[0]

    def request(self, method: str, timeout: int = 30, **params):
        """Like call(), but returns (result, error_code).

        error_code is the Telegram/HTTP status when the call failed - the caller needs it
        to tell "this chat is gone for good" (400/403) from "try again later".
        """
        url = API.format(token=self.token, method=method)
        # Nested structures (keyboards) must travel as JSON strings.
        payload = {}
        for key, value in params.items():
            if value is None:
                continue
            payload[key] = (json.dumps(value, ensure_ascii=False)
                            if isinstance(value, (dict, list)) else value)
        data = urllib.parse.urlencode(payload).encode("utf-8")

        for attempt in range(3):
            try:
                req = urllib.request.Request(
                    url, data=data,
                    headers={"Content-Type": "application/x-www-form-urlencoded",
                             "User-Agent": "ev-hunter-bot/2.0"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                    if body.get("ok"):
                        return body.get("result"), None
                    self.log(f"Telegram {method} not ok: {body}", "WARN")
                    return None, body.get("error_code")
            except urllib.error.HTTPError as exc:
                detail = ""
                try:
                    detail = exc.read().decode("utf-8")[:300]
                except Exception:  # noqa: BLE001
                    pass
                if exc.code == 429:
                    wait = 3 * (attempt + 1)
                    self.log(f"Telegram rate limited, waiting {wait}s", "WARN")
                    time.sleep(wait)
                    continue
                # 403 = user blocked the bot. Caller decides what to do; not retryable.
                self.log(f"Telegram {method} HTTP {exc.code}: {detail}", "WARN")
                return None, exc.code
            except Exception as exc:  # noqa: BLE001
                self.log(f"Telegram {method} failed: {type(exc).__name__}: {exc}", "WARN")
                time.sleep(1.5 * (attempt + 1))
        return None, None

    # ------------------------------------------------------------------ helpers ---

    def send(self, chat_id, text, reply_markup=None, preview=False):
        return self.send_checked(chat_id, text, reply_markup, preview)[0]

    def send_checked(self, chat_id, text, reply_markup=None, preview=False):
        """sendMessage returning (result, error_code).

        400 "chat not found" and 403 "bot was blocked" both mean this chat is
        unreachable until the user starts the bot again - not a transient failure.
        """
        return self.request("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML",
                            disable_web_page_preview="false" if preview else "true",
                            reply_markup=reply_markup)

    def edit(self, chat_id, message_id, text, reply_markup=None):
        return self.call("editMessageText", chat_id=chat_id, message_id=message_id,
                         text=text, parse_mode="HTML", disable_web_page_preview="true",
                         reply_markup=reply_markup)

    def edit_markup(self, chat_id, message_id, reply_markup=None):
        return self.call("editMessageReplyMarkup", chat_id=chat_id,
                         message_id=message_id, reply_markup=reply_markup)

    def answer_callback(self, callback_id, text=None, alert=False):
        return self.call("answerCallbackQuery", callback_query_id=callback_id,
                         text=text, show_alert="true" if alert else "false")

    def get_updates(self, offset=None, poll_timeout=30):
        """Long-poll for updates.

        Not routed through call(), because `timeout` here is a Bot API parameter while
        call() uses that name for the HTTP timeout - and the HTTP one must be the larger
        of the two or urllib aborts the connection mid-poll.
        """
        url = API.format(token=self.token, method="getUpdates")
        params = {"timeout": poll_timeout,
                  "allowed_updates": json.dumps(["message", "callback_query"])}
        if offset is not None:
            params["offset"] = offset
        data = urllib.parse.urlencode(params).encode("utf-8")
        try:
            req = urllib.request.Request(
                url, data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded",
                         "User-Agent": "ev-hunter-bot/2.0"})
            with urllib.request.urlopen(req, timeout=poll_timeout + 20) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                return body.get("result") or [] if body.get("ok") else []
        except Exception as exc:  # noqa: BLE001 - long poll times out routinely
            self.log(f"getUpdates: {type(exc).__name__}: {exc}", "DEBUG")
            return []

    def delete_webhook(self):
        """getUpdates and webhooks are mutually exclusive; make sure polling can work."""
        return self.call("deleteWebhook", drop_pending_updates="false")


def esc(text) -> str:
    return (str(text if text is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
