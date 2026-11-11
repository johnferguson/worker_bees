"""A tiny web server shared by the worker_bees web pages.

ZZZ_schedule_editor.py and ZZZ_monitor.py each start one. It only uses
Python's standard library. By default it only answers this computer
(127.0.0.1), so other PCs on the network can't reach it; --host 0.0.0.0
opens it to the network.
"""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WEB_FOLDER = Path(__file__).parent / "web"
LOCAL_NAMES = {"127.0.0.1", "localhost", "::1"}


class Handler(BaseHTTPRequestHandler):
    """Serves one page from the web folder plus a few JSON addresses.

    Each script makes a subclass and sets:
      page       the HTML file in the web folder shown at /
      get_api    {"/api/...": function()}            -> data to send back
      post_api   {"/api/...": function(request data)} -> (status, data)
    """

    page = None
    get_api = {}
    post_api = {}

    def log_message(self, format, *args):
        pass  # keep the console quiet

    def host_is_allowed(self):
        """When only this computer may connect, only answer to its own names.

        This stops a web page from pointing a name of its own at 127.0.0.1 to
        get round the browser's protections.
        """
        if self.server.server_address[0] not in LOCAL_NAMES:
            return True
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        return host in LOCAL_NAMES

    def send(self, status, body, content_type):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, status, data):
        self.send(status, json.dumps(data), "application/json")

    def do_GET(self):
        if not self.host_is_allowed():
            return self.send(403, "Forbidden", "text/plain")
        path = self.path.split("?", 1)[0]
        if path == "/":
            return self.send(200, (WEB_FOLDER / self.page).read_text(encoding="utf-8"), "text/html; charset=utf-8")
        if path in self.get_api:
            return self.send_json(200, self.get_api[path]())
        self.send(404, "Not found", "text/plain")

    def do_POST(self):
        # The page sends this header with every change. A browser won't let
        # another website send it, so only our own page can make changes.
        if not self.host_is_allowed() or self.headers.get("X-Worker-Bees") != "1":
            return self.send(403, "Forbidden", "text/plain")
        handler = self.post_api.get(self.path)
        if handler is None:
            return self.send(404, "Not found", "text/plain")
        try:
            length = int(self.headers.get("Content-Length") or 0)
            request = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self.send_json(400, {"error": "The request wasn't valid JSON."})
        status, data = handler(request)
        self.send_json(status, data)


def serve(handler, default_port, title):
    parser = argparse.ArgumentParser(description=title)
    parser.add_argument("--port", type=int, default=default_port, help=f"default {default_port}")
    parser.add_argument("--host", default="127.0.0.1",
                        help="default 127.0.0.1 (this computer only); 0.0.0.0 lets other PCs open it")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), handler)
    shown = "localhost" if args.host in LOCAL_NAMES else args.host
    print(f"{title}: open http://{shown}:{args.port} in a browser. Ctrl+C stops it.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
