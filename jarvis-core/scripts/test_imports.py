#!/usr/bin/env python3
"""Verify all core module imports load without errors."""
import sys
import importlib

MODULES = [
    "core.llm_client",
    "core.episodic_memory",
    "core.hardware_monitor",
    "core.model_router",
    "core.routing",
    "core.scoring",
    "core.commands",
    "core.reasoning_pipeline",
    "core.strategy_refiner",
    "agents.crew_agents",
    "agents.autogen_debate",
    "tools.file_tool",
    "tools.system_tool",
    "tools.web_search_tool",
    "tools.browser_tool",
    "tools.math_tool",
    "tools.time_tool",
]

failed = []
for m in MODULES:
    try:
        importlib.import_module(m)
        print(f"  OK  {m}")
    except Exception as e:
        print(f"  ERR {m}: {e}")
        failed.append(m)

print()
if failed:
    print(f"Failed: {len(failed)}/{len(MODULES)}")
    sys.exit(1)
else:
    print(f"All {len(MODULES)} imports OK")
