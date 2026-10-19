# Security Model

Cerebrofy runs locally next to your code and your repositories. This document
records the guarantees the code actually enforces, the configuration that
controls them, and the assumptions that are **not** enforced.

---

## 1. Repository-root resolution and the MCP launch boundary (C1)

Cerebrofy databases live in `.cerebrofy/db/` next to the repository. A
manipulated working directory used to be able to silently redirect a running
server at a *different* project's databases. Root resolution now has one
implementation (`src/cerebrofy/utils/paths.py`) with a strict order:

1. **Explicit pin** — `cerebrofy mcp --root <path>` or the `CEREBROFY_ROOT`
   env var. The walk-up is skipped entirely; an invalid pin fails closed
   (`InvalidRepoRootError`) instead of falling back to the CWD.
2. **CWD walk-up** — from `os.getcwd()`, upward until `.cerebrofy/config.yaml`
   is found. This preserves the documented CWD routing (one MCP entry serving
   several repos).

The walk-up is clipped by a **launch boundary** set once at MCP start-up:

| Launched from | Boundary | Effect |
|---|---|---|
| Inside a Cerebrofy project | That project root | Per-call CWD routing works inside the project; sibling projects and parents are unreachable. |
| A non-project directory (e.g. a workspace root) | The launch CWD | Repos *beneath* the launch directory are served; siblings and parents are not. |

`CEREBROFY_ROOT` is also validated against the boundary and rejected when it
points outside it. CLI commands are unaffected (they resolve from their own
CWD, as documented).

> **Caveat:** a server launched at a workspace root intentionally serves every
> repo beneath it. If that broad scope is not what you want, pin one project
> with `--root` / `CEREBROFY_ROOT`.

---

## 2. Database integrity sidecar (`<db>.sha256`)

`cerebrofy build` and `cerebrofy update` write a SHA256 sidecar
(`cerebrofy.db.sha256`) after their final database writes and after the writing
connection closes — so WAL frames have been checkpointed before the file is
hashed. The sidecar is written atomically (temp file + rename).

Read paths verify the digest according to `database.integrity_check` in
`.cerebrofy/config.yaml`:

| Value | Behaviour on mismatch |
|---|---|
| `off` | Skip the check entirely. |
| `warn` *(default)* | Log a warning; the read proceeds. |
| `fail` | Raise `IntegrityError` (`[INTEGRITY_ERROR]`). |

A **missing sidecar is a no-op**, so databases built before this feature remain
readable. Verification is cached per `(mtime_ns, size)` fingerprint of the
database and sidecar files, so repeated reads in one process stay cheap.

> **What this does and does not prove.** The digest detects a `.db` file that
> changed after the last build/update — the at-rest tampering case. It is
> best-effort: WAL checkpoints and concurrent writers can change file bytes
> during a read (the default `warn` mode never blocks for that reason), and it
> is not a signature — an attacker who can rewrite the database can rewrite the
> sidecar too. Do not treat it as tamper-proofing or as a substitute for
> backups.

---

## 3. `sqlite-vec` supply chain (n11)

Vector search loads the `sqlite-vec` native extension in-process. Loading a
native extension means executing trusted native code, so Cerebrofy pins the
dependency explicitly and re-checks the installed version at load time:

* `pyproject.toml` pins `sqlite-vec>=0.1.6,<0.2.0` (locked in `uv.lock`);
* every load path goes through `cerebrofy.db.vec.load_sqlite_vec`
  (`db/connection.py`, `search/hybrid.py`, `memory/store.py`,
  `session/_recorder/schema.py`), which raises `RuntimeError` with remediation
  when the installed version falls outside that range.

The assumption left to the operator: wheels are installed from a trusted index
(`uv sync` / `uv lock`), and the environment has not been modified after that.

---

## 4. Database write serialization (n13)

Multi-statement writes to `cerebrofy.db` go through
`cerebrofy.db.connection.write_transaction`:

* a process-wide `threading.RLock` serializes in-process writers;
* `BEGIN IMMEDIATE` takes the SQLite reserved lock up-front, avoiding late
  `database is locked` failures;
* nested use raises `RuntimeError("write_transaction cannot be nested")`
  instead of silently committing a partial transaction.

Reads stay lock-free. Session recording additionally serializes writes on its
shared `check_same_thread=False` connection with its own middleware lock;
SQLite's per-connection mutex alone is not sufficient for application-level
transactions. Details: `docs/db-schema.md`.

---

## 5. Data stays local

Sessions, memories, and the index are regular local SQLite databases. Session
recording is opt-in (`record_sessions: true`), local-only, and event payloads
are truncated and redacted (see `docs/configuration.md`). Cerebrofy does not
send repository contents anywhere.
