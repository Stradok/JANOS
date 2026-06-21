#!/usr/bin/env python3
"""JANOS server CLI — Phase 2-5 pipeline via HTTP.

Usage:
  python chat.py              # connect to server on port 8000
  python chat.py --port 9000  # custom port
  python chat.py --full       # /api/v2/chat (full pipeline with RAG, debate, scoring)
  python chat.py --v1         # legacy /chat/v1

Inside the chat:
  !<cmd>   — send a /command to the Phase 4 command interface
  /scores  — show agent/model rankings
  /status  — show system status
  /quit    — exit
"""

import asyncio
import argparse
import sys

try:
    import httpx
except ImportError:
    print("httpx not installed. Run: pip install httpx")
    sys.exit(1)


async def _get(client, url):
    try:
        r = await client.get(url, timeout=15)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


async def _post(client, url, payload=None, params=None):
    try:
        r = await client.post(url, json=payload, params=params, timeout=120)
        return r.json()
    except httpx.ConnectError:
        return {"error": f"Cannot connect to {url}. Start server: uvicorn main:app --port 8000"}
    except Exception as e:
        return {"error": str(e)}


async def main():
    parser = argparse.ArgumentParser(description="JANOS server CLI")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--full", action="store_true", help="Use /api/v2/chat (RAG+debate+scoring)")
    parser.add_argument("--v1", action="store_true", help="Use legacy /chat/v1")
    args = parser.parse_args()

    base = f"http://localhost:{args.port}"
    if args.full:
        chat_url, mode, body_key = f"{base}/api/v2/chat", "full-pipeline", "input"
    elif args.v1:
        chat_url, mode, body_key = f"{base}/chat/v1", "v1", "message"
    else:
        chat_url, mode, body_key = f"{base}/chat/v2", "v2-agents", "message"

    print(f"JANOS [{mode}] — type !<cmd> for commands, /quit to exit\n")

    async with httpx.AsyncClient() as client:
        health = await _get(client, f"{base}/health")
        if "error" not in health:
            v = health.get("version", "?")
            p2 = "✓" if health.get("phase2", {}).get("active") else "✗"
            p3 = "✓" if health.get("phase3", {}).get("active") else "✗"
            p5 = "✓" if health.get("phase5", {}).get("active") else "✗"
            agents = health.get("phase2", {}).get("agents", [])
            print(f"Server v{v} | P2{p2} P3{p3} P5{p5} | agents: {', '.join(agents)}\n")

        while True:
            try:
                msg = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nBye.")
                break

            if not msg:
                continue
            if msg.lower() in ("/quit", "/exit"):
                print("Bye.")
                break

            # /scores shortcut
            if msg.lower() == "/scores":
                data = await _get(client, f"{base}/api/v3/rankings")
                agents_list = data.get("agents", [])
                models_list = data.get("models", [])
                if agents_list:
                    print("Agent rankings:")
                    for a in agents_list[:5]:
                        print(f"  {a.get('agent','?')}: score={a.get('avg_score',0):.2f} ({a.get('success_count',0)}✓ {a.get('failure_count',0)}✗)")
                if models_list:
                    print("Model rankings:")
                    for m in models_list[:5]:
                        print(f"  {m.get('model','?')}: score={m.get('avg_score',0):.2f}")
                if not agents_list and not models_list:
                    print("No ranking data yet — send some chats first.")
                print()
                continue

            if msg.lower() == "/status":
                data = await _get(client, f"{base}/api/status")
                hw = data.get("hardware", {})
                print(f"RAM: {hw.get('ram_used_gb',0):.1f}/{hw.get('ram_total_gb',0):.1f}GB  CPU: {hw.get('cpu_percent',0):.0f}%")
                ep = data.get("episodic_memory", {})
                print(f"Episodes stored: {ep.get('total_episodes',0)}")
                models = data.get("models_available", [])
                print(f"Models: {', '.join(models) or 'none'}\n")
                continue

            # Phase 4 commands via !prefix
            if msg.startswith("!"):
                cmd_input = msg[1:].strip()
                data = await _post(client, f"{base}/api/v4/command", params={"input": cmd_input})
                print(f"JAN: {data.get('response', data.get('error', str(data)))}\n")
                continue

            # Chat
            data = await _post(client, chat_url, {body_key: msg})
            if "error" in data and not data.get("response"):
                print(f"Error: {data['error']}\n")
                continue

            response = (
                data.get("response")
                or data.get("output", {}).get("response", "")
                or str(data)
            )
            score = data.get("score", "")
            retries = data.get("retries", 0)
            model = data.get("model", "")
            ep_id = data.get("episode_id", data.get("task_id", ""))

            meta = []
            if model:
                meta.append(model[:20])
            if score != "":
                s = f"{score:.2f}" if isinstance(score, float) else str(score)
                meta.append(f"score={s}")
            if retries:
                meta.append(f"{retries} retries")

            label = f"JAN [{', '.join(meta)}]" if meta else "JAN"
            print(f"{label}: {response}")
            if ep_id:
                print(f"  id={ep_id}  rate: POST {base}/feedback {{\"task_id\":\"{ep_id}\",\"rating\":5}}")
            print()


if __name__ == "__main__":
    asyncio.run(main())
