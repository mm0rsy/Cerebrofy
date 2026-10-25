"""Cross-Session Pattern Synthesizer — analyzes session history for patterns."""

from cerebrofy.synthesizer.analyzer import (
    Pattern,
    StoredPattern,
    SynthesisResult,
    closed_session_count,
    list_synthesized_patterns,
    maybe_run_synthesis,
    parse_pattern_confidence,
    run_synthesis,
    sessions_until_next_synthesis,
    synthesis_interval,
    synthesize,
)

__all__ = [
    "Pattern",
    "StoredPattern",
    "SynthesisResult",
    "closed_session_count",
    "list_synthesized_patterns",
    "maybe_run_synthesis",
    "parse_pattern_confidence",
    "run_synthesis",
    "sessions_until_next_synthesis",
    "synthesis_interval",
    "synthesize",
]
