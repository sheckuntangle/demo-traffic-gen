"""WebSocket endpoint for live log and status streaming."""

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger("demo_generator.web.ws")

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    manager = websocket.app.state.manager
    await websocket.accept()
    manager.ws_clients.add(websocket)
    logger.info(f"WebSocket connected ({len(manager.ws_clients)} clients)")

    try:
        await websocket.send_json({"type": "status", "data": manager.get_status()})
        await websocket.send_json({"type": "stats", "data": manager.get_stats()})

        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {type(e).__name__}: {e}")
    finally:
        manager.ws_clients.discard(websocket)
