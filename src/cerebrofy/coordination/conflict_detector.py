"""Cerebrofy Multi-Agent Coordination — Conflict Detector

This module implements memory contradiction detection between agents working
on the same neurons. It uses a keyword-opposition heuristic to identify
potentially conflicting memories.

Key features:
- Keyword-based contradiction detection (Phase 1)
- Integration with ActiveAgentRegistry for claim conflicts
- Extensible design for future embedding-based semantic opposition
- Conflict reporting with resolution options
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from .registry import ActiveAgentRegistry


# Keyword opposition pairs for contradiction detection
CONTRADICTION_PATTERNS: list[tuple[str, str]] = [
    # "never X" vs "X is fine/ok/acceptable/recommended"
    (r'\bnever\s+(\w+)', r'\b(\w+)\s+is\s+(fine|ok|okay|acceptable|recommended|good)'),
    (r'\balways\s+(\w+)', r'\b(\w+)\s+is\s+(not\s+required|optional|unnecessary|deprecated)'),
    (r'\bdeprecated\b', r'\brecommended\b'),
    (r'\bdeprecated\b', r'\buse\s+instead\b'),
    (r'\bavoid\s+(\w+)', r'\buse\s+\1\b'),
    (r'\bdon\'?t\s+use\s+(\w+)', r'\b(\w+)\s+is\s+(fine|ok|okay|acceptable)'),
    (r'\bmust\s+not\s+(\w+)', r'\b(\w+)\s+is\s+(fine|ok|okay|acceptable|recommended)'),
    (r'\bforbidden\b', r'\ballowed\b'),
    (r'\bprohibited\b', r'\bpermitted\b'),
    # "remove X" vs "add X" or "keep X"
    (r'\bremove\s+(\w+)', r'\b(add|keep|retain)\s+\1\b'),
    (r'\bdelete\s+(\w+)', r'\b(add|keep|retain)\s+\1\b'),
    # "X is broken/bad" vs "X works/good"
    (r'\b(\w+)\s+is\s+(broken|bad|wrong|incorrect|buggy)', r'\b(\w+)\s+(works|works\s+fine|good|correct|fixed)'),
]


class ConflictDetector:
    """Detects conflicts between agent claims and memory contradictions."""
    
    def __init__(self, registry: ActiveAgentRegistry | None = None):
        self.registry = registry
        self.patterns = CONTRADICTION_PATTERNS
    
    def detect_claim_conflicts(self, neuron_id: str, requesting_agent: str) -> dict[str, Any]:
        """Detect if a neuron is already claimed by another active agent."""
        if not self.registry:
            return {'claim_conflicts': [], 'has_conflict': False}
        
        claimants = self.registry.check_conflicts(requesting_agent, neuron_id)
        other_claimants = [c for c in claimants['claiming_agents'] if c['agent_id'] != requesting_agent]
        
        return {
            'neuron': neuron_id,
            'claim_conflicts': other_claimants,
            'has_conflict': len(other_claimants) > 0
        }
    
    def detect_memory_contradictions(self, neuron_id: str, memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Detect contradictory memories on the same neuron using keyword heuristic."""
        contradictions: list[dict[str, Any]] = []
        
        # Compare each pair of memories
        for i, mem_a in enumerate(memories):
            for mem_b in memories[i+1:]:
                contradiction = self._check_contradiction(mem_a, mem_b)
                if contradiction:
                    contradictions.append({
                        'neuron': neuron_id,
                        'memory_a': {'id': mem_a.get('id'), 'body': mem_a.get('body', ''), 'author': mem_a.get('author')},
                        'memory_b': {'id': mem_b.get('id'), 'body': mem_b.get('body', ''), 'author': mem_b.get('author')},
                        'type': contradiction['type'],
                        'matched_pattern': contradiction['pattern'],
                        'resolution_options': ['keep_newest', 'keep_by_author', 'human_review', 'merge']
                    })
        
        return contradictions
    
    def _check_contradiction(self, mem_a: dict[str, Any], mem_b: dict[str, Any]) -> dict[str, Any] | None:
        """Check if two memories contradict each other using keyword patterns."""
        body_a = mem_a.get('body', '').lower()
        body_b = mem_b.get('body', '').lower()
        
        if not body_a or not body_b:
            return None
        
        for pattern_a, pattern_b in self.patterns:
            # Check A against B's pattern
            match_a = re.search(pattern_a, body_a)
            match_b = re.search(pattern_b, body_b)
            
            if match_a and match_b:
                # Check if they're talking about the same thing
                word_a = match_a.group(1) if match_a.groups() else match_a.group(0)
                word_b = match_b.group(1) if match_b.groups() else match_b.group(0)
                
                if word_a.lower() == word_b.lower():
                    return {
                        'type': 'keyword_opposition',
                        'pattern': f'"{pattern_a}" vs "{pattern_b}"',
                        'matched_words': word_a
                    }
            
            # Also check B against A's pattern (symmetric)
            match_a_rev = re.search(pattern_b, body_a)
            match_b_rev = re.search(pattern_a, body_b)
            
            if match_a_rev and match_b_rev:
                word_a = match_a_rev.group(1) if match_a_rev.groups() else match_a_rev.group(0)
                word_b = match_b_rev.group(1) if match_b_rev.groups() else match_b_rev.group(0)
                
                if word_a.lower() == word_b.lower():
                    return {
                        'type': 'keyword_opposition',
                        'pattern': f'"{pattern_b}" vs "{pattern_a}"',
                        'matched_words': word_a
                    }
        
        return None
    
    def check_conflicts(
        self,
        neuron_id: str,
        requesting_agent: str,
        memories: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Comprehensive conflict check for a neuron."""
        claim_conflicts = self.detect_claim_conflicts(neuron_id, requesting_agent)
        memory_conflicts = []
        
        if memories:
            memory_conflicts = self.detect_memory_contradictions(neuron_id, memories)
        
        # Check for lobe-level awareness (other agents in same lobe)
        lobe_awareness: list[dict[str, Any]] = []
        if self.registry:
            # Get lobe from neuron ID (format: lobe/file::neuron)
            lobe = neuron_id.split('/')[0] if '/' in neuron_id else ''
            if lobe:
                for agent_id, agent_data in self.registry.get_active_agents().items():
                    if agent_id != requesting_agent:
                        for claimed_neuron in agent_data['claimed_neurons']:
                            if claimed_neuron.startswith(lobe + '/'):
                                lobe_awareness.append({
                                    'agent_id': agent_id,
                                    'agent_type': agent_data['agent_type'],
                                    'intent': agent_data['intent'],
                                    'active_minutes': agent_data.get('active_minutes', 0),
                                })
                                break
        
        return {
            'neuron': neuron_id,
            'claim_conflicts': claim_conflicts['claim_conflicts'],
            'has_claim_conflict': claim_conflicts['has_conflict'],
            'memory_conflicts': memory_conflicts,
            'has_memory_conflict': len(memory_conflicts) > 0,
            'lobe_awareness': lobe_awareness,
            'has_lobe_activity': len(lobe_awareness) > 0,
        }


class MemoryContradictionDetector:
    """Specialized detector for memory contradictions across the codebase."""
    
    def __init__(self) -> None:
        self.detector = ConflictDetector()
    
    def scan_all_neurons(self, memories_by_neuron: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
        """Scan all neurons for memory contradictions."""
        contradictions: dict[str, list[dict[str, Any]]] = {}
        
        for neuron_id, memories in memories_by_neuron.items():
            if len(memories) > 1:
                conflicts = self.detector.detect_memory_contradictions(neuron_id, memories)
                if conflicts:
                    contradictions[neuron_id] = conflicts
        
        return contradictions
    
    def get_conflict_summary(self, contradictions: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        """Generate a summary of all memory conflicts."""
        total_conflicts = sum(len(conflicts) for conflicts in contradictions.values())
        affected_neurons = len(contradictions)
        
        by_type: dict[str, int] = {}
        for neuron_conflicts in contradictions.values():
            for conflict in neuron_conflicts:
                conflict_type = conflict.get('type', 'unknown')
                by_type[conflict_type] = by_type.get(conflict_type, 0) + 1
        
        return {
            'total_conflicts': total_conflicts,
            'affected_neurons': affected_neurons,
            'by_type': by_type,
            'neurons': list(contradictions.keys()),
        }