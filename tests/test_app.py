import os
import tempfile
import unittest

os.environ["SMS_PROVIDER"] = "log"
os.environ["API_KEY"] = "test-key"
os.environ["INBOUND_TOKEN"] = "inbound-secret"
os.environ["DISABLE_WORKER"] = "1"

import app as service  # noqa: E402
import store  # noqa: E402

HEADERS = {"X-API-Key": "test-key"}


class SmsServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        store.DB_PATH = self.tmp.name
        store.PER_NUMBER_DAILY_LIMIT = 2
        store.GLOBAL_DAILY_LIMIT = 3
        store.init_db()
        self.client = service.app.test_client()

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_requires_api_key(self):
        resp = self.client.post("/sms/send", json={"to": "+994501234567", "body": "hi"})
        self.assertEqual(resp.status_code, 401)

    def test_rejects_bad_number(self):
        resp = self.client.post("/sms/send", json={"to": "0501234567", "body": "hi"},
                                headers=HEADERS)
        self.assertEqual(resp.status_code, 400)

    def test_per_number_limit(self):
        for _ in range(2):
            resp = self.client.post("/sms/send", json={"to": "+994501234567", "body": "hi"},
                                    headers=HEADERS)
            self.assertEqual(resp.status_code, 202)
        resp = self.client.post("/sms/send", json={"to": "+994501234567", "body": "hi"},
                                headers=HEADERS)
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.get_json()["reason"], "number_daily_limit")

    def test_global_limit_in_bulk(self):
        numbers = [f"+99450000000{i}" for i in range(5)]
        resp = self.client.post("/sms/bulk", json={"recipients": numbers, "body": "hi"},
                                headers=HEADERS)
        data = resp.get_json()
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(data["summary"]["queued"], 3)
        self.assertEqual(data["summary"]["blocked"], 2)

    def test_bulk_flags_invalid_numbers(self):
        resp = self.client.post("/sms/bulk",
                                json={"recipients": ["abc", "+994501234567"], "body": "hi"},
                                headers=HEADERS)
        data = resp.get_json()
        self.assertEqual(data["summary"], {"queued": 1, "invalid": 1})

    def test_stop_reply_opts_out(self):
        self.client.post("/sms/inbound/inbound-secret",
                         data={"From": "+994501234567", "Body": "STOP"})
        resp = self.client.post("/sms/send", json={"to": "+994501234567", "body": "hi"},
                                headers=HEADERS)
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.get_json()["reason"], "opted_out")

    def test_inbound_wrong_token_is_hidden(self):
        resp = self.client.post("/sms/inbound/wrong", data={"From": "+994501234567", "Body": "STOP"})
        self.assertEqual(resp.status_code, 404)

    def test_limits_endpoint(self):
        self.client.post("/sms/send", json={"to": "+994501234567", "body": "hi"},
                         headers=HEADERS)
        resp = self.client.get("/limits?to=%2B994501234567", headers=HEADERS)
        data = resp.get_json()
        self.assertEqual(data["number_used_today"], 1)
        self.assertEqual(data["global_used_today"], 1)


if __name__ == "__main__":
    unittest.main()
