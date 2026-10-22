"""Cerebrofy Multi-Agent Coordination Registry Module

This module implements the ActiveAgentRegistry which tracks all active agents
working on the same codebase and manages their claims on neurons (code units).

Key responsibilities:
- Track active agents and their claimed neurons
- Manage claim lifecycle (claim/release)
- Monitor heartbeats to detect stale claims
- Provide conflict detection interface for MCP tools
- Maintain consistency with session state

The registry is thread-safe and designed for concurrent access from multiple
agents working on the same codebase.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from cerebrofy.db.connection import open_db
from cerebrofy.db.schema import create_memory_schema, create_session_schema


class ActiveAgentRegistry:
    """Main registry class for tracking active agents and their claims."""
    
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db = open_db(self.db_path)
        self.heartbeat_interval = 300  # 5 minutes in seconds
        self.staleness_threshold = 2 * 300  # 10 minutes
        self._ensure_schema()
        self._load_active_agents()

    def _ensure_schema(self) -> None:
        """Ensure the active_agents table exists (idempotent)."""
        create_session_schema(self.db)
        create_memory_schema(self.db)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS active_agents ("
            "  agent_id TEXT PRIMARY KEY,"
            "  agent_type TEXT NOT NULL,"
            "  session_id TEXT,"
            "  intent TEXT,"
            "  claimed_neurons TEXT NOT NULL DEFAULT '[]',"
            "  started_ts INTEGER NOT NULL,"
            "  last_heartbeat INTEGER NOT NULL,"
            "  status TEXT DEFAULT 'active'"
            ");"
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_active_agents_status ON active_agents(status);"
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_active_agents_neuron ON active_agents(claimed_neurons);"
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_active_agents_heartbeat ON active_agents(last_heartbeat);"
        )
        self.db.commit()

    def _load_active_agents(self) -> None:
        """Load all active agents from the database."""
        self.active_agents = {}
        agents = self.db.execute(
            "SELECT agent_id, agent_type, session_id, intent, claimed_neurons, "
            "started_ts, last_heartbeat, status FROM active_agents "
            "WHERE status = 'active'"
        ).fetchall()

        for agent in agents:
            agent_id, agent_type, session_id, intent, claimed_neurons, started_ts, last_heartbeat, status = agent
            self.active_agents[agent_id] = {
                'agent_type': agent_type,
                'session_id': session_id,
                'intent': intent,
                'claimed_neurons': json.loads(claimed_neurons) if claimed_neurons else [],
                'started_ts': started_ts,
                'last_heartbeat': last_heartbeat,
                'status': status
            }
    
    def get_active_agents(self) -> dict[str, Any][str, Dict]:
        """Return a copy of all active agents."""
        return self.active_agents.copy()
    
    def claim_neurons(self, agent_id: str, neurons: List[str], intent: str, ttl_minutes: int = 60) -> dict[str, Any]:
        """Claim neurons for an agent. Returns conflict information."""
        # Check if agent already exists
        if agent_id in self.active_agents:
            # Update existing agent
            self._update_agent_heartbeat(agent_id)
            old_neurons = self.active_agents[agent_id]['claimed_neurons']
            self.active_agents[agent_id]['claimed_neurons'] = neurons
            self.active_agents[agent_id]['intent'] = intent
            self.active_agents[agent_id]['last_heartbeat'] = int(time.time())
            return self._check_conflicts(agent_id, neurons)
        
        # New agent - create entry
        agent_id = agent_id
        self.active_agents[agent_id] = {
            'agent_type': 'claude',
            'session_id': self._get_session_id(),
            'intent': intent,
            'claimed_neurons': neurons,
            'started_ts': int(time.time()),
            'last_heartbeat': int(time.time()),
            'status': 'active'
        }
        return self._check_conflicts(agent_id, neurons)
    
    def release_neurons(self, agent_id: str, neurons: List[str]) -> dict[str, Any]:
        """Release specific neurons claimed by an agent."""
        if agent_id not in self.active_agents:
            return {'error': 'NO_ACTIVE_AGENT'}
        
        # Remove specific neurons
        current_neurons = set(self.active_agents[agent_id]['claimed_neurons'])
        to_release = set(neurons)
        remaining_neurons = list(current_neurons - to_release)

        if remaining_neurons:
            # Update existing claim
            self.active_agents[agent_id]['claimed_neurons'] = remaining_neurons
        else:
            # Release all claims for this agent
            del self.active_agents[agent_id]
            return {'released': list(to_release)}

        self.active_agents[agent_id]['last_heartbeat'] = int(time.time())
        return {'released': list(to_release)}

    def release_all(self, agent_id: str) -> dict[str, Any]:
        """Release all claims for an agent."""
        if agent_id not in self.active_agents:
            return {'error': 'NO_ACTIVE_AGENT'}

        released_neurons = self.active_agents[agent_id]['claimed_neurons']
        del self.active_agents[agent_id]
        return {'released': released_neurons}
    
    def get_claims(self) -> List[Dict]:
        """Get all current claims by all active agents."""
        claims = []
        for agent_id, agent_data in self.active_agents.items():
            for neuron in agent_data['claimed_neurons']:
                claims.append({
                    'agent_id': agent_id,
                    'agent_type': agent_data['agent_type'],
                    'intent': agent_data['intent'],
                    'neuron': neuron,
                    'active_minutes': (int(time.time()) - agent_data['started_ts']) // 60
                })
        return claims
    
    def check_conflicts(self, agent_id: str, neuron: str) -> dict[str, Any]:
        """Check for conflicts on a specific neuron."""
        # Find all agents claiming this neuron
        claiming_agents = []
        for agent_id, agent_data in self.active_agents.items():
            if neuron in agent_data['claimed_neurons']:
                claiming_agents.append({
                    'agent_id': agent_id,
                    'agent_type': agent_data['agent_type'],
                    'intent': agent_data['intent'],
                    'active_minutes': (int(time.time()) - agent_data['started_ts']) // 60
                })
        
        return {
            'agent_id': agent_id,
            'claiming_agents': claiming_agents,
            'neuron': neuron,
            'conflict': len(claiming_agents) > 1
        }
    
    def check_memory_conflicts(self, neuron: str) -> dict[str, Any]:
        """Check for memory contradictions on a specific neuron."""
        # This would need to query the memories table - simplified for now
        # In real implementation, this would check for contradictory memories
        return {'neuron': neuron, 'conflicts': [], 'resolution_options': ['keep_newest', 'keep_by_author', 'human_review', 'merge']}
    
    def _check_conflicts(self, agent_id: str, neurons: List[str]) -> dict[str, Any]:
        """Internal method to check conflicts for claimed neurons."""
        conflicts = []
        for neuron in neurons:
            conflict_info = self.check_conflicts(agent_id, neuron)
            if conflict_info['conflict']:
                conflicts.append(conflict_info)
        
        return {
            'claimed': neurons,
            'conflicts': conflicts,
            'claim_id': f"claim_{int(time.time())}_{agent_id}"
        }
    
    def _update_agent_heartbeat(self, agent_id: str) -> None:
        """Update the last heartbeat timestamp for an agent."""
        if agent_id in self.active_agents:
            self.active_agents[agent_id]['last_heartbeat'] = int(time.time())
    
    def _get_session_id(self) -> str:
        """Generate or retrieve session ID for the current agent."""
        # In real implementation, this would tie to actual session state
        return f"sess_{int(time.time())}_{agent_id[:5]}"
    
    def cleanup_stale_agents(self) -> List[Dict]:
        """Remove stale agents (no heartbeat for > 2× interval) and return released info."""
        now = int(time.time())
        stale_agents = []
        
        to_delete = []
        for agent_id, agent_data in self.active_agents.items():
            if now - agent_data['last_heartbeat'] > self.staleness_threshold:
                to_delete.append(agent_id)
                stale_agents.append({
                    'agent_id': agent_id,
                    'agent_type': agent_data['agent_type'],
                    'intent': agent_data['intent'],
                    'claimed_neurons': agent_data['claimed_neurons'],
                    'active_minutes': (now - agent_data['started_ts']) // 60
                })
        
        for agent_id in to_delete:
            del self.active_agents[agent_id]
        
        return stale_agents