import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app


def test_homepage_is_available():
    response = app.test_client().get("/")

    assert response.status_code == 200
    assert response.content_type.startswith("text/html")


def test_posts_api_returns_expected_json():
    response = app.test_client().get("/api/posts")

    assert response.status_code == 200
    data = response.get_json()
    assert isinstance(data["posts"], list)
    assert data["page"] == 1
    assert "total" in data