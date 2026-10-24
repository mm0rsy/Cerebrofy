# Dependency Upgrade Navigator

`cerebrofy upgrade` maps every place your indexed code uses a dependency's changing API, scores the migration effort, emits a dependency-ordered plan, and can apply precise AST auto-fixes and validate the result afterwards.

It is **offline-first**: Cerebrofy never contacts PyPI, GitHub, or a changelog service. Breaking changes come from a curated manifest that ships with Cerebrofy or from a YAML/JSON file you provide.

## CLI Reference

```bash
cerebrofy upgrade pydantic --from v1 --to v2
cerebrofy upgrade requests --breaking-only
cerebrofy upgrade pydantic --manifest ./pydantic-custom.yaml --auto-fix --step 1,2
cerebrofy upgrade pydantic --validate
```

- `PACKAGE` — package name (e.g. `pydantic`, `requests`)
- `--from VERSION` — current version (used to select a manifest range)
- `--to VERSION` — target version
- `--breaking-only` — filter `severity: deprecated` changes (default: false on CLI, true on MCP)
- `--manifest PATH` — custom manifest file (YAML or JSON)
- `--manifest-dir PATH` — search additional manifests before the bundled set
- `--diff PATH` — alias for `--manifest`
- `--auto-fix` — apply AST auto-fixes (explicit opt-in)
- `--step 1,2` — only run specific auto-fix steps
- `--validate` — rescan for remaining old patterns
- `--format` — `markdown` (default) or `json`

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

The blast radius comes from the real graph (`analysis/blast_radius.py`, depth-2 BFS, `RUNTIME_BOUNDARY` excluded per Law II). No schema change was needed; the feature reads the existing `nodes` and `edges` tables.

## Manifest Format

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
    match: '\.dict\s*\('  # explicit detection regex
    auto_fix: true        # default: only safe rename shapes are auto-fixable
```

Edits are derived from the AST shape of `old`/`new`; manifests never supply raw textual substitutions. Unknown keys are ignored, so a manifest written for a newer Cerebrofy version still loads.

`--diff` is an alias for `--manifest` and accepts the same YAML or a JSON API diff. A bare JSON list of changes is accepted when a package name is supplied on the command line. Changes may use `old_api`/`new_api` instead of `old`/`new`.

`--manifest-dir DIR` searches additional manifests before the bundled set. Cerebrofy also looks in `.cerebrofy/upgrades/` automatically.

Version constraints are evaluated offline with a simple numeric-prefix comparison.

## Bundled Manifests

| Package | Range | Notes |
|---------|-------|-------|
| `pydantic` | v1 → v2 | `.dict()`, `.json()`, `.parse_obj()`, `@validator`, `class Config` |
| `requests` | 2.x → 3.x | `requests.packages`, `requests.compat`, deprecated utils shims |

These are **curated, not exhaustive**. They cover the mechanical, high-frequency changes; always cross-check the library's official migration guide. Community manifests can be added as files and passed with `--manifest`.

## Error Codes

| Code | Meaning |
|------|---------|
| `MANIFEST_NOT_FOUND` | The manifest file is absent, or no manifest exists for the package. |
| `INVALID_MANIFEST` | The manifest is malformed: invalid YAML/JSON, schema violation, bad regex, or a bad field value. |
| `VERSION_NOT_FOUND` | A manifest for the package exists, but none covers the requested version pair. |
| `NO_INDEX` | No index found — run `cerebrofy build` first. |
| `PACKAGE_NOT_USED` | The package is not used in any indexed file. |

## MCP Tool: `cerebrofy_upgrade`

**Input schema:**

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

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `package` | string | ✅ | Package name (e.g. `pydantic`, `requests`) |
| `from_version` | string | — | Current version (used to select a manifest range) |
| `to_version` | string | — | Target version |
| `breaking_only` | boolean | — | Only report `breaking` changes (default: `true`) |
| `auto_fix` | boolean | — | Apply AST auto-fixes (default: `false`) |
| `step` | integer[] | — | Steps to auto-fix; omit for every auto-fixable step |
| `validate` | boolean | — | Rescan for remaining old patterns (default: `false`) |
| `format` | string | — | `markdown` (default) or `json` |

**Output fields:** `package`, `from_version`, `to_version`, `breaking_changes`, `steps`, `total_effort_hours`, `risk`, `auto_fix_results` (plus `validation` when requested).

## Auto-Fix Safety

Supported transforms:

| Shape | Example |
|-------|---------|
| Attribute call | `obj.dict()` → `obj.model_dump()` |
| Module-qualified call | `pkg.old_name(...)` → `pkg.new_name(...)` |
| Decorator | `@validator` → `@field_validator` |
| Import symbol | `from pydantic import validator` → `field_validator` |

Structural rewrites such as `class Config` → `model_config = ConfigDict(...)` are deliberately **not** auto-fixed. Every changed file is re-parsed with `ast.parse`; if the result would be invalid, the file is left unchanged and the error is reported in `auto_fix_results`.

## Deferred

- **Automatic PyPI/changelog fetching** (`--detect`, release-note parsing) is not implemented. It would require network access and a release API; manifests are the supported offline path.
- **Semantic-search supplement** to API detection is not used. Exact import + pattern scanning is deterministic and works without the fastembed model.

## Related

- [Architecture](../concepts/architecture.md) — `RUNTIME_BOUNDARY` edges excluded from blast radius (Law II)
- [Blast Radius](./blast-radius.md) -- effort estimation uses depth-2 blast radius per usage site