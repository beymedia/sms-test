"""SMS provider adapters. Select one with the SMS_PROVIDER env variable."""
import logging
import os
import uuid

import requests

log = logging.getLogger(__name__)


class SendError(Exception):
    pass


class LogProvider:
    """Test mode: nothing leaves the server. Messages are only logged and recorded."""

    name = "log"

    def send(self, to, body):
        log.info("SIMULATED SMS to %s: %s", to, body)
        return f"sim-{uuid.uuid4().hex}"


class TwilioProvider:
    """Sends SMS through the Twilio REST API (no SDK needed)."""

    name = "twilio"

    def __init__(self):
        self.account_sid = os.environ["TWILIO_ACCOUNT_SID"]
        self.auth_token = os.environ["TWILIO_AUTH_TOKEN"]
        self.sender = os.environ["TWILIO_FROM"]
        self.url = (
            f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        )

    def send(self, to, body):
        resp = requests.post(
            self.url,
            auth=(self.account_sid, self.auth_token),
            data={"To": to, "From": self.sender, "Body": body},
            timeout=15,
        )
        if resp.status_code >= 300:
            raise SendError(f"Twilio {resp.status_code}: {resp.text[:300]}")
        return resp.json().get("sid")


def get_provider():
    name = os.environ.get("SMS_PROVIDER", "log").lower()
    if name == "log":
        return LogProvider()
    if name == "twilio":
        return TwilioProvider()
    raise ValueError(f"Unknown SMS_PROVIDER: {name!r} (use 'log' or 'twilio')")
