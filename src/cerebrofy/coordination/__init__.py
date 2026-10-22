"""Cerebrofy Multi-Agent Coordination — Core Modules

This package implements the Multi-Agent Coordination Protocol for Cerebrofy.

Core components:
- registry.py: ActiveAgentRegistry for tracking agents and their claims
- conflict_detector.py: ConflictDetector for detecting claim conflicts and memory contradictions  
- resolver.py: ConflictResolver for resolving conflicting memories

Integration points:
- Database: Uses the existing Cerebrofy database schema (migrations/007_coordination.sql)
- MCP tools: Provides tools for agent coordination (cerebrofy_claim, cerebrofy_release, cerebrofy_who, cerebrofy_conflicts, cerebrofy_resolve)
- CLI commands: Provides commands for agent coordination (cerebrofy who, claim, release, conflicts, resolve)
- Memory system: Integrates with existing memory layer to detect contradictions
- Session system: Leverages Idea #11 (Live Agent Session Recorder) for session tracking

This is Phase 1 of Wave C: Multi-Agent Coordination Protocol.
"""

from .registry import ActiveAgentRegistry
from .conflict_detector import ConflictDetector, MemoryContradictionDetector
from .resolver import (
    ConflictResolver,
    ResolutionStrategy,
    AgentSessionTracker,
    CoordinationOrchestrator,
)

__all__ = [
    'ActiveAgentRegistry',
    'ConflictDetector', 
    'MemoryContradictionDetector',
    'ConflictResolver',
    'ResolutionStrategy',
    'AgentSessionTracker',
    'CoordinationOrchestrator'
]

# Module version
__version__ = '1.0.0'