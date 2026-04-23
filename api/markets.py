from http.server import BaseHTTPRequestHandler
from urllib import parse

from api.common import with_error_boundary
from server import json_response, markets_payload


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = parse.urlparse(self.path)
        query = parse.parse_qs(parsed.query)
        refresh = query.get("refresh", ["0"])[0] == "1"
        return with_error_boundary(self, lambda: json_response(self, 200, markets_payload(refresh=refresh)))
