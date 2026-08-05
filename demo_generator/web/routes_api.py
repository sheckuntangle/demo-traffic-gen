"""REST API endpoints for control, config, and stats."""

import asyncio
import json
import logging
import os
import re
import shutil

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

logger = logging.getLogger("demo_generator.web.api")

router = APIRouter()

docker_router = APIRouter(prefix="/docker")


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
    except Exception as e:
        manager.logger.info("ERROR", f"Single category run failed: {category_name}: {e}")
        raise HTTPException(500, str(e))
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
    logger.info("GET /config")
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
    logger.info(f"PUT /config/categories/{name}")
    try:
        manager.update_config("categories", name, data)
    except ValueError as e:
        logger.error(f"Config update failed: {e}")
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
    rc, stdout, stderr = await _run_cmd("ip", "-j", "addr", "show")
    if rc != 0:
        logger.error(f"ip -j addr show failed: {stderr}")
        return []
    try:
        interfaces = json.loads(stdout)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse ip output: {e}")
        return []
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


# --- Docker Client Management ---


@docker_router.get("/status")
async def docker_status(request: Request):
    manager = request.app.state.manager
    docker_conf = manager.config.get("docker", {})
    result = {
        "docker_available": shutil.which("docker") is not None,
        "enabled": docker_conf.get("enabled", False),
        "image_exists": False,
        "image_name": docker_conf.get("image_name", "demo-generator-worker"),
        "network_exists": False,
        "containers": [],
    }
    try:
        pool = manager.get_docker_pool()
        result["image_exists"] = pool.image_exists()
        net_mgr = pool._network_mgr
        if net_mgr:
            result["network_exists"] = net_mgr.get_macvlan_network() is not None
        if pool.is_started:
            result["containers"] = pool.get_status()
    except Exception as e:
        logger.debug(f"Docker status check: {e}")
    return result


@docker_router.put("/config")
async def update_docker_config(request: Request):
    manager = request.app.state.manager
    data = await request.json()
    docker_conf = manager.config.setdefault("docker", {})
    for key in ("enabled", "parent_interface", "subnet", "gateway", "containers",
                "image_name", "network_name", "worker_port"):
        if key in data:
            docker_conf[key] = data[key]
    manager._save_config()
    return {"status": "saved"}


@docker_router.get("/image/status")
async def docker_image_status(request: Request):
    manager = request.app.state.manager
    docker_conf = manager.config.get("docker", {})
    image_name = docker_conf.get("image_name", "demo-generator-worker")
    try:
        pool = manager.get_docker_pool()
        pool._init_docker()
        image = pool._docker.images.get(image_name)
        return {
            "exists": True,
            "id": image.short_id,
            "tags": image.tags,
            "created": image.attrs.get("Created", ""),
        }
    except Exception:
        return {"exists": False}


@docker_router.post("/image/build")
async def docker_image_build(request: Request):
    manager = request.app.state.manager
    try:
        pool = manager.get_docker_pool()
        project_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        await asyncio.to_thread(pool.build_image, project_dir)
        return {"status": "built"}
    except Exception as e:
        logger.error(f"Docker image build failed: {e}")
        raise HTTPException(500, f"Build failed: {e}")


@docker_router.post("/network/create")
async def docker_network_create(request: Request):
    manager = request.app.state.manager
    try:
        pool = manager.get_docker_pool()
        pool._init_docker()
        pool._network_mgr.create_networks()
        return {"status": "created"}
    except Exception as e:
        logger.error(f"Docker network creation failed: {e}")
        raise HTTPException(500, str(e))


@docker_router.post("/network/remove")
async def docker_network_remove(request: Request):
    manager = request.app.state.manager
    try:
        pool = manager.get_docker_pool()
        pool._init_docker()
        pool._network_mgr.remove_networks()
        return {"status": "removed"}
    except Exception as e:
        logger.error(f"Docker network removal failed: {e}")
        raise HTTPException(500, str(e))


@docker_router.post("/containers/start")
async def docker_containers_start(request: Request):
    manager = request.app.state.manager
    try:
        pool = manager.get_docker_pool()
        await pool.start()
        manager._docker_pool = pool
        return {"status": "started", "containers": pool.get_status()}
    except Exception as e:
        logger.error(f"Docker containers start failed: {e}")
        raise HTTPException(500, str(e))


@docker_router.post("/containers/stop")
async def docker_containers_stop(request: Request):
    manager = request.app.state.manager
    try:
        pool = manager.get_docker_pool()
        await pool.cleanup()
        return {"status": "stopped"}
    except Exception as e:
        logger.error(f"Docker containers stop failed: {e}")
        raise HTTPException(500, str(e))
