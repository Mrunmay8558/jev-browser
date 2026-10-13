import pytest
from fastapi.testclient import TestClient

from examples.browser_decision import sample_state
from jev_lab.app import create_app
from jev_lab.config import Settings


@pytest.fixture
def state():
    return sample_state()


@pytest.fixture
def client():
    settings = Settings(_env_file=None, typesafe_api_key="", jev_model="jev-1.13.0", port=4317)
    with TestClient(create_app(settings), base_url="http://127.0.0.1:4317") as test_client:
        yield test_client
