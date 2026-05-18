import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: requires ANTHROPIC_API_KEY; skipped in PR CI")
    config.addinivalue_line("markers", "nightly: expensive LLM calls; only runs in nightly CI")
