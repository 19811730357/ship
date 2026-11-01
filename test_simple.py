"""
Simple integration test without special characters
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from billing_agent.parsers import DocumentParser
from billing_agent.agent import BillingAgent, is_api_configured
from billing_agent.workflow import BillingWorkflow


def test_parser():
    print("\n[Test 1] File Parser")
    parser = DocumentParser()

    test_file = Path("test_sample.txt")
    test_file.write_text("Test content: HANDLING CHARGE 50 USD", encoding='utf-8')

    try:
        result = parser.parse_file(test_file)
        print("  PASS - Parser works")
        print(f"  File: {result['source_file']}")
        print(f"  Type: {result['source_type']}")
        return True
    except Exception as e:
        print(f"  FAIL - {e}")
        return False
    finally:
        if test_file.exists():
            test_file.unlink()


def test_agent():
    print("\n[Test 2] Agent Initialization")
    try:
        agent = BillingAgent(accounting_entity="Test", use_mock=True)
        print("  PASS - Agent initialized (mock mode)")
        return True
    except Exception as e:
        print(f"  FAIL - {e}")
        return False


def test_workflow():
    print("\n[Test 3] Demo Workflow")
    try:
        workflow = BillingWorkflow(accounting_entity="Demo Origin", use_mock_data=True)
        results = workflow.process_demo_scenario("update", output_dir=None)

        print("  PASS - Workflow executed")
        print(f"  Decisions: {results['summary']['total_decisions']}")
        print(f"  CREATE: {results['summary']['operations']['CREATE']}")
        print(f"  UPDATE: {results['summary']['operations']['UPDATE']}")
        return True
    except Exception as e:
        print(f"  FAIL - {e}")
        import traceback
        traceback.print_exc()
        return False


def test_api_check():
    print("\n[Test 4] API Configuration Check")
    configured = is_api_configured()
    if configured:
        print("  INFO - API is configured")
    else:
        print("  INFO - API not configured (using mock mode)")
    return True


if __name__ == "__main__":
    print("=" * 60)
    print("Shipping Billing Agent V2 - Integration Test")
    print("=" * 60)

    tests = [
        test_parser,
        test_agent,
        test_workflow,
        test_api_check
    ]

    passed = sum(1 for test in tests if test())
    total = len(tests)

    print("\n" + "=" * 60)
    print(f"Results: {passed}/{total} tests passed")
    print("=" * 60)

    if passed == total:
        print("\nAll tests passed! System is ready.")
    else:
        print(f"\n{total - passed} test(s) failed.")

    sys.exit(0 if passed == total else 1)
