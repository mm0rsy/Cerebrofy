# Semantic Release — Design Spec

**Date:** 2026-06-21  
**Status:** Approved  
**Branch:** To be implemented on a fresh branch from master

---

## Problem

Releases require a manual `git tag v<version> && git push origin v<version>` before anything publishes to PyPI. With conventional commits already in use, the version number is implicit in every commit — semantic-release makes it explicit automatically.

---

## Goal

On every merge to master, automatically:
1. Analyze conventional commits since the last tag
2. Determine the next semantic version (patch / minor / major)
3. Bump `version` in `pyproject.toml`
4. Update `CHANGELOG.md`
5. Commit both files back to master
6. Push the new tag
7. Let the existing `release.yml` pick up the tag and publish to PyPI

No manual tagging. No version maintenance. No separate CHANGELOG editing.

---

## Architecture

```
push to master
      │
      ▼
semantic-release.yml
  └─ python-semantic-release version --push
        ├─ bumps pyproject.toml
        ├─ writes CHANGELOG.md
        ├─ commits both (via RELEASE_TOKEN PAT)
        └─ pushes tag vX.Y.Z
                │
                ▼
          release.yml  (triggered by tag push)
            ├─ test gate
            ├─ uv build  (wheel + sdist)
            └─ publish to PyPI + GitHub Release
```

The two workflows are independent. `semantic-release.yml` owns versioning; `release.yml` owns publishing. The tag is the handoff point.

---

## Changes

### New: `.github/workflows/semantic-release.yml`

Triggers on `push` to `master`. Full git history is required (`fetch-depth: 0`) so semantic-release can find the previous tag. Uses the `RELEASE_TOKEN` PAT so the tag push triggers `release.yml` (the default `GITHUB_TOKEN` cannot trigger other workflows).

```yaml
name: Semantic Release

on:
  push:
    branches:
      - master

concurrency:
  group: semantic-release
  cancel-in-progress: false   # never cancel a release in flight

jobs:
  release:
    name: Semantic Release
    runs-on: ubuntu-22.04
    permissions:
      contents: write

    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
          token: ${{ secrets.RELEASE_TOKEN }}

      - uses: astral-sh/setup-uv@v4
        with:
          enable-cache: true
          cache-dependency-glob: "uv.lock"

      - name: Install python-semantic-release
        run: uv tool install python-semantic-release

      - name: Run semantic release
        env:
          GH_TOKEN: ${{ secrets.RELEASE_TOKEN }}
        run: semantic-release version --push
```

### Modified: `pyproject.toml`

Add `[tool.semantic_release]` section:

```toml
[tool.semantic_release]
version_toml = ["pyproject.toml:project.version"]
branch = "master"
changelog_file = "CHANGELOG.md"
commit_message = "chore(release): v{version} [skip ci]"
upload_to_vcs_release = false
```

| Key | Value | Reason |
|-----|-------|--------|
| `version_toml` | `["pyproject.toml:project.version"]` | The single source of truth for the version |
| `branch` | `"master"` | Only release from master |
| `changelog_file` | `"CHANGELOG.md"` | Auto-generated; committed alongside the version bump |
| `commit_message` | `"chore(release): v{version} [skip ci]"` | `[skip ci]` prevents CI re-running on the bump commit itself |
| `upload_to_vcs_release` | `false` | GitHub Release creation stays in `release.yml` |

### Modified: `.github/workflows/release.yml`

Remove the "Sync version from tag" step:

```yaml
# DELETE THIS ENTIRE STEP:
- name: Sync version from tag
  run: |
    VERSION="${GITHUB_REF_NAME#v}"
    sed -i "s/^version = \".*\"/version = \"${VERSION}\"/" pyproject.toml
    sed -i "s/__version__ = \".*\"/__version__ = \"${VERSION}\"/" src/cerebrofy/__init__.py
```

`pyproject.toml` already has the correct version when the tag fires (semantic-release wrote it). `src/cerebrofy/__init__.py` uses `importlib.metadata.version()` — no hardcoded string to patch.

### New: `CHANGELOG.md`

Generated and committed automatically on the first release after this is set up. Grouped by commit type (`feat`, `fix`, `refactor`, etc.) with links to commits. Maintained by semantic-release from this point forward — do not edit manually.

---

## Version Bump Rules

Derived from the Angular/Conventional Commits parser (default in python-semantic-release):

| Commit prefix | Bump |
|---------------|------|
| `fix(...):` | patch — `1.0.5 → 1.0.6` |
| `feat(...):` | minor — `1.0.5 → 1.1.0` |
| `BREAKING CHANGE` in footer | major — `1.0.5 → 2.0.0` |
| `chore:`, `docs:`, `refactor:`, `test:` | no release |

The `(#23)` scope format used in this repo is valid — semantic-release treats it as a scope label and includes it in CHANGELOG grouping.

---

## One-Time GitHub Setup (manual, by repo owner)

1. **Create a fine-grained PAT**  
   GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens → New token  
   - Resource owner: `mm0rsy`  
   - Repository access: Cerebrofy only  
   - Permission: **Contents → Read and write**

2. **Add as a repo secret**  
   Cerebrofy repo → Settings → Secrets and variables → Actions → New repository secret  
   - Name: `RELEASE_TOKEN`  
   - Value: paste the PAT

No branch protection changes needed. The PAT push is treated as a regular user push by GitHub.

---

## What Does Not Change

- `release.yml` trigger (still fires on `v*.*.*` tag push)
- PyPI publishing mechanism (OIDC Trusted Publisher, unchanged)
- GitHub Release creation (still in `release.yml` via `softprops/action-gh-release`)
- Test gate in `release.yml` (still runs before build and publish)
- Commit message convention (already conventional commits)

---

## Out of Scope

- Pre-release channels (`alpha`, `beta`, `rc`) — can be added later via `[tool.semantic_release.branches]`
- Slack / Linear release notifications — can be added via post-release workflow step
- Dry-run / preview mode — available via `semantic-release version --print` locally
