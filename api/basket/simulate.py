from http.server import BaseHTTPRequestHandler

from api.common import with_error_boundary
from server import json_response, read_json, simulate_basket


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        return with_error_boundary(
            self,
            lambda: json_response(self, 200, simulate_basket(read_json(self))),
        )
