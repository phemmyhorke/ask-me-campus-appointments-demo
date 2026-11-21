from concurrent.futures import ThreadPoolExecutor
from datetime import date
import json
from threading import Thread
from unittest import TestCase
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app import DemoError, Schedule, make_server


class ScheduleTests(TestCase):
    def setUp(self):
        self.schedule = Schedule(date(2026, 11, 20))
        self.a, self.b, *_ = self.schedule.slots

    def test_generates_four_weekdays(self):
        dates = {s["date"] for s in self.schedule.state()["slots"]}
        self.assertEqual(dates, {"2026-11-23", "2026-11-24", "2026-11-25", "2026-11-26"})

    def test_book_move_cancel_releases_slots(self):
        key = self.schedule.book(self.a)
        self.schedule.move(key, self.b)
        self.assertEqual(self.schedule.state()["bookings"][0]["slot"]["id"], self.b)
        self.schedule.book(self.a)
        self.schedule.cancel(key)
        self.schedule.book(self.b)
        self.assertEqual(len(self.schedule.state()["bookings"]), 2)

    def test_conflicting_reschedule_preserves_original(self):
        key = self.schedule.book(self.a)
        self.schedule.book(self.b)
        with self.assertRaises(DemoError) as e:
            self.schedule.move(key, self.b)
        self.assertEqual(e.exception.status, 409)
        self.assertEqual(self.schedule.state()["bookings"][0]["slot"]["id"], self.a)

    def test_concurrent_requests_get_one_slot(self):
        def attempt(_):
            try:
                self.schedule.book(self.a)
                return 201
            except DemoError as e:
                return e.status
        with ThreadPoolExecutor(max_workers=5) as pool:
            self.assertCountEqual(pool.map(attempt, range(5)), [201, 409, 409, 409, 409])


class HttpTests(TestCase):
    def setUp(self):
        self.server = make_server(0, Schedule(date(2026, 11, 20)))
        self.worker = Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.worker.join)
        self.addCleanup(self.server.shutdown)
        self.url = "http://127.0.0.1:" + str(self.server.server_port)

    def call(self, path, method="GET", value=None, headers=None):
        req = Request(self.url + path, data=json.dumps(value).encode() if value is not None else None,
                      headers={"Content-Type": "application/json", **(headers or {})}, method=method)
        try:
            with urlopen(req, timeout=3) as resp:
                return resp.status, json.load(resp)
        except HTTPError as err:
            with err:
                return err.code, json.load(err)

    def test_http_booking_journey(self):
        status, state = self.call("/api/schedule")
        self.assertEqual(status, 200)
        a, b, *_ = [s["id"] for s in state["slots"]]
        status, result = self.call("/api/bookings", "POST", {"slotId": a})
        self.assertEqual(status, 201)
        path = "/api/bookings/" + result["id"]
        self.assertEqual(self.call("/api/bookings", "POST", {"slotId": a})[0], 409)
        self.assertEqual(self.call(path, "PATCH", {"slotId": b})[0], 200)
        self.assertEqual(self.call("/api/schedule")[1]["bookings"][0]["slot"]["id"], b)
        self.assertEqual(self.call(path, "DELETE")[0], 200)
        self.assertEqual(self.call(path, "DELETE")[0], 404)
        self.assertEqual(self.call("/api/schedule")[1]["bookings"], [])

    def test_bad_inputs_and_cross_origin(self):
        a = next(iter(self.server.schedule.slots))
        for payload in ([], {"unexpected": a}, {"slotId": None}, {"slotId": "unknown"},
                        {"slotId": a, "extra": "never collected"}):
            with self.subTest(payload=payload):
                self.assertEqual(self.call("/api/bookings", "POST", payload)[0], 400)
        self.assertEqual(self.call("/api/bookings", "POST", {"slotId": a},
                                   {"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.call("/api/bookings", "POST", {"slotId": a},
                                   {"Origin": "http://example.invalid"})[0], 403)
        self.assertEqual(self.call("/api/schedule")[1]["bookings"], [])

    def test_only_allowlisted_static_assets_served(self):
        with urlopen(self.url + "/", timeout=3) as res:
            self.assertIn(b"PORTFOLIO DEMO", res.read())
            self.assertIn("frame-ancestors 'none'", res.headers["Content-Security-Policy"])
        self.assertEqual(self.call("/app.py")[0], 404)
