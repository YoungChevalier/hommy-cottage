"""
Hommy Cottage - Pytest Fixtures
Provides test client and application context fixtures for testing.
"""
import pytest
from app import create_app
from config import Config


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret-key"
    WTF_CSRF_ENABLED = False


@pytest.fixture
def app():
    """Creates a configured Flask application for testing."""
    application = create_app(TestConfig)
    return application


@pytest.fixture
def client(app):
    """Provides a test client for route simulations."""
    return app.test_client()


@pytest.fixture
def runner(app):
    """Provides a CLI test runner."""
    return app.test_cli_runner()
