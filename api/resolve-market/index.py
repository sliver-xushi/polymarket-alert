from http.server import BaseHTTPRequestHandler
from urllib import parse

from api.common import with_error_boundary
from server import json_response, resolve_market_input


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = parse.urlparse(self.path)
        query = parse.parse_qs(parsed.query)
        value = query.get("input", [""])[0]
        return with_error_boundary(
            self,
            lambda: json_response(self, 200, {"market": resolve_market_input(value)}),
        )
