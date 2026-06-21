# Semantic Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automate version bumping, CHANGELOG generation, and tag creation on every push to master using `python-semantic-release`, so PyPI releases happen without manual tagging.

**Architecture:** A new `semantic-release.yml` workflow runs `python-semantic-release` on every master push, bumps `pyproject.toml`, writes `CHANGELOG.md`, commits both, and pushes a tag. The existing `release.yml` fires on that tag and publishes to PyPI — unchanged except for removing the now-redundant version `sed` step.

**Tech Stack:** `python-semantic-release` (uv tool), GitHub Actions, `RELEASE_TOKEN` PAT secret (configured by repo owner before this branch is merged)

---

### Task 1: Create branch from master

**Files:**
- No file changes — branch setup only

- [ ] **Step 1: Checkout master and pull latest**

```bash
git checkout master
git pull origin master
```

Expected: on branch `master`, up to date.

- [ ] **Step 2: Create the feature branch**

```bash
git checkout -b chore/semantic-release
```

Expected: `Switched to a new branch 'chore/semantic-release'`

---

### Task 2: Add `[tool.semantic_release]` config to `pyproject.toml`

**Files:**
- Modify: `pyproject.toml` (append new section at end of file)

- [ ] **Step 1: Verify current version field**

```bash
grep '^version' pyproject.toml
```

Expected output: `version = "2.0.0"` (or current version — whatever is there)

- [ ] **Step 2: Append semantic_release config**

Add this block at the end of `pyproject.toml`:

```toml
[tool.semantic_release]
version_toml = ["pyproject.toml:project.version"]
branch = "master"
changelog_file = "CHANGELOG.md"
commit_message = "chore(release): v{version} [skip ci]"
upload_to_vcs_release = false
```

- [ ] **Step 3: Verify the config is valid TOML**

```bash
python3 -c "import tomllib; tomllib.load(open('pyproject.toml', 'rb')); print('TOML valid')"
```

Expected: `TOML valid`

- [ ] **Step 4: Dry-run semantic-release locally to verify config is picked up**

```bash
uv tool install python-semantic-release
semantic-release version --print
```

Expected: prints the next version (e.g. `2.0.1` or `2.1.0`) without making any changes. If it prints `No release will be made` that is also valid — it means no qualifying commits since the last tag on master.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "chore: configure python-semantic-release in pyproject.toml"
```

---

### Task 3: Create `semantic-release.yml` workflow

**Files:**
- Create: `.github/workflows/semantic-release.yml`

- [ ] **Step 1: Create the workflow file**

```yaml
name: Semantic Release

on:
  push:
    branches:
      - master

concurrency:
  group: semantic-release
  cancel-in-progress: false

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

- [ ] **Step 2: Validate the YAML is well-formed**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/semantic-release.yml')); print('YAML valid')"
```

Expected: `YAML valid`

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/semantic-release.yml
git commit -m "chore: add semantic-release workflow"
```

---

### Task 4: Remove redundant version sync step from `release.yml`

**Files:**
- Modify: `.github/workflows/release.yml`

The `build` job currently patches `pyproject.toml` and `__init__.py` via `sed` to sync the version from the tag. With semantic-release, `pyproject.toml` is already correct when the tag fires. `__init__.py` uses `importlib.metadata.version()` — no hardcoded string exists to patch.

- [ ] **Step 1: Open `release.yml` and locate the step to remove**

Find and delete this entire step from the `build` job:

```yaml
      - name: Sync version from tag
        run: |
          VERSION="${GITHUB_REF_NAME#v}"
          sed -i "s/^version = \".*\"/version = \"${VERSION}\"/" pyproject.toml
          sed -i "s/__version__ = \".*\"/__version__ = \"${VERSION}\"/" src/cerebrofy/__init__.py
```

- [ ] **Step 2: Verify the YAML is still well-formed after deletion**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml')); print('YAML valid')"
```

Expected: `YAML valid`

- [ ] **Step 3: Verify the build job still has all required steps**

```bash
grep -n "name:" .github/workflows/release.yml
```

Expected: `test`, `build`, `publish` jobs present; `Sync version from tag` step absent.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "chore: remove manual version sync step — handled by semantic-release"
```

---

### Task 5: Create initial `CHANGELOG.md`

**Files:**
- Create: `CHANGELOG.md`

`python-semantic-release` will overwrite this file on the first release, but it needs to exist for the tool to append to it correctly. Create a minimal placeholder.

- [ ] **Step 1: Create `CHANGELOG.md`**

```markdown
# Changelog

All notable changes to this project will be documented in this file.

This file is auto-generated by [python-semantic-release](https://python-semantic-release.readthedocs.io/).
Do not edit manually.
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "chore: add CHANGELOG.md placeholder for semantic-release"
```

---

### Task 6: Push branch and open PR

**Files:**
- No file changes — git operations only

- [ ] **Step 1: Push the branch**

```bash
git push -u origin chore/semantic-release
```

- [ ] **Step 2: Open the PR targeting master**

```bash
gh pr create \
  --title "chore: automate releases with python-semantic-release" \
  --base master \
  --body "$(cat <<'EOF'
## Summary

- Adds `python-semantic-release` config to `pyproject.toml`
- Adds `.github/workflows/semantic-release.yml` — runs on every master push, bumps version, writes CHANGELOG.md, commits both, pushes tag
- Removes the now-redundant manual version sync step from `release.yml`
- Adds `CHANGELOG.md` placeholder

## One-time setup required before merging

The repo owner must:
1. Create a fine-grained PAT (GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens) with **Contents: Read and write** scoped to the Cerebrofy repo
2. Add it as a repo secret named `RELEASE_TOKEN` (repo → Settings → Secrets and variables → Actions)

Without `RELEASE_TOKEN`, the semantic-release workflow will fail on its first run.

## How it works after merge

Every push to master is analyzed for conventional commits since the last tag:
- `fix(...):` → patch bump
- `feat(...):` → minor bump  
- `BREAKING CHANGE` in commit footer → major bump
- `chore:`, `docs:`, `refactor:`, `test:` → no release

On a qualifying commit: `pyproject.toml` version is bumped, `CHANGELOG.md` is updated, both are committed with `[skip ci]`, and the new tag triggers the existing `release.yml` to publish to PyPI.
EOF
)"
```

- [ ] **Step 3: Confirm PR URL is returned and note it**

Expected: `https://github.com/mm0rsy/Cerebrofy/pull/<N>`
