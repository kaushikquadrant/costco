#!/usr/bin/env python
"""Ask the real agent ONE question and print a timestamp for every step.

    python eval-adk\\diag_one.py
    python eval-adk\\diag_one.py "How many P1 incidents are there in total?"

A quick way to see where time goes (model calls, tool calls, hand-offs) without
running a whole eval. Day 4's tracing shows the same thing in Cloud Trace.
"""
import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import telemetry  # noqa: E402  (TRACING=on in .env sends this question's trace to Cloud Trace)

telemetry.setup()

from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402

from ops_agent.agent import MODEL, root_agent  # noqa: E402

QUESTION = sys.argv[1] if len(sys.argv) > 1 else "Is INC0428 still open, and what is its priority?"


async def main() -> None:
    print(f"model={MODEL}  project={os.getenv('GOOGLE_CLOUD_PROJECT')}  location={os.getenv('GOOGLE_CLOUD_LOCATION')}")
    print(f"question: {QUESTION}\n")
    runner = InMemoryRunner(agent=root_agent, app_name="diag")
    session = await runner.session_service.create_session(app_name="diag", user_id="diag")
    msg = types.Content(role="user", parts=[types.Part(text=QUESTION)])
    t0 = last = time.perf_counter()
    async for ev in runner.run_async(user_id="diag", session_id=session.id, new_message=msg):
        now = time.perf_counter()
        parts = ev.content.parts if ev.content and ev.content.parts else []
        what = []
        for p in parts:
            if p.function_call:
                what.append(f"calls {p.function_call.name}({dict(p.function_call.args or {})})")
            elif p.function_response:
                what.append(f"tool result from {p.function_response.name}")
            elif p.text:
                what.append("text: " + p.text.strip().replace("\n", " ")[:90])
        um = getattr(ev, "usage_metadata", None)
        tok = f" [{um.prompt_token_count or 0}+{um.candidates_token_count or 0} tok]" if um and not ev.partial else ""
        print(f"{now - t0:7.1f}s (+{now - last:5.1f}s)  {ev.author:<16} {'; '.join(what) or '(event)'}{tok}")
        last = now
    print(f"\ntotal {time.perf_counter() - t0:.1f}s")
    telemetry.flush()
    for tid in {telemetry.trace_id_for(i) for i in telemetry._invocation_trace} - {""}:
        print("trace:", telemetry.trace_url(tid))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:  # show the real error plainly
        print(f"\nERROR {type(e).__name__}: {str(e)[:600]}")
