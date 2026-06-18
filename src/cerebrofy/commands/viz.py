"""cerebrofy viz — serve interactive 3D brain visualization in the browser."""
from __future__ import annotations

import time
import webbrowser
from pathlib import Path

import rich_click as click

from cerebrofy.viz.graph_export import export_graph
from cerebrofy.viz.server import VizServer

_STATIC_DIR = Path(__file__).parent.parent / "viz" / "static"


@click.command("viz")
@click.option("--port", default=7331, show_default=True, help="Port to serve on.")
@click.option("--no-open", is_flag=True, help="Start server without opening browser.")
def cerebrofy_viz(port: int, no_open: bool) -> None:
    """Open interactive 3D brain visualization of the indexed codebase."""
    config_path = Path(".cerebrofy") / "config.yaml"
    if not config_path.exists():
        raise click.ClickException(
            "No .cerebrofy/ found. Run cerebrofy init first."
        )

    db_path = Path(".cerebrofy") / "db" / "cerebrofy.db"
    if not db_path.exists():
        raise click.ClickException(
            "No index found. Run cerebrofy build first."
        )

    click.echo("Reading graph from cerebrofy.db…")
    graph = export_graph(db_path)
    click.echo(
        f"  {graph.meta.node_count} nodes · "
        f"{graph.meta.edge_count} edges · "
        f"{graph.meta.lobe_count} lobes"
    )

    server = VizServer(_STATIC_DIR, graph, port=port)
    actual_port = server.start()
    url = f"http://localhost:{actual_port}"
    click.echo(f"Serving at {url}  (Ctrl+C to stop)")

    if not no_open:
        webbrowser.open(url)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.stop()
        click.echo("\nStopped.")
