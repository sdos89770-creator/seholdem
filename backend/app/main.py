from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .game import ROOMS, act, create_room, join_room, public_state, start_hand

app = FastAPI(title="Holdem Friends")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
FRONTEND_SOURCE = Path(__file__).resolve().parents[2] / "frontend"
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")
else:
    app.mount("/src", StaticFiles(directory=FRONTEND_SOURCE / "src"), name="source")
connections: dict[str, set[WebSocket]] = {}


class PlayerRequest(BaseModel):
    name: str


class JoinRequest(PlayerRequest):
    code: str


def find_player(room_code: str, player_id: str):
    room = ROOMS.get(room_code.upper())
    if room is None or not any(player.id == player_id for player in room.players):
        return None
    return room


async def broadcast(room_code: str) -> None:
    room = ROOMS.get(room_code)
    if not room:
        return
    for socket in list(connections.get(room_code, set())):
        player_id = socket.query_params.get("player_id")
        try:
            await socket.send_json({"type": "state", "state": public_state(room, player_id)})
        except Exception:
            connections[room_code].discard(socket)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/rooms")
def new_room(request: PlayerRequest) -> dict[str, Any]:
    try:
        room, player = create_room(request.name)
        return {"code": room.code, "player_id": player.id, "state": public_state(room, player.id)}
    except ValueError as error:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/rooms/join")
def enter_room(request: JoinRequest) -> dict[str, Any]:
    try:
        room, player = join_room(request.code, request.name)
        return {"code": room.code, "player_id": player.id, "state": public_state(room, player.id)}
    except ValueError as error:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/rooms/{code}")
def get_room(code: str, player_id: str):
    room = find_player(code, player_id)
    if room is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="방 또는 플레이어를 찾을 수 없습니다.")
    return public_state(room, player_id)


@app.delete("/api/rooms/{code}/players/{player_id}")
def leave_room(code: str, player_id: str) -> dict[str, bool]:
    room = find_player(code, player_id)
    if room is None:
        raise HTTPException(status_code=404, detail="방 또는 플레이어를 찾을 수 없습니다.")
    if room.started:
        raise HTTPException(status_code=409, detail="토너먼트가 시작된 뒤에는 자리를 비울 수 없습니다.")
    room.players = [player for player in room.players if player.id != player_id]
    for seat, player in enumerate(room.players):
        player.seat = seat
    if not room.players:
        ROOMS.pop(room.code, None)
    elif room.host_id == player_id:
        room.host_id = room.players[0].id
    return {"ok": True}


@app.websocket("/ws/{code}")
async def room_socket(websocket: WebSocket, code: str):
    room = find_player(code, websocket.query_params.get("player_id", ""))
    if room is None:
        await websocket.close(code=1008, reason="invalid room or player")
        return
    await websocket.accept()
    connections.setdefault(room.code, set()).add(websocket)
    await broadcast(room.code)
    try:
        while True:
            message = await websocket.receive_json()
            player_id = websocket.query_params.get("player_id", "")
            try:
                if message.get("action") == "start":
                    if player_id != room.host_id:
                        raise ValueError("방장만 토너먼트를 시작할 수 있습니다.")
                    if not room.started:
                        room.started = True
                    start_hand(room)
                elif message.get("action") == "play":
                    act(room, player_id, str(message.get("move", "")), int(message.get("amount", 0)))
                else:
                    raise ValueError("지원하지 않는 요청입니다.")
                await broadcast(room.code)
            except (ValueError, TypeError) as error:
                await websocket.send_json({"type": "error", "message": str(error)})
    except WebSocketDisconnect:
        connections.get(room.code, set()).discard(websocket)


@app.get("/")
def frontend() -> FileResponse:
    root = FRONTEND_DIST if (FRONTEND_DIST / "index.html").is_file() else FRONTEND_SOURCE
    index_file = root / "index.html"
    return FileResponse(index_file)


@app.get("/{path:path}")
def frontend_route(path: str) -> FileResponse:
    root = FRONTEND_DIST if (FRONTEND_DIST / "index.html").is_file() else FRONTEND_SOURCE
    index_file = root / "index.html"
    requested_file = (root / path).resolve()
    if requested_file.is_relative_to(root.resolve()) and requested_file.is_file():
        return FileResponse(requested_file)
    return FileResponse(index_file)
