"""Shared fixtures for AI Review Copilot tests (Idea #17)."""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

MEMORIES_WARNING = (
    "Clock skew breaks token expiry if drift > 30s — always use server_time"
)


def write_config(root: Path) -> None:
    config_dir = root / ".cerebrofy"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.yaml").write_text(
        "lobes:\n"
        "  auth: auth/\n"
        "  api: api/\n"
        "  billing: billing/\n"
        "  middleware: middleware/\n"
        "  tests: tests/\n"
        "tracked_extensions: [.py]\n"
        "embedding_model: local\n",
        encoding="utf-8",
    )


def write_rules(root: Path) -> None:
    (root / ".cerebrofy" / "arch-rules.yaml").write_text(
        "rules:\n"
        "  - name: no-auth-to-billing\n"
        "    description: Auth must not call billing directly\n"
        "    severity: error\n"
        "    check:\n"
        "      no_edge:\n"
        "        from_lobe: auth\n"
        "        to_lobe: billing\n",
        encoding="utf-8",
    )


def make_index_db(root: Path) -> sqlite3.Connection:
    """Create a small file-backed index exercising every review check."""
    db_dir = root / ".cerebrofy" / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_dir / "cerebrofy.db")
    conn.executescript(
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        INSERT INTO meta VALUES ('schema_version', '1');
        CREATE TABLE nodes (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            file TEXT NOT NULL,
            type TEXT,
            line_start INTEGER,
            line_end INTEGER,
            signature TEXT,
            docstring TEXT,
            hash TEXT
        );
        CREATE TABLE edges (
            src_id TEXT,
            dst_id TEXT,
            rel_type TEXT NOT NULL,
            file TEXT,
            PRIMARY KEY (src_id, dst_id, rel_type)
        );
        """
    )
    nodes = [
        ("auth/tokens.py::validate_token", "validate_token", "auth/tokens.py", 10, 20),
        ("auth/tokens.py::refresh_token", "refresh_token", "auth/tokens.py", 22, 30),
        ("middleware/auth.py::route_guard", "route_guard", "middleware/auth.py", 5, 9),
        ("api/views.py::oauth_callback", "oauth_callback", "api/views.py", 30, 40),
        ("tests/test_tokens.py::test_validate", "test_validate", "tests/test_tokens.py", 1, 8),
        ("billing/charge.py::charge", "charge", "billing/charge.py", 1, 12),
        ("api/views.py::charge_endpoint", "charge_endpoint", "api/views.py", 50, 60),
        ("auth/tokens.py::token_module", "token_module", "auth/tokens.py", 1, 1),
    ]
    conn.executemany(
        "INSERT INTO nodes (id, name, file, type, line_start, line_end) "
        "VALUES (?, ?, ?, 'function', ?, ?)",
        nodes,
    )
    conn.execute(
        "UPDATE nodes SET type = 'module' WHERE id = 'auth/tokens.py::token_module'"
    )
    edges = [
        ("middleware/auth.py::route_guard", "auth/tokens.py::validate_token"),
        ("api/views.py::oauth_callback", "auth/tokens.py::validate_token"),
        ("tests/test_tokens.py::test_validate", "auth/tokens.py::validate_token"),
        ("auth/tokens.py::validate_token", "billing/charge.py::charge"),
        ("api/views.py::charge_endpoint", "billing/charge.py::charge"),
        ("auth/tokens.py::refresh_token", "auth/tokens.py::validate_token"),
    ]
    conn.executemany(
        "INSERT INTO edges (src_id, dst_id, rel_type, file) VALUES (?, ?, 'LOCAL_CALL', ?)",
        [(src, dst, src.split("::")[0]) for src, dst in edges],
    )
    conn.commit()
    return conn


def write_memories(root: Path) -> None:
    db_dir = root / ".cerebrofy" / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_dir / "memories.db")
    conn.execute(
        "CREATE TABLE memories ("
        "id TEXT PRIMARY KEY, neuron_id TEXT, lobe TEXT, type TEXT, title TEXT, "
        "body TEXT, author TEXT, created_ts INTEGER, tags TEXT, decay_score REAL, "
        "status TEXT)"
    )
    conn.execute(
        "INSERT INTO memories VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "mem-1",
            "auth/tokens.py::validate_token",
            "auth",
            "warning",
            "Use server_time, not datetime.now()",
            MEMORIES_WARNING,
            "alice@co.com",
            1780000000,
            "auth,time",
            1.0,
            "active",
        ),
    )
    conn.commit()
    conn.close()


def git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def setup_git_repo(root: Path) -> None:
    git("init", "-b", "main", cwd=root)
    git("config", "user.email", "test@cerebrofy.test", cwd=root)
    git("config", "user.name", "CerebrofyTest", cwd=root)
    (root / "auth").mkdir(parents=True, exist_ok=True)
    (root / "auth" / "tokens.py").write_text(
        "def validate_token(token):\n    return bool(token)\n\n"
        "def refresh_token(token):\n    return validate_token(token)\n",
        encoding="utf-8",
    )
    (root / "billing").mkdir(parents=True, exist_ok=True)
    (root / "billing" / "charge.py").write_text(
        "def charge(amount):\n    return amount\n", encoding="utf-8"
    )
    git("add", ".", cwd=root)
    git("commit", "-m", "initial", cwd=root)


def change_tracked_files(root: Path) -> None:
    (root / "auth" / "tokens.py").write_text(
        "def validate_token(token):\n    return bool(token) and len(token) > 0\n\n"
        "def refresh_token(token):\n    return validate_token(token)\n",
        encoding="utf-8",
    )
    (root / "billing" / "charge.py").write_text(
        "def charge(amount):\n    return max(amount, 0)\n", encoding="utf-8"
    )


def make_repo(root: Path) -> sqlite3.Connection:
    write_config(root)
    write_rules(root)
    write_memories(root)
    return make_index_db(root)
