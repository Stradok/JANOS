#!/usr/bin/env python3
"""Phase 3-5 audit — 13 integration checks."""
import asyncio
import sys
import uuid
import inspect
import unittest.mock as mock


async def run():
    failures = []

    def check(label, cond):
        symbol = "OK  " if cond else "FAIL"
        print(f"  [{symbol}] {label}")
        if not cond:
            failures.append(label)

    # P3-A: RoutingEngine agent running average
    from core.routing import RoutingEngine
    tag = "pipe_audit_" + uuid.uuid4().hex[:6]
    re = RoutingEngine()
    re.record_agent_result(tag, success=True, score=0.8)
    re.record_agent_result(tag, success=True, score=0.6)
    re.record_agent_result(tag, success=False, score=-0.2)
    r = next((x for x in re.get_agent_rankings() if x["agent"] == tag), None)
    check("P3-A  RoutingEngine agent avg ≈ 0.400", r and abs(r["avg_score"] - 0.4) < 0.01)

    # P3-B: RoutingEngine model running average
    re.record_model_result(tag + "_m", "general", success=True, score=0.9)
    re.record_model_result(tag + "_m", "general", success=False, score=-0.1)
    rm = next((x for x in re.get_model_rankings() if x["model"] == tag + "_m"), None)
    check("P3-B  RoutingEngine model avg ≈ 0.400", rm and abs(rm["avg_score"] - 0.4) < 0.01)

    # P3-C: CriticAgent parses positive score
    from agents.crew_agents import CriticAgent
    c = CriticAgent()

    async def good_response(*a, **kw):
        return "VALID: yes\nISSUES: none\nSCORE: 0.85\nSUGGESTION: ok"

    async def bad_response(*a, **kw):
        return "VALID: no\nISSUES: empty output\nSCORE: -0.5\nSUGGESTION: retry"

    with mock.patch.object(c, "think", good_response):
        v = await c.validate("some output", "task", [])
    check("P3-C  CriticAgent parses score=0.85, valid=True", v["score"] == 0.85 and v["valid"])

    # P3-D: CriticAgent parses negative score
    with mock.patch.object(c, "think", bad_response):
        v2 = await c.validate("", "task", [])
    check("P3-D  CriticAgent parses score=-0.5, valid=False", v2["score"] == -0.5 and not v2["valid"])

    # P3-E: Retry loop present in main.py
    with open("main.py") as f:
        main_src = f.read()
    check("P3-E  Retry loop in /api/v2/chat", "retry_count < ctx.max_retries" in main_src)
    check("P3-E  RoutingEngine.record_agent_result wired", "record_agent_result" in main_src)
    check("P3-E  ScoringEngine.record_action wired", "record_action" in main_src)

    # P3-F: ReasoningPipeline sets outcome_score
    with open("core/reasoning_pipeline.py") as f:
        pipe_src = f.read()
    check("P3-F  outcome_score set from critic in pipeline", "outcome_score = validation.get" in pipe_src)

    # P4: CommandHandler
    from core.commands import CommandHandler
    ch = CommandHandler()
    ch.register("ping", lambda _: "pong", "Test command", "/ping")
    res = await ch.execute("ping", "")
    check("P4    CommandHandler.execute('ping') == 'pong'", res == "pong")

    # P5-A: ScoringEngine records correctly
    from core.scoring import ScoringEngine
    se = ScoringEngine()
    se.record_action(tag + "_sc", success=True)
    se.record_action(tag + "_sc", success=True)
    se.record_action(tag + "_sc", success=False)
    ea = next((a for a in se.get_ranked_actions() if a["action"] == tag + "_sc"), None)
    check("P5-A  ScoringEngine score=1.5 (2 success, 1 fail)", ea and abs(ea["score"] - 1.5) < 0.01)

    # P5-B: StrategyRefiner accepts run_immediately param
    from core.strategy_refiner import StrategyRefiner
    check("P5-B  StrategyRefiner.start(run_immediately=) exists",
          "run_immediately" in inspect.signature(StrategyRefiner.start).parameters)

    # P5-C: FeedbackModule bridges to ScoringEngine
    with open("modules/feedback_module.py") as f:
        fb_src = f.read()
    check("P5-C  FeedbackModule -> ScoringEngine bridge", "ScoringEngine" in fb_src)

    # P5-D: /api/v5/scores endpoint
    check("P5-D  /api/v5/scores endpoint in main.py", '"/api/v5/scores"' in main_src or "api/v5/scores" in main_src)

    print()
    total = 13
    passed = total - len(failures)
    if failures:
        print(f"  {passed}/{total} passed.  FAILED: {failures}")
        sys.exit(1)
    else:
        print(f"  {passed}/{total} passed — all checks OK")


asyncio.run(run())
