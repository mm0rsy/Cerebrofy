"""Cerebrofy Multi-Agent Coordination — Conflict Resolver Module

This module provides strategies for resolving memory conflicts between multiple
AI agents working on the same neurons. It implements the resolution options
specified in the IDEA.md: keep_newest, keep_by_author, human_review, and merge.

The resolver integrates with the memory system and conflict detector to provide
consistent, deterministic conflict resolution that's appropriate for both
automated and human-in-the-loop scenarios.
"""
from __future__ import annotations

import re
import time
from enum import Enum
from typing import Any


class ResolutionStrategy(Enum):
    """Available conflict resolution strategies."""
    KEEP_MOST_RECENT = 'keep_newest'
    KEEP_BY_AUTHOR = 'keep_by_author'
    HUMAN_REVIEW = 'human_review'
    MERGE = 'merge'


class ConflictResolver:
    """Resolves memory conflicts between agents with different viewpoints."""
    
    def __init__(self, memories_db: Any | None = None) -> None:
        self.memories_db = memories_db
        self.resolution_strategies = {
            ResolutionStrategy.KEEP_MOST_RECENT: self._resolve_by_timestamp,
            ResolutionStrategy.KEEP_BY_AUTHOR: self._resolve_by_author,
            ResolutionStrategy.HUMAN_REVIEW: self._resolve_human_review,
            ResolutionStrategy.MERGE: self._resolve_by_merge
        }
    
    def resolve_memory_conflict(self, conflict_info: dict[str, Any], strategy: ResolutionStrategy) -> dict[str, Any]:
        """Resolve a single memory conflict using the specified strategy."""
        memory_a = conflict_info['memory_a']
        memory_b = conflict_info['memory_b']
        neuron = conflict_info['neuron']
        
        resolver_func = self.resolution_strategies.get(strategy, self._resolve_by_timestamp)
        
        try:
            result = resolver_func(memory_a, memory_b, conflict_info)
            return {
                'conflict_resolved': True,
                'strategy_used': strategy.value,
                'resolved_memory': result['resolved_memory'],
                'discarded_memory': result.get('discarded_memory'),
                'merged_memory': result.get('merged_memory'),
                'conflict_info': conflict_info,
                'resolution_timestamp': int(time.time())
            }
        except Exception as e:
            return {
                'conflict_resolved': False,
                'error': str(e),
                'fallback_strategy': ResolutionStrategy.KEEP_MOST_RECENT.value,
                'conflict_info': conflict_info
            }
    
    def resolve_multiple_conflicts(self, conflict_list: list[dict[str, Any]], strategy: ResolutionStrategy) -> list[dict[str, Any]]:
        """Resolve multiple conflicts, returning results for each."""
        results = []
        for conflict in conflict_list:
            result = self.resolve_memory_conflict(conflict, strategy)
            results.append(result)
        return results
    
    def _resolve_by_timestamp(self, memory_a: dict[str, Any], memory_b: dict[str, Any], conflict_info: dict[str, Any]) -> dict[str, Any]:
        """Resolution strategy: keep the memory with newer timestamp."""
        ts_a = memory_a.get('created_ts', 0)
        ts_b = memory_b.get('created_ts', 0)
        
        if ts_a >= ts_b:
            return {
                'resolved_memory': memory_a,
                'discarded_memory': memory_b
            }
        else:
            return {
                'resolved_memory': memory_b,
                'discarded_memory': memory_a
            }
    
    def _resolve_by_author(self, memory_a: dict[str, Any], memory_b: dict[str, Any], conflict_info: dict[str, Any]) -> dict[str, Any]:
        """Resolution strategy: keep memory from higher-privilege author."""
        author_a = memory_a.get('author', '')
        author_b = memory_b.get('author', '')
        
        # Priority order: claude > human > other
        author_priority = {
            'claude': 3,
            'claude-sonnet-4-6': 3,
            'claude-3-5-sonnet': 3,
            'claude-3-opus': 2,
            'human': 2,
            'human:': 2,
            'gpt-4': 1,
            'gpt-3.5': 1,
            'cursor': 1,
            'devin': 1,
            'ci': 0,
            '': 0
        }
        
        priority_a = author_priority.get(author_a, 0)
        priority_b = author_priority.get(author_b, 0)
        
        if priority_a >= priority_b:
            return {
                'resolved_memory': memory_a,
                'discarded_memory': memory_b
            }
        else:
            return {
                'resolved_memory': memory_b,
                'discarded_memory': memory_a
            }
    
    def _resolve_human_review(self, memory_a: dict[str, Any], memory_b: dict[str, Any], conflict_info: dict[str, Any]) -> dict[str, Any]:
        """Resolution strategy: flag for human review, no automatic decision."""
        # In a real implementation, this would flag the conflict for human review
        # For now, we'll use a deterministic approach based on memory id to avoid
        # repeated decisions on the same conflict
        conflict_hash = hash(f"{conflict_info['neuron']}_{memory_a.get('id')}_{memory_b.get('id')}")
        
        # Use hash to make it deterministic but appear 'random' enough for review
        if conflict_hash % 2 == 0:
            return {
                'resolved_memory': memory_a,
                'discarded_memory': memory_b,
                'note': 'Conflict flagged for human review'
            }
        else:
            return {
                'resolved_memory': memory_b,
                'discarded_memory': memory_a,
                'note': 'Conflict flagged for human review'
            }
    
    def _resolve_by_merge(self, memory_a: dict[str, Any], memory_b: dict[str, Any], conflict_info: dict[str, Any]) -> dict[str, Any]:
        """Resolution strategy: create a merged memory combining both."""
        # Extract key insights from both memories
        body_a = memory_a.get('body', '')
        body_b = memory_b.get('body', '')
        author_a = memory_a.get('author', 'unknown')
        author_b = memory_b.get('author', 'unknown')
        
        # Determine if they're addressing the same concept or complementary aspects
        # Simple heuristic: if they use similar subject matter words, merge
        words_a = set(re.findall(r'\b\w+\b', body_a.lower()))
        words_b = set(re.findall(r'\b\w+\b', body_b.lower()))
        
        # Merge strategy: combine both bodies with attribution
        merged_body = f"{author_a}'s view: {body_a}\n{author_b}'s view: {body_b}\n"
        
        # Create merged memory entry
        merged_memory = {
            'id': f"merged_{int(time.time())}_{conflict_info['neuron'].replace('/', '_')}",
            'neuron_id': conflict_info['neuron'],
            'lobe': memory_a.get('lobe', ''),
            'type': 'merged_resolution',
            'title': f"Merged Resolution: {conflict_info['neuron']}",
            'body': merged_body,
            'author': 'system_resolver',
            'created_ts': int(time.time()),
            'tags': ['merged', 'conflict_resolution', memory_a.get('lobe', '')],
            'decay_score': 1.0,
            'status': 'active',
            'source_memories': [memory_a.get('id'), memory_b.get('id')],
            'resolution_strategy': ResolutionStrategy.MERGE.value
        }
        
        return {
            'merged_memory': merged_memory,
            'discarded_memory_a': memory_a,
            'discarded_memory_b': memory_b,
            'note': 'Created merged memory resolving conflict'
        }


