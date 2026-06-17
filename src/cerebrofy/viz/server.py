"""Local HTTP server: serves viz/static/ files and a /data JSON endpoint."""
from __future__ import annotations

import threading
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from cerebrofy.viz.graph_export import VizGraph


class _VizHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: object, graph_json: str, **kwargs: object) -> None:
        self._graph_json = graph_json
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:
        if self.path == "/data":
            body = self._graph_json.encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        else:
            super().do_GET()

    def log_message(self, fmt: str, *args: object) -> None:
        pass  # silence per-request logs


class VizServer:
    def __init__(
        self, static_dir: Path, graph: VizGraph, port: int = 7331
    ) -> None:
        self.static_dir = static_dir
        self.graph = graph
        self.port = port
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> int:
        """Start in background thread. Returns actual port used."""
        graph_json = self.graph.to_json()
        handler = partial(
            _VizHandler,
            directory=str(self.static_dir),
            graph_json=graph_json,
        )
        for offset in range(10):
            candidate = self.port + offset
            try:
                self._server = HTTPServer(("127.0.0.1", candidate), handler)
                self.port = candidate
                break
            except OSError:
                continue
        else:
            raise RuntimeError(
                f"Could not bind to any port in {self.port}–{self.port + 9}"
            )
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )
        self._thread.start()
        return self.port

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server = None
