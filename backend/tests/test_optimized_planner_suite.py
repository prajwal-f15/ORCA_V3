import asyncio
import time
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding="utf-8")

from app.brain.planner import IntentPlanner

TEST_QUERIES = [
    ("मला Mumbai Port ते Goa Panaji safe route दाखव.", "route_optimization"),
    ("Show me a safe route from Mumbai to Goa.", "route_optimization"),
    ("Mumbai se Goa ka safe route dikhao.", "route_optimization"),
    ("आज fishing साठी काय conditions आहेत?", "fishing_potential"),
    ("marine risk काय आहे?", "marine_risk"),
    ("Where should I go fishing today?", "fishing_potential"),
    ("मला आज मासेमारीसाठी कुठे जायला योग्य आहे?", "fishing_potential"),
    ("आज मछली पकड़ने के लिए कहाँ जाना चाहिए?", "fishing_potential"),
    ("आज fishing साठी कोणता area चांगला आहे?", "fishing_potential"),
    ("Is it safe to go to sea today?", "marine_safety"),
    ("मला सुरक्षित route हवा आहे.", "route_optimization"),
    ("Hello ORCA", "general_orca_chat"),
    ("हवामानाचा अंदाज काय आहे?", "weather_information"),
]

async def run_suite():
    planner = IntentPlanner()
    print("=" * 75)
    print("TESTING OPTIMIZED ORCA INTENT PLANNER (13 MULTILINGUAL QUERIES)")
    print("=" * 75)

    total_time = 0.0
    passed = 0

    for query, expected_intent in TEST_QUERIES:
        t0 = time.time()
        plan = await planner.plan(query)
        dur = time.time() - t0
        total_time += dur

        actual_intent = plan.intent
        is_pass = (actual_intent == expected_intent)
        if is_pass:
            passed += 1

        tag = "PASS" if is_pass else "FAIL"
        print(f"[{tag}] {dur:.2f}s | Exp: '{expected_intent}' | Got: '{actual_intent}' | Tool: '{plan.tool}' | Query: '{query}'")

    avg_time = total_time / len(TEST_QUERIES)
    print("=" * 75)
    print(f"SUMMARY: {passed}/{len(TEST_QUERIES)} PASSED | Total: {total_time:.2f}s | Avg: {avg_time:.2f}s per query")
    print("=" * 75)

if __name__ == "__main__":
    asyncio.run(run_suite())
