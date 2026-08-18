from backend.app.main import app


def test_app_importable():
    # Smoke test: ensures the wrapper is wired to the existing FastAPI app.
    assert hasattr(app, "routes")

