from fastapi.testclient import TestClient

from app.main import app


def test_lobby_static_files_and_room_api_are_available():
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "색근테이블" in page.text
        assert client.get("/src/main.js").status_code == 200
        assert client.get("/api/health").json() == {"status": "ok"}

        created = client.post("/api/rooms", json={"name": "Host"})
        assert created.status_code == 200
        assert created.json()["state"]["players"][0]["name"] == "Host"