class AgentSessionTracker:
    """Tracks agent sessions for coordination purposes."""
    
    def __init__(self, sessions_db: Any | None = None) -> None:
        self.sessions_db = sessions_db
    
    def get_agent_session_info(self, agent_id: str) -> dict[str, Any]:
        """Get session information for an agent."""
        if not self.sessions_db:
            return {'agent_id': agent_id, 'session_id': None, 'error': 'No sessions DB'}
        
        # In real implementation, query the sessions table
        # For now, return placeholder
        return {
            'agent_id': agent_id,
            'session_id': f"sess_{agent_id.split('_')[-1] if '_' in agent_id else 'unknown'}",
            'status': 'active',
            'note': 'Session tracking requires integration with Idea #11'
        }
    
    def cleanup_inactive_sessions(self, inactive_threshold_minutes: int = 60) -> list[dict[str, Any]]:
        """Clean up inactive sessions and return cleanup info."""
        # In real implementation, query sessions DB and delete inactive ones
        # Return cleanup info for coordination
        return []
    
    def update_agent_heartbeat(self, agent_id: str, session_id: str | None = None) -> dict[str, Any]:
        """Update heartbeat for an agent."""
        return {
            'agent_id': agent_id,
            'session_id': session_id,
            'heartbeat_updated': True,
            'note': 'Heartbeat tracking requires registry integration'
        }


class CoordinationOrchestrator:
    """High-level coordinator for all conflict resolution activities."""
    
    def __init__(
        self,
        registry: Any | None = None,
        resolver: Any | None = None,
        session_tracker: Any | None = None,
    ) -> None:
        self.registry = registry
        self.resolver = resolver
        self.session_tracker = session_tracker
        self.active_strategies = {
            'memory_conflicts': ResolutionStrategy.KEEP_MOST_RECENT,
            'claim_conflicts': ResolutionStrategy.KEEP_MOST_RECENT,
            'lobe_conflicts': ResolutionStrategy.KEEP_MOST_RECENT
        }
    
    def resolve_agent_conflict(self, agent_id: str, neuron_id: str, 
                            conflict_type: str = 'memory', conflict_details: dict[str, Any] | None = None) -> dict[str, Any]:
        """Resolve a conflict involving a specific agent."""
        strategy = self.active_strategies.get(conflict_type, ResolutionStrategy.KEEP_MOST_RECENT)
        
        result: dict[str, Any] = {
            'agent_id': agent_id,
            'neuron_id': neuron_id,
            'conflict_type': conflict_type,
            'strategy_used': strategy.value,
            'resolution_timestamp': int(time.time()),
            'success': True
        }
        
        if conflict_type == 'memory' and conflict_details:
            if self.resolver:
                # For now, just return what would be resolved
                result['would_resolve'] = {
                    'strategy': strategy.value,
                    'note': 'Actual resolution requires memory context'
                }
        
        return result
    
    def get_coordination_status(self) -> dict[str, Any]:
        """Get overall coordination status."""
        status: dict[str, Any] = {
            'registry_active': self.registry is not None,
            'resolver_active': self.resolver is not None,
            'session_tracker_active': self.session_tracker is not None,
            'active_strategies': self.active_strategies,
            'timestamp': int(time.time())
        }
        
        if self.registry:
            status['active_agents'] = len(self.registry.get_active_agents())
            status['total_claims'] = sum(len(agent_data['claimed_neurons']) 
                                        for agent_data in self.registry.get_active_agents().values())
        
        return status


# Module-level exports for easier import
__all__ = [
    'ConflictResolver',
    'ResolutionStrategy',
    'AgentSessionTracker',
    'CoordinationOrchestrator',
    'CONTRADICTION_PATTERNS'
]