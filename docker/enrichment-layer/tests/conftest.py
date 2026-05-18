import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def isolated_data_dir():
    tmp = Path(tempfile.mkdtemp(prefix="enrich_test_"))

    from enrichment.config import settings
    from enrichment import storage

    old_data, old_db = settings.data_dir, settings.database_url
    settings.data_dir = tmp
    settings.database_url = f"sqlite:///{tmp}/index.db"
    storage.reset_engine_for_tests()

    yield tmp

    settings.data_dir = old_data
    settings.database_url = old_db
    storage.reset_engine_for_tests()
