"""REST API endpoints for control, config, and stats."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

router = APIRouter()


class StartRequest(BaseModel):
    mode: str = "full"


@router.post("/start")
async def start(req: StartRequest, request: Request):
    manager = request.app.state.manager
    if manager._engine and manager._engine.is_running:
        raise HTTPException(409, "Engine is already running")
    if req.mode not in ("full", "triggers", "legit"):
        raise HTTPException(400, f"Invalid mode: {req.mode}")
    await manager.start(req.mode)
    return {"status": "started", "mode": req.mode}


@router.post("/stop")
async def stop(request: Request):
    manager = request.app.state.manager
    await manager.stop()
    return {"status": "stopped"}


@router.post("/run/{category_name}")
async def run_single(category_name: str, request: Request):
    manager = request.app.state.manager
    try:
        await manager.run_single(category_name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"status": "completed", "category": category_name}


@router.get("/status")
async def status(request: Request):
    manager = request.app.state.manager
    return manager.get_status()


@router.get("/stats")
async def stats(request: Request):
    manager = request.app.state.manager
    return manager.get_stats()


@router.get("/config")
async def get_config(request: Request):
    manager = request.app.state.manager
    return manager.config


@router.get("/config/categories/{name}")
async def get_category_config(name: str, request: Request):
    manager = request.app.state.manager
    if name not in manager.config["categories"]:
        raise HTTPException(404, f"Unknown category: {name}")
    return manager.config["categories"][name]


@router.put("/config/categories/{name}")
async def update_category_config(name: str, request: Request):
    manager = request.app.state.manager
    data = await request.json()
    try:
        manager.update_config("categories", name, data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"status": "saved"}


@router.put("/config/generator")
async def update_generator_config(request: Request):
    manager = request.app.state.manager
    data = await request.json()
    manager.update_config("generator", None, data)
    return {"status": "saved"}


@router.put("/config/legitimate")
async def update_legitimate_config(request: Request):
    manager = request.app.state.manager
    data = await request.json()
    manager.update_config("legitimate", None, data)
    return {"status": "saved"}


@router.get("/categories")
async def list_categories(request: Request):
    from ..categories import get_all_categories
    manager = request.app.state.manager
    result = []
    for name, cls in get_all_categories().items():
        if name == "legitimate":
            continue
        enabled = manager.config["categories"].get(name, {}).get("enabled", False)
        result.append({"name": name, "display_name": cls.display_name, "enabled": enabled})
    return result
