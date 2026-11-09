#!/usr/bin/env python
"""Simple backend test script"""

import requests
import time

print("Testing backend connection...")
print("=" * 60)

# Test 1: Health check
print("\n1. Testing /health endpoint...")
try:
    resp = requests.get('http://localhost:8080/health', timeout=5)
    print(f"   Status: {resp.status_code}")
    print(f"   Response: {resp.json()}")
except Exception as e:
    print(f"   ERROR: {e}")
    exit(1)

# Test 2: Chat endpoint
print("\n2. Testing /chat endpoint (this may take time)...")
print("   Sending: 'What is INC0428?'")
print("   Waiting... (up to 60 seconds)")

start = time.time()
try:
    resp = requests.post(
        'http://localhost:8080/chat',
        json={'message': 'What is INC0428?'},
        timeout=60
    )
    elapsed = time.time() - start

    print(f"   Success! Response time: {elapsed:.1f} seconds")
    print(f"   Status: {resp.status_code}")

    if resp.status_code == 200:
        data = resp.json()
        print(f"   Reply: {str(data.get('reply', 'N/A'))[:200]}")
    else:
        print(f"   Response: {resp.text[:200]}")

except requests.Timeout:
    elapsed = time.time() - start
    print(f"   TIMEOUT after {elapsed:.1f} seconds")
    print("   Backend is not responding (MCP tools may be stuck)")

except Exception as e:
    print(f"   ERROR: {e}")

print("\n" + "=" * 60)
print("Test complete!")
