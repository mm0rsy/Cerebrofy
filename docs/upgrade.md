# Dependency Upgrade Navigator

`cerebrofy upgrade` maps every place your indexed code uses a dependency's
changing API, scores the migration effort, emits a dependency-ordered plan, and
can apply precise AST auto-fixes and validate the result afterwards.

It is **offline-first**: Cerebrofy never contacts PyPI, GitHub, or a changelog
service. Breaking changes come from a curated manifest that ships with Cerebrofy
or from a YAML/JSON file you provide.

```bash
cerebrofy upgrade pydantic --from v1 --to v2
cerebrofy upgrade requests --breaking-only
cerebrofy upgrade pydantic --manifest ./pydantic-custom.yaml --auto-fix --step 1,2
cerebrofy upgrade pydantic --validate
```

## Pipeline

```
manifest (curated or --manifest/--diff)
        │
        ▼
scanner.py ── indexed Python files (nodes.file) + ast import detection
        │      + RUNTIME_BOUNDARY edges to external::<package>
        │      → per-change UsageSite list (neuron id, file, line)
        ▼
planner.py ── base/config steps → call sites by blast radius desc → validators/other
        │      effort = Σ(1 + depth-2 blast radius × 0.1)
        │      2.5 minutes per effort point → total_effort_hours
        │      risk LOW/MEDIUM/HIGH
        ▼
fixer.py  ── AST transforms for attribute calls, decorators, import symbols
        │      edits restricted to scanned site lines; re-parse before writing;
        │      invalid files are left untouched
        ▼
validator.py ── rescan without an import gate → PASS/FAIL + file:line
```

The blast radius comes from the real graph (`analysis/blast_radius.py`,
depth-2 BFS, `RUNTIME_BOUNDARY` excluded per Law II). No schema change was
needed; the feature reads the existing `nodes` and `edges` tables.

## Manifest format

```yaml
package: pydantic
from_version: ">=1.0,<2.0"
to_version: ">=2.0"
changes:
  - type: rename          # rename | removed | changed
    old: ".dict()"
    new: ".model_dump()"
    severity: breaking    # breaking | deprecated
```

Optional fixer metadata keeps transforms accurate:

```yaml
    category: call        # base | call | validator | other
    match: '\.dict\s*\(' # explicit detection regex
    replacement: ".model_dump("
    auto_fix: true        # default: only safe rename shapes are auto-fixable
```

`--diff` is an alias for `--manifest` and accepts the same YAML or a JSON API
diff. A bare JSON list of changes is accepted when a package name is supplied on
the command line. Changes may use `old_api`/`new_api` instead of `old`/`new`.

`--manifest-dir DIR` searches additional manifests before the bundled set.
Cerebrofy also looks in `.cerebrofy/upgrades/` automatically.

Version constraints are evaluated offline with a simple numeric-prefix
comparison. If the package is known but no manifest covers the requested pair,
the command returns `VERSION_NOT_FOUND`; if the package has no manifest at all
it returns `MANIFEST_NOT_FOUND`.

## Bundled manifests

| Package | Range | Notes |
|---|---|---|
| `pydantic` | v1 → v2 | `.dict()`, `.json()`, `.parse_obj()`, `@validator`, `class Config` |
| `requests` | 2.x → 3.x | `requests.packages`, `requests.compat`, deprecated utils shims |

These are **curated, not exhaustive**. They cover the mechanical,
high-frequency changes; always cross-check the library's official migration
guide. Community manifests can be added as files and passed with `--manifest`.

## CLI

```bash
cerebrofy upgrade PACKAGE [--from VERSION] [--to VERSION] [--breaking-only]
                         [--manifest PATH] [--manifest-dir PATH] [--diff PATH]
                         [--auto-fix] [--step 1,2] [--validate]
                         [--format markdown|json]
```

- Default output is Markdown; `--format json` emits the MCP schema.
- `--breaking-only` filters `severity: deprecated` changes. It is an opt-in CLI
  flag (default: false), so an interactive `cerebrofy upgrade pydantic` shows the
  complete curated plan. The MCP tool defaults `breaking_only` to true instead:
  agent calls should stay focused on breaking work and avoid spending context on
  deprecated-only noise. Pass `"breaking_only": false` to mirror the CLI.
- `--auto-fix` is an explicit opt-in. Without `--step`, only auto-fixable steps
  run; selecting a non-mechanical step reports an error instead of guessing.
- `--validate` alone rescans all indexed Python files and exits non-zero when
  old patterns remain. Combined with `--auto-fix`, it validates right after the
  fixes.

## MCP tool

`cerebrofy_upgrade` mirrors the CLI:

```json
{
  "package": "pydantic",
  "from_version": "1.10.0",
  "to_version": "2.0.0",
  "breaking_only": true,
  "auto_fix": false,
  "step": [1, 2],
  "validate": false,
  "format": "markdown"
}
```

Output fields: `package`, `from_version`, `to_version`, `breaking_changes`,
`steps`, `total_effort_hours`, `risk`, `auto_fix_results` (plus `validation`
when requested). Errors use `[CODE] message` with `NO_INDEX`,
`PACKAGE_NOT_USED`, `MANIFEST_NOT_FOUND`, and `VERSION_NOT_FOUND`.

## Auto-fix safety

Supported transforms:

| Shape | Example |
|---|---|
| Attribute call | `obj.dict()` → `obj.model_dump()` |
| Module-qualified call | `pkg.old_name(...)` → `pkg.new_name(...)` |
| Decorator | `@validator` → `@field_validator` |
| Import symbol | `from pydantic import validator` → `field_validator` |

Structural rewrites such as `class Config` → `model_config = ConfigDict(...)`
are deliberately **not** auto-fixed. Every changed file is re-parsed with
`ast.parse`; if the result would be invalid, the file is left unchanged and the
error is reported in `auto_fix_results`.

## Deferred

- **Automatic PyPI/changelog fetching** (`--detect`, release-note parsing) is
  not implemented. It would require network access and a release API; manifests
  are the supported offline path.
- **Semantic-search supplement** to API detection is not used. Exact import +
  pattern scanning is deterministic and works without the fastembed model.
- **Community manifest package** (`pip install cerebrofy[upgrades]`) is replaced
  by bundled package data plus `--manifest-dir`; no new pip extra is required.
