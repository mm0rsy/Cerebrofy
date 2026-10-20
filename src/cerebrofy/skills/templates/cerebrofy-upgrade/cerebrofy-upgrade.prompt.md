Plan a dependency upgrade from the Cerebrofy graph before changing the version pin.

Preferred: cerebrofy_upgrade(package="<pkg>", from_version="<old>", to_version="<new>")
Breaking only: cerebrofy_upgrade(package="<pkg>", breaking_only=true)
Auto-fix selected steps: cerebrofy_upgrade(package="<pkg>", auto_fix=true, step=[1, 2])
Post-upgrade check: cerebrofy_upgrade(package="<pkg>", validate=true)

Decision rules:
- Start with the plan (auto_fix=false). Read the ordered steps before touching code.
- Update `base` steps first (base classes / class Config), then call sites by blast radius.
- Never auto-fix structural changes (`class Config` → `model_config`) — rewrite those manually.
- Treat auto_fix_results errors as blockers for that file; inspect and edit manually.
- After the upgrade, call validate=true and do not merge while any `file:line` remains.
- NO_INDEX → run cerebrofy build. MANIFEST_NOT_FOUND / VERSION_NOT_FOUND → provide a
  custom manifest with the CLI (`--manifest` / `--diff`); the MCP tool is offline by design.
