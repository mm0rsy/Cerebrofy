import json
import sqlite3
import threading
import time
import urllib.request

import pytest
from click.testing import CliRunner

from cerebrofy.cli import main


@pytest.fixture
def repo_with_index(tmp_path):
    config_dir = tmp_path / ".cerebrofy"
    db_dir = config_dir / "db"
    db_dir.mkdir(parents=True)
    # lobes mapping so _file_to_lobe resolves 'mod.py' → 'mod' (not filtered as unknown)
    (config_dir / "config.yaml").write_text("version: 1\nproject: test\nlobes:\n  mod: mod\n")
    db = db_dir / "cerebrofy.db"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE nodes (
            id TEXT, name TEXT, type TEXT,
            file TEXT, line_start INTEGER, line_end INTEGER, docstring TEXT
        );
        CREATE TABLE edges (src_id TEXT, dst_id TEXT, rel_type TEXT);
        INSERT INTO nodes VALUES ('mod::alpha','alpha','function','mod.py',1,5,NULL);
        INSERT INTO nodes VALUES ('mod::beta', 'beta', 'function','mod.py',7,12,NULL);
        INSERT INTO edges VALUES ('mod::alpha','mod::beta','CALLS');
    """)
    con.commit()
    con.close()
    return tmp_path


def test_viz_errors_without_init(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(main, ["viz", "--no-open"])
    assert result.exit_code != 0
    assert "cerebrofy init" in result.output


def test_viz_errors_without_build(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".cerebrofy").mkdir()
    (tmp_path / ".cerebrofy" / "config.yaml").write_text("version: 1\n")
    result = CliRunner().invoke(main, ["viz", "--no-open"])
    assert result.exit_code != 0
    assert "cerebrofy build" in result.output


def test_viz_serves_data_endpoint(repo_with_index, monkeypatch):
    monkeypatch.chdir(repo_with_index)
    PORT = 17360

    def run():
        CliRunner().invoke(main, ["viz", "--port", str(PORT), "--no-open"])

    t = threading.Thread(target=run, daemon=True)
    t.start()

    # Poll until server responds or timeout (CI can be slow)
    data = None
    for _ in range(40):
        time.sleep(0.25)
        try:
            with urllib.request.urlopen(f"http://localhost:{PORT}/data", timeout=2) as resp:
                data = json.loads(resp.read())
            break
        except Exception:
            continue
    assert data is not None, "viz server did not respond within 10 seconds"

    assert data["meta"]["node_count"] == 2
    assert data["meta"]["edge_count"] == 1
    assert all(
        n["region"] in ["frontal", "parietal", "temporal", "occipital", "limbic"]
        for n in data["nodes"]
    )
