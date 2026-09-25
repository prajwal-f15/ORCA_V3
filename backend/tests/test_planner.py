import sys
import time
import argparse
import httpx

sys.stdout.reconfigure(encoding='utf-8')

BASE_URL = "http://127.0.0.1:8001"

TEST_CASES = [
    {
        "id": "english",
        "category": "English",
        "message": "Where should I go fishing today?",
        "expected_intent": "fishing_potential",
        "expected_tool": "marine_intelligence",
    },
    {
        "id": "marathi",
        "category": "Marathi",
        "message": "मला आज मासेमारीसाठी कुठे जायला योग्य आहे?",
        "expected_intent": "fishing_potential",
        "expected_tool": "marine_intelligence",
    },
    {
        "id": "hindi",
        "category": "Hindi",
        "message": "आज मछली पकड़ने के लिए कहाँ जाना चाहिए?",
        "expected_intent": "fishing_potential",
        "expected_tool": "marine_intelligence",
    },
    {
        "id": "mixed",
        "category": "Mixed",
        "message": "आज fishing साठी कोणता area चांगला आहे?",
        "expected_intent": "fishing_potential",
        "expected_tool": "marine_intelligence",
    },
    {
        "id": "safety",
        "category": "Safety",
        "message": "Is it safe to go to sea today?",
        "expected_intent": "marine_safety",
        "expected_tool": "safety_governor",
    },
    {
        "id": "route",
        "category": "Route",
        "message": "मला सुरक्षित route हवा आहे.",
        "expected_intent": "route_optimization",
        "expected_tool": "route_engine",
    },
    {
        "id": "general",
        "category": "General",
        "message": "Hello ORCA",
        "expected_intent": "general_orca_chat",
        "expected_tool": None,
    },
]


def run_single_test(tc, per_test_timeout=240.0):
    payload = {"message": tc["message"]}
    t0 = time.time()
    print(f"\n--- Testing [{tc['category']}]: '{tc['message']}' ---", flush=True)
    try:
        resp = httpx.post(f"{BASE_URL}/api/v1/brain/plan", json=payload, timeout=per_test_timeout)
        elapsed = time.time() - t0
        status = resp.status_code
        data = resp.json()
        intent = data.get("intent")
        tool = data.get("tool")

        passed = (status == 200) and (intent == tc["expected_intent"]) and (tool == tc["expected_tool"])
        tag = "PASS" if passed else "FAIL"

        print(f"[{tag}] Status: {status} | Time: {elapsed:.2f}s", flush=True)
        print(f"       Intent: '{intent}' (Expected: '{tc['expected_intent']}')", flush=True)
        print(f"       Tool:   '{tool}' (Expected: '{tc['expected_tool']}')", flush=True)
        print(f"       JSON:   {data}", flush=True)
        return passed, elapsed, data
    except Exception as e:
        elapsed = time.time() - t0
        print(f"[ERROR] Request failed after {elapsed:.2f}s: {e}", flush=True)
        return False, elapsed, {"error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="ORCA Step 2 Intent Router Test Runner")
    parser.add_argument("--case", choices=[tc["id"] for tc in TEST_CASES] + ["all"], default="all", help="Test case to run")
    parser.add_argument("--timeout", type=float, default=240.0, help="Per-test HTTP timeout in seconds")
    args = parser.parse_args()

    cases_to_run = TEST_CASES if args.case == "all" else [tc for tc in TEST_CASES if tc["id"] == args.case]

    print("=" * 70, flush=True)
    print(f"ORCA INTENT ROUTER TEST RUNNER (Running {len(cases_to_run)} test(s), per-test timeout={args.timeout}s)", flush=True)
    print("=" * 70, flush=True)

    suite_t0 = time.time()
    passed_count = 0

    for tc in cases_to_run:
        passed, _, _ = run_single_test(tc, per_test_timeout=args.timeout)
        if passed:
            passed_count += 1

    total_time = time.time() - suite_t0
    total_cases = len(cases_to_run)

    print("\n" + "=" * 70, flush=True)
    print(f"FINAL SUMMARY: {passed_count}/{total_cases} PASSED (Total time: {total_time:.2f}s)", flush=True)
    print("=" * 70, flush=True)


if __name__ == "__main__":
    main()
