"""Precise, AST-based mechanical fixes for rename/removed API changes.

Only transforms whose meaning is unambiguous are applied:

* attribute calls — ``obj.dict()`` → ``obj.model_dump()``
* plain/module calls — ``pydantic.parse_obj_as(...)`` → ``pydantic.TypeAdapter(...)``
* decorators — ``@validator`` → ``@field_validator``
* import symbols — ``from pydantic import validator`` → ``field_validator``

Structural rewrites (for example ``class Config`` bodies becoming
``model_config = ConfigDict(...)``) are **not** mechanical and are reported as
errors instead of guessed at. Every edit is re-parsed with :mod:`ast` before it
is written; a file that would become syntactically invalid is left untouched.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from cerebrofy.errors import CEREBROFY_ERROR, CerebrofyError
from cerebrofy.upgrade.manifest import Change, Manifest
from cerebrofy.upgrade.planner import UpgradePlan
from cerebrofy.upgrade.scanner import ScanResult

_EDITABLE_SUFFIX = ".py"


class FixerError(CerebrofyError):
    """Auto-fix could not be applied (bad step selection or unsupported change)."""

    code: str = CEREBROFY_ERROR


@dataclass
class FixResult:
    """Per-step auto-fix outcome."""

    step: int
    change_index: int
    neurons_fixed: int = 0
    sites_fixed: int = 0
    errors: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "step": self.step,
            "change_index": self.change_index,
            "neurons_fixed": self.neurons_fixed,
            "sites_fixed": self.sites_fixed,
            "errors": self.errors,
            "files_modified": self.files_modified,
        }


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _char_col(line: str, byte_col: int) -> int:
    """Convert an AST UTF-8 byte column to a Python string index."""
    return len(line.encode("utf-8")[:byte_col].decode("utf-8", errors="ignore"))


def _offsets(source: str) -> tuple[list[str], list[int]]:
    lines = source.splitlines(keepends=True)
    starts: list[int] = []
    cursor = 0
    for line in lines:
        starts.append(cursor)
        cursor += len(line)
    if not lines:
        lines = [""]
        starts = [0]
    return lines, starts


def _position(lines: list[str], starts: list[int], lineno: int, byte_col: int) -> int:
    line_index = max(0, min(lineno - 1, len(lines) - 1))
    return starts[line_index] + _char_col(lines[line_index], byte_col)


def _node_name_edit(
    lines: list[str],
    starts: list[int],
    node: ast.AST,
    name: str,
) -> tuple[int, int, str] | None:
    """Return an edit replacing *node* (an identifier) with *name*."""
    if not isinstance(node, ast.Name):
        return None
    start = _position(lines, starts, node.lineno, node.col_offset)
    return (start, start + len(node.id), name)


def _attribute_edit(
    lines: list[str],
    starts: list[int],
    node: ast.Attribute,
    new_attr: str,
) -> tuple[int, int, str] | None:
    end_lineno = node.end_lineno if node.end_lineno is not None else node.lineno
    end_col = node.end_col_offset if node.end_col_offset is not None else 0
    start_byte = end_col - len(node.attr.encode("utf-8"))
    end = _position(lines, starts, end_lineno, end_col)
    start = _position(lines, starts, end_lineno, start_byte)
    return (start, end, new_attr)


def _call_name_parts(old: str, new: str) -> tuple[str, str, bool, bool] | None:
    """Return ``(old_name, new_name, is_attribute, expects_module_prefix)``."""
    if "(" not in old and "(" not in new:
        return None
    old_head = old.split("(", 1)[0].strip()
    new_head = new.split("(", 1)[0].strip()
    if not old_head or not new_head:
        return None
    old_parts = old_head.split(".")
    new_parts = new_head.split(".")
    old_name = old_parts[-1]
    new_name = new_parts[-1]
    is_attribute = len(old_parts) > 1
    expects_module_prefix = is_attribute and not old_head.startswith(".")
    return old_name, new_name, is_attribute, expects_module_prefix


def _module_tail(node: ast.AST) -> str | None:
    """Return the textual tail of a value expression (e.g. ``requests``)."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _collect_edits(
    tree: ast.AST,
    source: str,
    change: Change,
    target_lines: set[int] | None = None,
) -> list[tuple[int, int, str]]:
    """Collect non-overlapping edits for one change.

    When *target_lines* is provided, edits are restricted to AST nodes whose
    source line is one of the scanned usage sites. This keeps a name-based
    transform (for example ``.dict()``) from rewriting unrelated occurrences
    elsewhere in the same file.
    """
    lines, starts = _offsets(source)
    edits: list[tuple[int, int, str]] = []
    old = change.old.strip()
    new = change.new.strip()

    # Structural rewrites are never guessed at.
    if old.startswith("class "):
        return []

    # Decorator rename: @validator -> @field_validator.
    if old.startswith("@") or (
        change.category == "validator" and "(" not in old and "." not in old
    ):
        old_name = old.lstrip("@").strip()
        new_name = new.lstrip("@").strip()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                for decorator in node.decorator_list:
                    target = decorator.func if isinstance(decorator, ast.Call) else decorator
                    if isinstance(target, ast.Name) and target.id == old_name:
                        edit = _node_name_edit(lines, starts, target, new_name)
                        if edit is not None:
                            edits.append(edit)
        return _restrict(_dedupe(edits), starts, target_lines)

    # Import-symbol rename: pydantic.validator -> pydantic.field_validator.
    if change.category == "validator" and "." in old and "(" not in old and not old.startswith("."):
        old_parts = old.split(".")
        new_parts = new.split(".")
        old_symbol = old_parts[-1]
        new_symbol = new_parts[-1]
        old_module = ".".join(old_parts[:-1])
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == old_module or module.endswith("." + old_module):
                    for alias in node.names:
                        if alias.name == old_symbol:
                            start = _position(lines, starts, alias.lineno, alias.col_offset)
                            edits.append((start, start + len(alias.name), new_symbol))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == old:
                        start = _position(lines, starts, alias.lineno, alias.col_offset)
                        edits.append((start, start + len(alias.name), new))
        return _restrict(_dedupe(edits), starts, target_lines)

    call_parts = _call_name_parts(old, new)
    if call_parts is not None:
        old_name, new_name, is_attribute, expects_module_prefix = call_parts
        old_prefix = old.split("(", 1)[0].strip().rsplit(".", 1)[0] if expects_module_prefix else ""
        if old.startswith("."):
            # Attribute call: .dict() -> .model_dump()
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr == old_name:
                        edit = _attribute_edit(lines, starts, node.func, new_name)
                        if edit is not None:
                            edits.append(edit)
        elif is_attribute:
            # Module-qualified call: requests.get(...) -> ...
            prefix_tail = old_prefix.rsplit(".", 1)[-1]
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr != old_name:
                        continue
                    if _module_tail(node.func.value) != prefix_tail:
                        continue
                    edit = _attribute_edit(lines, starts, node.func, new_name)
                    if edit is not None:
                        edits.append(edit)
        else:
            # Plain call by name.
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    if node.func.id == old_name:
                        edit = _node_name_edit(lines, starts, node.func, new_name)
                        if edit is not None:
                            edits.append(edit)
        return _restrict(_dedupe(edits), starts, target_lines)

    # Attribute without call: .dict -> .model_dump
    if old.startswith("."):
        old_attr = old[1:].split(".")[-1]
        new_attr = new.lstrip(".").split(".")[-1]
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == old_attr:
                edit = _attribute_edit(lines, starts, node, new_attr)
                if edit is not None:
                    edits.append(edit)
        return _restrict(_dedupe(edits), starts, target_lines)

    return []


