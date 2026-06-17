import json
import socket
import urllib.request
import pytest
from cerebrofy.viz.graph_export import VizGraph, VizNode, VizEdge, VizMeta
from cerebrofy.viz.server import VizServer


@pytest.fixture
def static_dir(tmp_path):
    (tmp_path / "index.html").write_text("<html>cerebrofy viz</html>")
    return tmp_path


@pytest.fixture
def graph():
    return VizGraph(
        nodes=[VizNode(id="a::b", name="b", type="function",
                       lobe="a", region="frontal", file="a.py", line=1)],
        edges=[VizEdge(src="a::b", dst="a::b", rel="CALLS")],
        meta=VizMeta(repo="test", node_count=1, edge_count=1, lobe_count=1),
    )


@pytest.fixture
def server(static_dir, graph):
    srv = VizServer(static_dir, graph, port=17331)
    srv.start()
    yield srv
    srv.stop()


def test_data_endpoint_returns_json(server):
    with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/data") as r:
        data = json.loads(r.read())
    assert set(data.keys()) == {"nodes", "edges", "meta"}


def test_data_node_has_correct_fields(server):
    with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/data") as r:
        data = json.loads(r.read())
    assert data["nodes"][0]["id"] == "a::b"
    assert data["nodes"][0]["region"] == "frontal"


def test_static_index_served(server):
    with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/index.html") as r:
        assert "cerebrofy viz" in r.read().decode()


def test_port_retry_on_conflict(static_dir, graph):
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 17340))
    blocker.listen(1)
    try:
        srv = VizServer(static_dir, graph, port=17340)
        actual = srv.start()
        assert actual != 17340
        with urllib.request.urlopen(f"http://127.0.0.1:{actual}/index.html") as r:
            assert r.status == 200
        srv.stop()
    finally:
        blocker.close()
