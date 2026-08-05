"""Docker-based client pool — runs each client in a container on a macvlan network."""

import asyncio
import logging
import random
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
                    return resp.status == 200
        except Exception:
            return False


class DockerNetworkManager:
    def __init__(self, docker_client, config):
        self._docker = docker_client
        self._config = config

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
                logger.info(f"Macvlan subnet changed ({existing_subnet} -> {subnet}), recreating network")
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
            logger.info(f"Created macvlan network '{network_name}' on {parent_iface} ({subnet})")

        mgmt = self.get_mgmt_network()
        if not mgmt:
            mgmt = self._docker.networks.create(MGMT_NETWORK_NAME, driver="bridge")
            logger.info(f"Created management bridge network '{MGMT_NETWORK_NAME}'")

        return macvlan, mgmt

    def remove_networks(self):
        macvlan = self.get_macvlan_network()
        if macvlan:
            macvlan.remove()
            logger.info("Removed macvlan network")

        mgmt = self.get_mgmt_network()
        if mgmt:
            mgmt.remove()
            logger.info("Removed management network")


class DockerClientPool:
    def __init__(self, config):
        self._config = config
        self._clients = []
        self._docker = None
        self._network_mgr = None
        self._rounds_since_recycle = 0
        self._recycle_interval = config["generator"].get("browser_recycle_rounds", 10)

    @property
    def is_started(self):
        return len(self._clients) > 0

    def _init_docker(self):
        if self._docker is None:
            import docker
            self._docker = docker.from_env()
            self._network_mgr = DockerNetworkManager(self._docker, self._config)

    @staticmethod
    def _generate_ips(start_ip, count):
        parts = start_ip.split(".")
        base = ".".join(parts[:3])
        last = int(parts[3])
        return [f"{base}.{last + i}" for i in range(count)]

    async def start(self):
        if self.is_started:
            return
        self._init_docker()

        docker_conf = self._config["docker"]
        client_count = docker_conf.get("client_count", 3)
        start_ip = docker_conf.get("start_ip", "")

        if not start_ip:
            raise ValueError("Docker start_ip is required")
        if client_count < 1:
            raise ValueError("Docker client_count must be >= 1")

        image_name = docker_conf.get("image_name", "demo-generator-worker")
        if not self.image_exists():
            import os
            project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.build_image(project_dir)

        macvlan, mgmt = self._network_mgr.create_networks()

        ips = self._generate_ips(start_ip, client_count)

        await asyncio.to_thread(self._remove_stale_containers)

        tasks = [
            self._start_container(ip, image_name, macvlan, mgmt)
            for ip in ips
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                logger.error(f"Failed to start container: {r}")
            elif r is not None:
                self._clients.append(r)

        logger.info(f"Started {len(self._clients)} Docker client(s)")

    def _remove_stale_containers(self):
        for c in self._docker.containers.list(all=True, filters={"name": CONTAINER_PREFIX}):
            try:
                c.remove(force=True)
                logger.info(f"Removed stale container '{c.name}'")
            except Exception as e:
                logger.warning(f"Could not remove '{c.name}': {e}")

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

        container = await asyncio.to_thread(
            self._docker.containers.run,
            image_name,
            name=container_name,
            environment=env,
            network=network_name,
            detach=True,
            mem_limit="512m",
            shm_size="256m",
        )

        await asyncio.to_thread(macvlan.disconnect, container)
        await asyncio.to_thread(macvlan.connect, container, ipv4_address=ip)
        await asyncio.to_thread(mgmt.connect, container)

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
        logger.info(f"Container {ip} ready (mgmt={mgmt_ip})")
        return client

    async def _wait_for_health(self, client, timeout=60):
        for _ in range(timeout * 2):
            if await client.health_check():
                return
            await asyncio.sleep(0.5)
        raise TimeoutError(f"Container '{client.container_name}' did not become healthy within {timeout}s")

    def get_clients(self):
        return list(self._clients)

    async def recycle_if_needed(self):
        self._rounds_since_recycle += 1
        if self._rounds_since_recycle >= self._recycle_interval:
            self._rounds_since_recycle = 0
            tasks = [c.recycle() for c in self._clients]
            await asyncio.gather(*tasks, return_exceptions=True)
            logger.info("Recycled all Docker client browser contexts")

    async def cleanup(self):
        self._init_docker()
        for client in self._clients:
            try:
                container = self._docker.containers.get(client.container_id)
                container.remove(force=True)
                logger.info(f"Removed container '{client.container_name}'")
            except Exception as e:
                logger.error(f"Failed to remove '{client.container_name}': {e}")
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
        self._init_docker()
        image_name = self._config["docker"].get("image_name", "demo-generator-worker")
        try:
            self._docker.images.get(image_name)
            return True
        except Exception:
            return False

    def build_image(self, path="."):
        self._init_docker()
        image_name = self._config["docker"].get("image_name", "demo-generator-worker")
        logger.info(f"Building Docker image '{image_name}'...")
        image, build_log = self._docker.images.build(path=path, tag=image_name, rm=True)
        for chunk in build_log:
            if "stream" in chunk:
                line = chunk["stream"].strip()
                if line:
                    logger.info(f"  {line}")
        logger.info(f"Image '{image_name}' built successfully")
        return image
