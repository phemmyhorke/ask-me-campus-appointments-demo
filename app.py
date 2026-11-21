"""Local-only, fictional appointment scheduling portfolio prototype."""
import argparse
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
from threading import Lock
from urllib.parse import urlsplit
from uuid import uuid4

STATIC = Path(__file__).with_name("static")
ASSETS = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
          "/style.css": ("style.css", "text/css")}
BOOKING_PATH = re.compile(r"/api/bookings/([a-f0-9]{32})")


class DemoError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


class Schedule:
    """Store fictional bookings in memory and serialize slot claims."""

    def __init__(self, today=None):
        today = today or date.today()
        days, candidate = [], today
        while len(days) < 4:
            candidate += timedelta(days=1)
            if candidate.weekday() < 5:
                days.append(candidate)
        times = [
            ("09:00", "9:00 AM", "Jordan Lee", "Campus Counseling"),
            ("11:30", "11:30 AM", "Taylor Morgan", "Student Wellbeing"),
            ("14:00", "2:00 PM", "Casey Patel", "Campus Counseling"),
        ]
        self.slots = {
            f"{day:%Y%m%d}-{clock.replace(':', '')}":
            {"id": f"{day:%Y%m%d}-{clock.replace(':', '')}", "date": day.isoformat(),
             "time": label, "provider": provider, "service": service}
            for day in days for clock, label, provider, service in times
        }
        self.bookings = {}
        self.lock = Lock()

    def state(self):
        with self.lock:
            taken = set(self.bookings.values())
            return {"slots": [dict(slot, available=key not in taken)
                              for key, slot in self.slots.items()],
                    "bookings": [{"id": key, "slot": self.slots[slot]}
                                 for key, slot in self.bookings.items()]}

    def _target(self, slot_id):
        if not isinstance(slot_id, str) or slot_id not in self.slots:
            raise DemoError(400, "Choose an available time from the schedule.")

    def book(self, slot_id):
        with self.lock:
            self._target(slot_id)
            if slot_id in self.bookings.values():
                raise DemoError(409, "That time is no longer available. Choose another.")
            key = uuid4().hex
            self.bookings[key] = slot_id
            return key

    def move(self, key, slot_id):
        with self.lock:
            if key not in self.bookings:
                raise DemoError(404, "This booking no longer exists.")
            self._target(slot_id)
            if self.bookings[key] == slot_id:
                return
            if slot_id in self.bookings.values():
                raise DemoError(409, "That time is no longer available. Your booking is unchanged.")
            self.bookings[key] = slot_id

    def cancel(self, key):
        with self.lock:
            if key not in self.bookings:
                raise DemoError(404, "This booking no longer exists.")
            del self.bookings[key]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        # There is no personal information in the system; suppress routine request logs.
        pass

    def send(self, status, body, mime):
        self.send_response(status)
        self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status, value):
        self.send(status, json.dumps(value).encode("utf-8"), "application/json")

    def mutation_guard(self):
        # Browser cross-origin writes are not part of the local demo.
        origin = self.headers.get("Origin")
        if origin and origin != "http://" + self.headers.get("Host", ""):
            raise DemoError(403, "This demo only accepts requests from its own page.")

    def slot_id(self):
        if self.headers.get_content_type() != "application/json":
            raise DemoError(415, "Use JSON for booking requests.")
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 1024:
                raise ValueError
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict) or set(data) != {"slotId"}:
                raise ValueError
            return data["slotId"]
        except (UnicodeError, ValueError):
            raise DemoError(400, "Send exactly one valid slotId.") from None

    def route(self, method):
        path = urlsplit(self.path).path
        try:
            if method == "GET" and path in ASSETS:
                file, mime = ASSETS[path]
                return self.send(200, (STATIC / file).read_bytes(), mime)
            if method == "GET" and path == "/api/schedule":
                return self.send_json(200, self.server.schedule.state())
            if method == "POST" and path == "/api/bookings":
                self.mutation_guard()
                key = self.server.schedule.book(self.slot_id())
                return self.send_json(201, {"id": key})
            match = BOOKING_PATH.fullmatch(path)
            if match and method in ("PATCH", "DELETE"):
                self.mutation_guard()
                if method == "PATCH":
                    self.server.schedule.move(match[1], self.slot_id())
                    return self.send_json(200, {"id": match[1]})
                self.server.schedule.cancel(match[1])
                return self.send_json(200, {"cancelled": True})
            raise DemoError(404, "This demo page or booking endpoint does not exist.")
        except DemoError as e:
            self.send_json(e.status, {"error": e.message})

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def do_PATCH(self):
        self.route("PATCH")

    def do_DELETE(self):
        self.route("DELETE")


def make_server(port=8000, schedule=None):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.schedule = schedule or Schedule()
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    with make_server(args.port) as server:
        print(f"Open http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
