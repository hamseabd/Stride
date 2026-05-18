"""L1.12 — Classifier intent recall. @integration — calls Haiku, ~$0.04/run."""
import os

import pytest

from evals.fixtures.traces import CLASSIFIER_PAIRS

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def classifier():
    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")
    from shared.classifier import classify_intent
    return classify_intent


def test_l1_12_classifier_recall(classifier):
    by_intent: dict[str, list[bool]] = {}
    for message, expected_intent in CLASSIFIER_PAIRS:
        got = classifier(message)
        by_intent.setdefault(expected_intent, []).append(got == expected_intent)

    failures = []
    for intent, results in sorted(by_intent.items()):
        recall = sum(results) / len(results)
        print(f"  {intent}: {recall:.0%} ({sum(results)}/{len(results)})")
        if recall < 0.95:
            failures.append(f"{intent}: {recall:.0%}")

    assert not failures, f"Recall below 0.95 for: {', '.join(failures)}"
