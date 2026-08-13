from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.integration


def test_postgres_boundary_is_explicit() -> None:
    if os.environ.get("DMF_ENVIRONMENT") != "TEST":
        pytest.skip("disposable PostgreSQL is not configured")
    assert os.environ.get("DMF_TEST_DATABASE_URL", "").startswith("postgresql")
