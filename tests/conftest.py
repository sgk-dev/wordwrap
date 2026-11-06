from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    if not config.pluginmanager.hasplugin("asyncio"):
        pytest.exit(
            "pytest-asyncio is not installed for this Python, so the async tests cannot run. "
            "Install the dev dependencies: pip install -e '.[dev]'",
            returncode=4,
        )
