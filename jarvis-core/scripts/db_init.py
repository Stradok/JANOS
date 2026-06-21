#!/usr/bin/env python3
"""Create all SQLite database tables — idempotent, safe to run anytime."""
from core.routing import RoutingEngine
from core.scoring import ScoringEngine

RoutingEngine()
print("  routing.db    OK  (agent_scores, model_scores)")

ScoringEngine()
print("  scoring.db    OK  (action_scores, feedback_log)")

print("  episodic.db   —   created at server startup via EpisodicMemory")
print("  jarvis_memory.db — created at server startup via FeedbackModule")
print("Done.")
