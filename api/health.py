from http.server import BaseHTTPRequestHandler

from api.common import with_error_boundary
from server import DB_PATH, json_response, utc_now_iso


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        return with_error_boundary(
            self,
            lambda: json_response(self, 200, {"ok": True, "time": utc_now_iso(), "db": str(DB_PATH)}),
        )
