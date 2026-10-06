"""Tiny local HTTP endpoint for LaserLifeHandler.RealDoSend: answers every POST with a
fixed body and appends the request body to a file. Prints its port on stdout.

argv[1]: response body, argv[2]: file receiving the posted bodies
"""
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

reply, log = sys.argv[1].encode(), sys.argv[2]


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        with open(log, "ab") as f:
            f.write(body + b"\n")
        self.send_response(200)
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)

    def log_message(self, *args):
        pass


srv = HTTPServer(("127.0.0.1", 0), H)
print(srv.server_address[1], flush=True)
srv.serve_forever()
