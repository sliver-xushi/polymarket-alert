from http.server import BaseHTTPRequestHandler
from urllib import parse

from api.common import with_error_boundary
from server import fetch_tracker_for_market, json_response


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = parse.urlparse(self.path)
        query = parse.parse_qs(parsed.query)
        return with_error_boundary(
            self,
            lambda: json_response(
                self,
                200,
                fetch_tracker_for_market(
                    query.get("slug", [""])[0],
                    query.get("startTime", [""])[0],
                    query.get("endTime", [""])[0],
                ),
            ),
        )
