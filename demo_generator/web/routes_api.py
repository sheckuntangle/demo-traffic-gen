"""REST API endpoints for control, config, and stats."""

import asyncio
import json
import re

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


@router.put("/config/clients")
async def update_client_profiles(request: Request):
    manager = request.app.state.manager
    data = await request.json()
    manager.update_config("clients", None, data)
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


# --- Network / IP Aliasing ---

async def _run_cmd(*args):
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout.decode(), stderr.decode()


@router.get("/network/interfaces")
async def list_interfaces():
    rc, stdout, _ = await _run_cmd("ip", "-j", "addr", "show")
    if rc != 0:
        raise HTTPException(500, "Failed to list interfaces")
    interfaces = json.loads(stdout)
    result = []
    for iface in interfaces:
        name = iface.get("ifname", "")
        if name == "lo":
            continue
        addrs = []
        for info in iface.get("addr_info", []):
            if info.get("family") == "inet":
                addrs.append({
                    "ip": info["local"],
                    "prefix": info.get("prefixlen", 24),
                    "label": info.get("label", ""),
                })
        result.append({"name": name, "addresses": addrs})
    return result


class AddIpRequest(BaseModel):
    interface: str
    ip: str
    prefix: int = 24


@router.post("/network/add-ip")
async def add_ip(req: AddIpRequest):
    if not re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", req.ip):
        raise HTTPException(400, "Invalid IP address format")
    if not re.match(r"^[a-zA-Z0-9]+$", req.interface):
        raise HTTPException(400, "Invalid interface name")

    rc, _, stderr = await _run_cmd(
        "sudo", "ip", "addr", "add", f"{req.ip}/{req.prefix}", "dev", req.interface,
    )
    if rc != 0:
        raise HTTPException(500, f"Failed to add IP: {stderr.strip()}")
    return {"status": "added", "ip": req.ip, "interface": req.interface}


class RemoveIpRequest(BaseModel):
    interface: str
    ip: str
    prefix: int = 24


@router.post("/network/remove-ip")
async def remove_ip(req: RemoveIpRequest):
    if not re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", req.ip):
        raise HTTPException(400, "Invalid IP address format")
    if not re.match(r"^[a-zA-Z0-9]+$", req.interface):
        raise HTTPException(400, "Invalid interface name")

    rc, _, stderr = await _run_cmd(
        "sudo", "ip", "addr", "del", f"{req.ip}/{req.prefix}", "dev", req.interface,
    )
    if rc != 0:
        raise HTTPException(500, f"Failed to remove IP: {stderr.strip()}")
    return {"status": "removed", "ip": req.ip, "interface": req.interface}
