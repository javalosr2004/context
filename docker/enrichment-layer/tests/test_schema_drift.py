"""Catches drift between enrichment's local DraftPlan and the backend's.

Both copies should produce identical JSON schemas. If this test breaks, sync
the copy in enrichment/schema_draft.py with backend/tutorial_schema.py.
"""
from pathlib import Path
import sys

import pytest

from enrichment.schema_draft import DraftPlan


@pytest.fixture
def backend_draft_plan():
    repo_root = Path(__file__).resolve().parents[3]
    backend_path = repo_root / "backend"
    if not (backend_path / "tutorial_schema.py").exists():
        pytest.skip("backend not present in this checkout")
    sys.path.insert(0, str(repo_root))
    try:
        from backend.tutorial_schema import DraftPlan as BackendDraftPlan
        return BackendDraftPlan
    finally:
        sys.path.pop(0)


def test_draft_plan_schema_matches_backend(backend_draft_plan):
    ours = DraftPlan.model_json_schema()
    theirs = backend_draft_plan.model_json_schema()
    assert ours == theirs, (
        "DraftPlan schema drift between enrichment and backend. "
        "Update enrichment/schema_draft.py to match."
    )
