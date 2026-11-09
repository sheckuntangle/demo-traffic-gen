"""Docker-based client pool — runs each client in a container on a macvlan network."""

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from typing import Optional

from .clients import (
    ClientProfile,
    FALLBACK_USER_AGENTS,
    FALLBACK_VIEWPORTS,
    FALLBACK_TIMEZONES,
)
from .primitives import TestResult

logger = logging.getLogger("demo_generator.docker")

MGMT_NETWORK_NAME = "demogen-mgmt"
CONTAINER_PREFIX = "demogen-client-"
WORKER_PORT = 8090


@dataclass
class DockerClient:
    profile: ClientProfile
    container_id: str
    container_name: str
    macvlan_ip: str
    mgmt_ip: str
    last_health_error: str = ""

    @property
    def base_url(self):
        return f"http://{self.mgmt_ip}:{WORKER_PORT}"

    async def run_category(self, category, config):
        import aiohttp
        url = f"{self.base_url}/run"
        payload = {"category": category.name, "config": config}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=600)) as resp:
                if resp.status != 200:
                    detail = await resp.text()
                    raise RuntimeError(f"Worker error ({resp.status}): {detail}")
                data = await resp.json()
                return [TestResult.from_dict(d) for d in data]

    async def recycle(self):
        import aiohttp
        url = f"{self.base_url}/recycle"
        async with aiohttp.ClientSession() as session:
            async with session.post(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                return resp.status == 200

    async def health_check(self):
        import aiohttp
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}/health", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    self.last_health_error = "" if resp.status == 200 else f"HTTP {resp.status}"
                    return resp.status == 200
        except Exception as e:
            self.last_health_error = f"{type(e).__name__}: {e}"
            return False


class DockerNetworkManager:
    def __init__(self, docker_client, config, progress=None):
        self._docker = docker_client
        self._config = config
        self._progress = progress or logger.info

    def get_macvlan_network(self):
        network_name = self._config["docker"].get("network_name", "demogen-macvlan")
        try:
            return self._docker.networks.get(network_name)
        except Exception:
            return None

    def get_mgmt_network(self):
        try:
            return self._docker.networks.get(MGMT_NETWORK_NAME)
        except Exception:
            return None

    def create_networks(self):
        docker_conf = self._config["docker"]
        network_name = docker_conf.get("network_name", "demogen-macvlan")
        parent_iface = docker_conf["parent_interface"]
        subnet = docker_conf["subnet"]
        gateway = docker_conf["gateway"]

        if not parent_iface or not subnet or not gateway:
            raise ValueError("parent_interface, subnet, and gateway are required")
        if "/" not in subnet:
            raise ValueError(f"Subnet must be in CIDR format (e.g. 192.168.41.0/24), got: {subnet}")

        macvlan = self.get_macvlan_network()
        if macvlan:
            existing_subnet = ""
            try:
                macvlan.reload()
                pools = macvlan.attrs.get("IPAM", {}).get("Config", [])
                if pools:
                    existing_subnet = pools[0].get("Subnet", "")
            except Exception:
                pass
            if existing_subnet != subnet:
                self._progress(f"Macvlan subnet changed ({existing_subnet} -> {subnet}), recreating network")
                macvlan.remove()
                macvlan = None

        if not macvlan:
            import docker as docker_mod
            ipam_pool = docker_mod.types.IPAMPool(subnet=subnet, gateway=gateway)
            ipam_config = docker_mod.types.IPAMConfig(pool_configs=[ipam_pool])
            macvlan = self._docker.networks.create(
                network_name,
                driver="macvlan",
                options={"parent": parent_iface},
                ipam=ipam_config,
            )
            self._progress(f"Created macvlan network '{network_name}' on {parent_iface} ({subnet})")

        mgmt = self.get_mgmt_network()
        if not mgmt:
            mgmt = self._docker.networks.create(MGMT_NETWORK_NAME, driver="bridge")
            self._progress(f"Created management bridge network '{MGMT_NETWORK_NAME}'")

        return macvlan, mgmt

    def remove_networks(self):
        macvlan = self.get_macvlan_network()
        if macvlan:
            macvlan.remove()
            self._progress("Removed macvlan network")

        mgmt = self.get_mgmt_network()
        if mgmt:
            mgmt.remove()
            self._progress("Removed management network")


