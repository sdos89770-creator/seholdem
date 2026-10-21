from fastapi.testclient import TestClient

from app.game import ROOMS
from app.main import app


def test_lobby_static_files_and_room_api_are_available():
    ROOMS.clear()
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "색근테이블" in page.text
        assert client.get("/src/main.js").status_code == 200
        assert client.get("/api/health").json() == {"status": "ok"}

        host = client.post("/api/rooms/join", json={"name": "Host"})
        guest = client.post("/api/rooms/join", json={"name": "Guest"})
        assert host.status_code == 200
        assert guest.status_code == 200
        assert host.json()["code"] == guest.json()["code"] == "TABLE"
        assert len(guest.json()["state"]["players"]) == 2

        host_id = host.json()["player_id"]
        guest_id = guest.json()["player_id"]
        host_token = host.json()["player_token"]
        guest_token = guest.json()["player_token"]
        assert "token" not in host.json()["state"]["players"][0]
        assert client.get("/api/rooms/TABLE", params={"token": host_token}).status_code == 200
        denied = client.delete(f"/api/rooms/TABLE/players/{host_id}/kick", params={"requester_token": guest_token})
        assert denied.status_code == 403

        kicked = client.delete(f"/api/rooms/TABLE/players/{guest_id}/kick", params={"requester_token": host_token})
        assert kicked.status_code == 200
        assert len(kicked.json()["state"]["players"]) == 1
        assert client.get("/api/rooms/TABLE", params={"token": guest_token}).status_code == 404
