"""SMS sending service: single and bulk sends, daily limits, opt-out, background worker."""
import hmac
import logging
import os
import re
import threading
import time
from collections import Counter
from functools import wraps

from flask import Flask, Response, abort, jsonify, request

import store
from providers import SendError, get_provider

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("sms-service")

app = Flask(__name__)

API_KEY = os.environ.get("API_KEY", "")
INBOUND_TOKEN = os.environ.get("INBOUND_TOKEN", "")
MAX_BULK = int(os.environ.get("MAX_BULK", "500"))
SEND_RATE_PER_SEC = float(os.environ.get("SEND_RATE_PER_SEC", "1"))
MAX_BODY = 1600
E164 = re.compile(r"^\+[1-9]\d{6,14}$")
STOP_WORDS = {"STOP", "DUR", "UNSUBSCRIBE"}

store.init_db()
provider = get_provider()


def require_api_key(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        supplied = request.headers.get("X-API-Key", "")
        if not API_KEY or not hmac.compare_digest(supplied, API_KEY):
            return jsonify(error="unauthorized"), 401
        return fn(*args, **kwargs)

    return wrapper


def _clean_number(raw):
    number = str(raw or "").replace(" ", "").replace("-", "")
    return number if E164.match(number) else None


def _clean_body(raw):
    body = str(raw or "").strip()
    return body if body and len(body) <= MAX_BODY else None


@app.get("/health")
def health():
    return jsonify(status="ok", provider=provider.name)


@app.post("/sms/send")
@require_api_key
def send_one():
    data = request.get_json(silent=True) or {}
    number = _clean_number(data.get("to"))
    body = _clean_body(data.get("body"))
    if not number or not body:
        return jsonify(error="'to' (E.164, e.g. +994501234567) and 'body' (1-1600 chars) are required"), 400

    result = store.enqueue([number], body)[0]
    code = 202 if result["status"] == "queued" else 422
    return jsonify(result), code


@app.post("/sms/bulk")
@require_api_key
def send_bulk():
    data = request.get_json(silent=True) or {}
    body = _clean_body(data.get("body"))
    recipients = data.get("recipients")
    if not body or not isinstance(recipients, list) or not recipients:
        return jsonify(error="'recipients' (list) and 'body' are required"), 400
    if len(recipients) > MAX_BULK:
        return jsonify(error=f"at most {MAX_BULK} recipients per request"), 400

    valid, results = [], []
    for raw in recipients:
        number = _clean_number(raw)
        if number:
            valid.append(number)
        else:
            results.append({"to": str(raw), "status": "invalid", "reason": "bad_number_format"})

    results = store.enqueue(valid, body) + results
    summary = dict(Counter(r["status"] for r in results))
    return jsonify(summary=summary, results=results), 202


@app.get("/sms/<int:msg_id>")
@require_api_key
def message_status(msg_id):
    row = store.get_message(msg_id)
    if row is None:
        return jsonify(error="not found"), 404
    return jsonify(row)


@app.get("/limits")
@require_api_key
def limits():
    payload = {
        "global_used_today": store.usage_today(),
        "global_limit": store.GLOBAL_DAILY_LIMIT,
        "per_number_limit": store.PER_NUMBER_DAILY_LIMIT,
    }
    number = _clean_number(request.args.get("to"))
    if number:
        payload["number"] = number
        payload["number_used_today"] = store.usage_today(number)
        payload["opted_out"] = store.is_opted_out(number)
    return jsonify(payload)


@app.post("/sms/inbound/<token>")
def inbound(token):
    """Twilio webhook for incoming replies. Handles STOP-style opt-outs."""
    if not INBOUND_TOKEN or not hmac.compare_digest(token, INBOUND_TOKEN):
        abort(404)
    sender = _clean_number(request.form.get("From"))
    text = (request.form.get("Body") or "").strip().upper()
    if sender and text in STOP_WORDS:
        store.add_opt_out(sender)
        log.info("Opt-out recorded for %s", sender)
    return Response("<Response/>", mimetype="text/xml")


def _worker():
    interval = 1.0 / SEND_RATE_PER_SEC
    while True:
        row = store.next_queued()
        if row is None:
            time.sleep(1)
            continue
        msg_id, number = row["id"], row["to_number"]
        if store.is_opted_out(number):
            store.update_message(msg_id, "blocked", error="opted_out")
        else:
            try:
                provider_id = provider.send(number, row["body"])
                status = "simulated" if provider.name == "log" else "sent"
                store.update_message(msg_id, status, provider_id=provider_id)
            except (SendError, OSError) as exc:
                log.error("Send failed for message %s: %s", msg_id, exc)
                store.update_message(msg_id, "failed", error=str(exc)[:500])
        time.sleep(interval)


def start_worker():
    thread = threading.Thread(target=_worker, daemon=True, name="sms-worker")
    thread.start()
    return thread


if os.environ.get("DISABLE_WORKER") != "1":
    start_worker()