class DockerClientPool:
    def __init__(self, config, progress=None):
        self._config = config
        self._clients = []
        self._containers = []
        self._progress = progress
        self._loop = None
        self._docker = None
        self._network_mgr = None
        self._rounds_since_recycle = 0
        self._recycle_interval = config["generator"].get("browser_recycle_rounds", 10)

    def _log(self, message):
        logger.info(message)
        if self._progress and self._loop:
            self._loop.call_soon_threadsafe(self._progress, message)

    async def _docker_call(self, label, function, *args, **kwargs):
        self._log(label)
        started = time.monotonic()
        task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
        try:
            while True:
                done, _ = await asyncio.wait({task}, timeout=10)
                if done:
                    result = task.result()
                    self._log(f"{label} — done ({time.monotonic() - started:.1f}s)")
                    return result
                self._log(f"{label} — still working ({time.monotonic() - started:.0f}s)")
        except asyncio.CancelledError:
            # Docker SDK calls cannot be cancelled mid-request. Finish before cleanup.
            self._log(f"Stopping: waiting for Docker operation to finish: {label}")
            try:
                await task
            finally:
                raise
        except Exception as e:
            self._log(f"ERROR: {label} failed: {type(e).__name__}: {e}")
            raise

    @property
    def is_started(self):
        return len(self._clients) > 0

    def _init_docker(self):
        if self._docker is None:
            import docker
            self._docker = docker.from_env(timeout=60)
            self._network_mgr = DockerNetworkManager(self._docker, self._config, self._log)

    @staticmethod
    def _generate_ips(start_ip, count):
        parts = start_ip.split(".")
        base = ".".join(parts[:3])
        last = int(parts[3])
        return [f"{base}.{last + i}" for i in range(count)]

    async def start(self):
        if self.is_started:
            return
        self._loop = asyncio.get_running_loop()
        await self._docker_call("Connecting to Docker daemon", self._init_docker)

        docker_conf = self._config["docker"]
        client_count = docker_conf.get("client_count", 3)
        start_ip = docker_conf.get("start_ip", "")

        if not start_ip:
            raise ValueError("Docker start_ip is required")
        if client_count < 1:
            raise ValueError("Docker client_count must be >= 1")

        image_name = docker_conf.get("image_name", "demo-generator-worker")
        if not await self._docker_call(f"Checking worker image {image_name}", self.image_exists):
            import os
            project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            await self._docker_call(f"Building worker image {image_name} (first build may take several minutes)", self.build_image, project_dir)

        self._log(f"Network settings: parent={docker_conf.get('parent_interface')}, "
                  f"subnet={docker_conf.get('subnet')}, gateway={docker_conf.get('gateway')}")
        macvlan, mgmt = await self._docker_call("Preparing macvlan and management networks", self._network_mgr.create_networks)

        ips = self._generate_ips(start_ip, client_count)

        await self._docker_call("Removing stale traffic containers", self._remove_stale_containers)

        tasks = [
            self._start_container(ip, image_name, macvlan, mgmt)
            for ip in ips
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                self._log(f"ERROR: Failed to start container: {type(r).__name__}: {r}")
            elif r is not None:
                self._clients.append(r)

        self._log(f"Docker startup: {len(self._clients)}/{client_count} clients ready")
        if len(self._clients) != client_count:
            raise RuntimeError("Docker startup incomplete; see container errors above")

    def _remove_stale_containers(self):
        for c in self._docker.containers.list(all=True, filters={"name": CONTAINER_PREFIX}):
            try:
                c.remove(force=True)
                self._log(f"Removed stale container '{c.name}'")
            except Exception as e:
                self._log(f"WARNING: Could not remove '{c.name}': {e}")

    async def _start_container(self, ip, image_name, macvlan, mgmt):
        ip_slug = ip.replace(".", "-")
        container_name = f"{CONTAINER_PREFIX}{ip_slug}"

        viewport = random.choice(FALLBACK_VIEWPORTS)
        user_agent = random.choice(FALLBACK_USER_AGENTS)
        timezone = random.choice(FALLBACK_TIMEZONES)

        env = {
            "WORKER_PROFILE_NAME": ip,
            "WORKER_USER_AGENT": user_agent,
            "WORKER_VIEWPORT_WIDTH": str(viewport["width"]),
            "WORKER_VIEWPORT_HEIGHT": str(viewport["height"]),
            "WORKER_TIMEZONE": timezone,
            "WORKER_LOCALE": "en-US",
        }

        network_name = self._config["docker"].get("network_name", "demogen-macvlan")

        def create_container(*args, **kwargs):
            container = self._docker.containers.run(*args, **kwargs)
            # Track immediately, even if cancellation arrives during the SDK call.
            self._containers.append(container)
            return container

        container = await self._docker_call(
            f"Creating container {container_name} for {ip}", create_container,
            image_name,
            name=container_name,
            environment=env,
            network=network_name,
            detach=True,
            mem_limit="512m",
            shm_size="256m",
        )

        await self._docker_call(f"Configuring {ip}: disconnecting temporary macvlan address", macvlan.disconnect, container)
        await self._docker_call(f"Configuring {ip}: assigning macvlan IP", macvlan.connect, container, ipv4_address=ip)
        await self._docker_call(f"Configuring {ip}: attaching management network", mgmt.connect, container)

        await asyncio.to_thread(container.reload)
        mgmt_ip = container.attrs["NetworkSettings"]["Networks"][MGMT_NETWORK_NAME]["IPAddress"]

        profile = ClientProfile(
            name=ip,
            user_agent=user_agent,
            viewport=viewport,
            timezone=timezone,
            locale="en-US",
            source_ip=ip,
        )

        client = DockerClient(
            profile=profile,
            container_id=container.id,
            container_name=container_name,
            macvlan_ip=ip,
            mgmt_ip=mgmt_ip,
        )

        await self._wait_for_health(client)
        self._log(f"Container {ip} ready (mgmt={mgmt_ip})")
        return client

    async def _wait_for_health(self, client, timeout=60):
        started = time.monotonic()
        deadline = started + timeout
        next_log = started
        self._log(f"Waiting for {client.container_name} worker at {client.base_url}/health (timeout {timeout}s)")
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            try:
                healthy = await asyncio.wait_for(client.health_check(), timeout=remaining)
            except asyncio.TimeoutError:
                healthy = False
            if healthy:
                self._log(f"Worker {client.macvlan_ip} healthy after {time.monotonic() - started:.1f}s")
                return
            now = time.monotonic()
            if now >= next_log:
                self._log(f"Worker {client.macvlan_ip} not ready yet ({now - started:.0f}s/{timeout}s): "
                          f"{getattr(client, 'last_health_error', '') or 'health endpoint not responding'}")
                next_log = now + 10
            await asyncio.sleep(min(0.5, max(0, deadline - time.monotonic())))
        try:
            container = await asyncio.to_thread(self._docker.containers.get, client.container_id)
            await asyncio.to_thread(container.reload)
            self._log(f"ERROR: {client.container_name} state: {container.attrs.get('State', {})}")
            output = await asyncio.to_thread(container.logs, tail=30)
            self._log(f"Worker log tail ({client.container_name}):\n{output.decode(errors='replace')}")
        except Exception as e:
            self._log(f"Could not read worker diagnostics: {e}")
        raise TimeoutError(f"Container '{client.container_name}' did not become healthy within {timeout}s; check worker logs and management network connectivity")

    def get_clients(self):
        return list(self._clients)

    async def recycle_if_needed(self):
        self._rounds_since_recycle += 1
        if self._rounds_since_recycle >= self._recycle_interval:
            self._rounds_since_recycle = 0
            tasks = [c.recycle() for c in self._clients]
            await asyncio.gather(*tasks, return_exceptions=True)
            self._log("Recycled all Docker client browser contexts")

    async def cleanup(self):
        for container in self._containers:
            try:
                await self._docker_call(f"Removing container {container.name}", container.remove, force=True)
            except Exception as e:
                self._log(f"ERROR: Failed to remove '{container.name}': {e}")
        self._containers = []
        self._clients = []

    def get_status(self):
        self._init_docker()
        status = []
        for client in self._clients:
            try:
                container = self._docker.containers.get(client.container_id)
                container.reload()
                state = container.status
            except Exception:
                state = "unknown"
            status.append({
                "name": client.profile.name,
                "container_name": client.container_name,
                "macvlan_ip": client.macvlan_ip,
                "mgmt_ip": client.mgmt_ip,
                "status": state,
            })
        return status

    def image_exists(self):
        from docker.errors import ImageNotFound
        self._init_docker()
        image_name = self._config["docker"].get("image_name", "demo-generator-worker")
        try:
            self._docker.images.get(image_name)
            return True
        except ImageNotFound:
            return False

    def build_image(self, path="."):
        self._init_docker()
        image_name = self._config["docker"].get("image_name", "demo-generator-worker")
        self._log(f"Building Docker image '{image_name}'...")
        # Low-level streaming API emits output while the build is running.
        for chunk in self._docker.api.build(path=path, tag=image_name, rm=True, decode=True):
            if chunk.get("error"):
                raise RuntimeError(chunk["error"])
            line = chunk.get("stream", "").strip()
            if not line and chunk.get("status"):
                line = " ".join(str(chunk.get(key, "")) for key in ("id", "status", "progress")).strip()
            if line:
                self._log(f"Build: {line}")
        self._log(f"Image '{image_name}' built successfully")
        return self._docker.images.get(image_name)
