"""Static server for design prototypes that disables browser caching, so edits show up on refresh."""
import functools
import http.server
import sys


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 4311
    directory = sys.argv[2] if len(sys.argv) > 2 else "designs"
    handler = functools.partial(NoCacheHandler, directory=directory)
    http.server.ThreadingHTTPServer(("", port), handler).serve_forever()
