"""Pytest configuration for ADK evaluations.

This file sets up pytest fixtures and markers for ADK eval tests.
"""
import pytest
from pathlib import Path
import os

# Increase MCP timeout from default 30s to 120s (2 minutes)
# This allows slow backends to respond without timing out
os.environ['MCP_REQUEST_TIMEOUT'] = '120'
os.environ['ADK_MCP_TIMEOUT'] = '120'


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "adk: ADK evaluation tests"
    )
    config.addinivalue_line(
        "markers", "category: Category of eval (lookup, log_search, metrics, etc)"
    )
    config.addinivalue_line(
        "markers", "agents: Number of agents involved (single, multi)"
    )


@pytest.fixture(scope="session")
def eval_sets_dir():
    """Path to evaluation sets directory."""
    return Path(__file__).parent / "eval_sets"


@pytest.fixture(scope="session")
def config_file():
    """Path to evaluation configuration file."""
    return Path(__file__).parent / "eval_sets" / "test_config.json"


@pytest.fixture(scope="session")
def ops_agent_module():
    """ADK agent module name."""
    return "ops_agent"
