import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path):
    from rn_live.app import create_app
    from rn_live.config import Settings

    settings = Settings(database_url=f"sqlite:///{tmp_path}/test.db", storage_dir=tmp_path / "media")
    with TestClient(create_app(settings)) as instance:
        yield instance
