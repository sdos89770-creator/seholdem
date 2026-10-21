from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .game import ROOMS, act, join_shared_room, kick_player, public_state, start_hand, _player_by_id, _remove_player

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


def player_for_token(room, token: str):
    return next((player for player in room.players if player.token == token and not player.kicked), None)


def find_player(room_code: str, token: str):
    room = ROOMS.get(room_code.upper())
    if room is None or player_for_token(room, token) is None:
        return None
    return room


async def broadcast(room_code: str) -> None:
    room = ROOMS.get(room_code)
    if not room:
        return
    for socket in list(connections.get(room_code, set())):
        player = player_for_token(room, socket.query_params.get("token", ""))
        if player is None:
            connections[room_code].discard(socket)
            await socket.close(code=1008, reason="invalid player session")
            continue
        try:
            await socket.send_json({"type": "state", "state": public_state(room, player.id)})
        except Exception:
            connections[room_code].discard(socket)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/rooms/join")
def enter_room(request: PlayerRequest) -> dict[str, Any]:
    try:
        room, player = join_shared_room(request.name)
        return {"code": room.code, "player_id": player.id, "player_token": player.token, "state": public_state(room, player.id)}
    except ValueError as error:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/rooms/{code}")
def get_room(code: str, token: str):
    room = find_player(code, token)
    if room is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="방 또는 플레이어를 찾을 수 없습니다.")
    return public_state(room, player_for_token(room, token).id)


@app.delete("/api/rooms/{code}/players/{player_id}")
async def leave_room(code: str, player_id: str, requester_token: str) -> dict[str, bool]:
    room = find_player(code, requester_token)
    if room is None:
        raise HTTPException(status_code=404, detail="방 또는 플레이어를 찾을 수 없습니다.")
    player = player_for_token(room, requester_token)
    if player.id != player_id:
        raise HTTPException(status_code=403, detail="자기 자신만 방에서 나갈 수 있습니다.")
    if room.started:
        raise HTTPException(status_code=409, detail="토너먼트가 시작된 뒤에는 자리를 비울 수 없습니다.")
    _remove_player(room, player)
    await broadcast(room.code)
    return {"ok": True}


@app.delete("/api/rooms/{code}/players/{target_id}/kick")
async def force_kick(code: str, target_id: str, requester_token: str) -> dict[str, Any]:
    room = find_player(code, requester_token)
    if room is None:
        raise HTTPException(status_code=404, detail="방 또는 방장을 찾을 수 없습니다.")
    requester = player_for_token(room, requester_token)
    try:
        target = _player_by_id(room, target_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    try:
        kick_player(room, requester.id, target.id)
    except ValueError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error

    for socket in list(connections.get(room.code, set())):
        if socket.query_params.get("token") == target.token:
            connections[room.code].discard(socket)
            try:
                await socket.close(code=1008, reason="removed by host")
            except RuntimeError:
                pass
    await broadcast(room.code)
    return {"ok": True, "state": public_state(room, requester.id)}


@app.websocket("/ws/{code}")
async def room_socket(websocket: WebSocket, code: str):
    token = websocket.query_params.get("token", "")
    room = find_player(code, token)
    if room is None:
        await websocket.close(code=1008, reason="invalid room or player")
        return
    await websocket.accept()
    connections.setdefault(room.code, set()).add(websocket)
    await broadcast(room.code)
    try:
        while True:
            message = await websocket.receive_json()
            player = player_for_token(room, token)
            if player is None:
                await websocket.close(code=1008, reason="invalid player session")
                break
            try:
                if message.get("action") == "start":
                    if player.id != room.host_id:
                        raise ValueError("방장만 토너먼트를 시작할 수 있습니다.")
                    start_hand(room)
                elif message.get("action") == "play":
                    act(room, player.id, str(message.get("move", "")), int(message.get("amount", 0)))
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

@app.post("/api/rooms/{code}/reset")
async def api_reset_tournament(code: str, requester_token: str) -> dict[str, Any]:
    """방장이 토너먼트를 초기화하고 새 게임을 준비합니다."""
    room = find_player(code, requester_token)
    if room is None:
        raise HTTPException(status_code=404, detail="방 또는 플레이어를 찾을 수 없습니다.")
    requester = player_for_token(room, requester_token)
    try:
        reset_tournament(room, requester.id)
    except ValueError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    
    await broadcast(room.code)
    return {"ok": True, "state": public_state(room, requester.id)}