def _restrict(
    edits: list[tuple[int, int, str]],
    starts: list[int],
    target_lines: set[int] | None,
) -> list[tuple[int, int, str]]:
    """Keep only edits whose 1-based start line is a scanned target line."""
    if target_lines is None:
        return edits
    # Use bisect_left to correctly map byte offset to 1-based line number.
    # starts[i] is the byte offset of line i+1 (0-indexed).
    # For an edit at byte offset b, the 1-based line is bisect_left(starts, b + 1).
    # But simpler: the line number is the index of the largest start <= b, plus 1.
    from bisect import bisect_right
    return [
        edit
        for edit in edits
        if bisect_right(starts, edit[0]) in target_lines
    ]


def _dedupe(edits: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    seen: set[tuple[int, int, str]] = set()
    result: list[tuple[int, int, str]] = []
    for edit in edits:
        if edit in seen or edit[0] >= edit[1]:
            continue
        seen.add(edit)
        result.append(edit)
    return result


def _apply_edits(source: str, edits: list[tuple[int, int, str]]) -> str:
    result = source
    for start, end, replacement in sorted(edits, key=lambda e: e[0], reverse=True):
        result = result[:start] + replacement + result[end:]
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def apply_fixes(
    plan: UpgradePlan,
    manifest: Manifest,
    scan: ScanResult,
    root: Path,
    steps: list[int] | None = None,
) -> list[FixResult]:
    """Apply auto-fixes for ``steps`` (default: every auto-fixable step).

    Raises :class:`FixerError` for unknown step numbers. Per-file/AST failures
    are recorded in each :class:`FixResult` instead of aborting the run.

    Cross-file rollback: if any file fails to apply or re-parse, all changes
    are rolled back atomically. Multiple steps modifying the same file are
    merged into a single atomic write per file.
    """
    available = {step.step_number for step in plan.steps}
    if steps is None:
        selected = [step.step_number for step in plan.steps if step.auto_fix]
    else:
        selected = list(dict.fromkeys(steps))
    unknown = [step for step in selected if step not in available]
    if unknown:
        raise FixerError(
            f"Unknown step(s): {', '.join(str(s) for s in unknown)}. "
            f"Available steps: {', '.join(str(s) for s in sorted(available)) or 'none'}."
        )

    usage_by_index = {usage.change_index: usage for usage in scan.usages}
    step_by_number = {step.step_number: step for step in plan.steps}
    all_results: list[FixResult] = []
    # Map file -> (original_source, list of (step_number, edits, target_lines))
    file_modifications: dict[Path, tuple[str, list[tuple[int, list[tuple[int, int, str]], set[int]]]]] = {}

    for step_number in selected:
        plan_step = step_by_number[step_number]
        change = manifest.changes[plan_step.change_index]
        result = FixResult(step=step_number, change_index=plan_step.change_index)
        all_results.append(result)

        if not change.auto_fix:
            result.errors.append(
                f"Change `{change.old}` is not mechanically auto-fixable; edit it manually."
            )
            continue

        usage = usage_by_index.get(plan_step.change_index)
        if usage is None or not usage.sites:
            result.errors.append("No scanned sites remain for this step.")
            continue

        by_file: dict[str, list[str]] = {}
        for site in usage.sites:
            by_file.setdefault(site.file, [])
            if site.neuron_id not in by_file[site.file]:
                by_file[site.file].append(site.neuron_id)

        for file, neuron_ids in sorted(by_file.items()):
            path = (root / file).resolve()
            try:
                path.relative_to(root.resolve())
            except ValueError:
                result.errors.append(f"{file}: refusing to edit outside the repository root.")
                continue
            if path.suffix.lower() != _EDITABLE_SUFFIX:
                result.errors.append(f"{file}: auto-fix only supports Python files.")
                continue
            if not path.exists():
                result.errors.append(f"{file}: file no longer exists.")
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except OSError as exc:
                result.errors.append(f"{file}: could not read file ({exc}).")
                continue
            try:
                tree = ast.parse(source)
            except SyntaxError as exc:
                result.errors.append(f"{file}: cannot parse ({exc.msg}, line {exc.lineno}).")
                continue

            target_lines = {site.line for site in usage.sites if site.file == file}
            edits = _collect_edits(tree, source, change, target_lines)
            if not edits:
                result.errors.append(
                    f"{file}: no safe AST transform found for `{change.old}` "
                    "(manual edit required)."
                )
                continue

            # Validate each edit individually
            for edit in edits:
                test_updated = _apply_edits(source, [edit])
                try:
                    ast.parse(test_updated)
                except SyntaxError as exc:
                    result.errors.append(
                        f"{file}: transformed source is invalid ({exc.msg}, line {exc.lineno}); "
                        "file left unchanged."
                    )
                    edits = []
                    break

            if not edits:
                continue

            # Store edits for this file/step
            if path not in file_modifications:
                file_modifications[path] = (source, [])
            original, step_edits = file_modifications[path]
            step_edits.append((step_number, edits, target_lines))

            result.files_modified.append(file)
            result.sites_fixed += len(edits)
            result.neurons_fixed += len(neuron_ids)

    # Atomic commit: merge edits per file and validate
    if any(r.errors for r in all_results):
        # Rollback: nothing was written yet, just clear
        for r in all_results:
            r.files_modified.clear()
            r.sites_fixed = 0
            r.neurons_fixed = 0
    else:
        # Merge all edits per file and apply atomically
        for path, (original, step_edits) in file_modifications.items():
            # Merge all edits for this file
            all_edits = []
            for step_num, edits, _ in step_edits:
                all_edits.extend(edits)
            
            if not all_edits:
                continue
                
            # Apply all merged edits
            updated = _apply_edits(original, all_edits)
            try:
                ast.parse(updated)
            except SyntaxError:
                # If merge causes syntax error, rollback all
                for path2, (orig, _) in file_modifications.items():
                    try:
                        path2.write_text(orig, encoding="utf-8")
                    except OSError:
                        pass
                for r in all_results:
                    r.files_modified.clear()
                    r.sites_fixed = 0
                    r.neurons_fixed = 0
                break
            
            # Write atomically (temp + replace)
            import tempfile
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, delete=False
            ) as tf:
                tf.write(updated)
                tf.flush()
                import os
                os.fsync(tf.fileno())
                temp_path = Path(tf.name)
            try:
                temp_path.replace(path)
            finally:
                if temp_path.exists():
                    temp_path.unlink(missing_ok=True)

    return all_results
