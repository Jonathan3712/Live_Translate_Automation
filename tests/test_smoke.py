"""Smoke tests for app import."""


def test_app_imports():
    """Ensure the Flask app module loads."""
    import app

    assert app.app is not None
