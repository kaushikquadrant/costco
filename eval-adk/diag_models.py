#!/usr/bin/env python
"""Which Gemini models can this project use, and how fast are they?

    python eval-adk\\diag_models.py
    python eval-adk\\diag_models.py gemini-3.1-flash-lite gemini-3.5-flash

Uses GOOGLE_CLOUD_PROJECT from .env and tries both the 'global' location and
GOOGLE_CLOUD_LOCATION. For each model it sends one short request and one
judge-like request (asks the model to reason before answering), and prints the
time taken, so you can pick GEMINI_MODEL (agent) and JUDGE_MODEL (judges).
"""
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
from google import genai  # noqa: E402

CANDIDATES = sys.argv[1:] or [
    "gemini-2.5-flash", "gemini-2.5-flash-lite",
    "gemini-3.1-flash-lite", "gemini-3.1-flash",
    "gemini-3.5-flash-lite", "gemini-3.5-flash",
    "gemini-3.6-flash", "gemini-3.8-flash",
]
PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT")
LOCATIONS = list(dict.fromkeys(["global", os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")]))
JUDGE_PROMPT = ("Reference answer: 'INC0428 is open with priority P1.' Agent answer: 'INC0428 is still open; its "
                "priority is P1, for the payments service.' Think step by step, then say only YES if the agent answer "
                "means the same as the reference, otherwise NO.")

print(f"project={PROJECT}\n")
print(f"{'model':<24}{'location':<14}{'short':>8}{'judge-like':>12}  result")
for model in CANDIDATES:
    for loc in LOCATIONS:
        client = genai.Client(vertexai=True, project=PROJECT, location=loc)
        try:
            t = time.perf_counter()
            client.models.generate_content(model=model, contents="Say OK")
            short = time.perf_counter() - t
            t = time.perf_counter()
            r = client.models.generate_content(model=model, contents=JUDGE_PROMPT)
            judge = time.perf_counter() - t
            print(f"{model:<24}{loc:<14}{short:7.1f}s{judge:11.1f}s  ok: {(r.text or '').strip()[:20]}")
            break  # works here; no need to try the other location
        except Exception as e:
            msg = str(e)
            reason = "not available" if "404" in msg else "quota (429)" if "429" in msg else msg[:60]
            print(f"{model:<24}{loc:<14}{'-':>8}{'-':>12}  {reason}")
