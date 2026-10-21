"""The fixture web app (M1.5): a cart page served with the standard library. `python app.py PORT`."""

import http.server
import sys

PAGE = """<!doctype html>
<title>Cart</title>
<h1>Your cart</h1>
<p data-testid="item-count">3 items</p>
<p data-testid="subtotal">Subtotal: $30.00</p>
"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = PAGE.encode() if self.path == "/" else b"not found"
        self.send_response(200 if self.path == "/" else 404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    http.server.ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
