"""WebSocket endpoint for live log and status streaming."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    manager = websocket.app.state.manager
    await websocket.accept()
    manager.ws_clients.add(websocket)

    try:
        await websocket.send_json({"type": "status", "data": manager.get_status()})
        await websocket.send_json({"type": "stats", "data": manager.get_stats()})

        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        manager.ws_clients.discard(websocket)
