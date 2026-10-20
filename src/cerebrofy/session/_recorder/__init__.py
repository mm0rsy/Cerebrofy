"""Private implementation package for cerebrofy.session.recorder (Idea #11).

This package was split out of ``recorder.py`` for maintainability (m9): each
sub-module owns one concern — models, argument redaction, schema, queries,
blast-radius metrics, lifecycle, or memory integration. ``recorder.py`` is a
thin facade that re-exports the public surface so existing imports keep
working.

Heavy / native-backed collaborators stay lazy-import: ``sqlite_vec`` (native C
extension), the fastembed-backed embedder, and the monkeypatch-targeted
memory-store openers. See inline comments in the relevant sub-modules for why.
"""
