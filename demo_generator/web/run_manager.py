"""Singleton managing Engine lifecycle, config persistence, and WebSocket broadcasting."""

import asyncio
import json
import os
import tempfile
from datetime import datetime

from ..config import load_config
from ..engine import Engine, RunMode
from ..logger import Logger
from ..stats import Stats
from ..clients import ClientPool


class RunManager:
    def __init__(self, config, config_path):
        self.config = config
        self.config_path = config_path
        self.logger = Logger(
            log_dir=config["generator"].get("log_dir", "./logs"),
            quiet=True,
        )
        self.stats = Stats()
        self._pool = ClientPool(config)
        self._docker_pool = None
        self._engine = None
        self._run_task = None
        self._single_run_task = None
        self._mode = None
        self._start_time = None
        self.ws_clients = set()

        self.logger.subscribe(self._on_log_entry)

    def _on_log_entry(self, entry):
        self.broadcast({"type": "log", "data": entry})

    def broadcast(self, message):
        dead = set()
        for ws in self.ws_clients:
            try:
                asyncio.ensure_future(ws.send_json(message))
            except Exception:
                dead.add(ws)
        self.ws_clients -= dead

    def get_status(self):
        running = self._engine is not None and self._engine.is_running
        elapsed = 0
        if self._start_time and running:
            elapsed = int((datetime.now() - self._start_time).total_seconds())
        return {
            "running": running,
            "mode": self._mode.value if self._mode else None,
            "round": self._engine.round_num if self._engine else 0,
            "elapsed_seconds": elapsed,
            "start_time": self._start_time.isoformat() if self._start_time else None,
            "log_file": self.logger.log_filename,
        }

    def get_stats(self):
        return self.stats.get_cumulative()

    async def _get_active_pool(self):
        if self.config.get("docker", {}).get("enabled"):
            pool = self.get_docker_pool()
            if not pool.is_started:
                self.logger.info("SYSTEM", "Starting Docker containers...")
                await pool.start()
            return pool
        return self._pool

    async def start(self, mode="full"):
        if self._engine and self._engine.is_running:
            raise RuntimeError("Engine is already running")

        self._mode = RunMode(mode)
        pool = await self._get_active_pool()
        self._engine = Engine(self.config, self.logger, self.stats, pool=pool)

        self._engine.on("on_round_start", lambda **kw: self.broadcast({
            "type": "round_start", "data": kw
        }))
        self._engine.on("on_round_complete", lambda **kw: self.broadcast({
            "type": "round_complete",
            "data": {"round_num": kw.get("round_num"), "summary": kw.get("summary")},
        }))

        self._start_time = datetime.now()
        self._run_task = asyncio.create_task(self._run_engine())
        self.broadcast({"type": "status", "data": self.get_status()})

    async def _run_engine(self):
        try:
            await self._engine.start(mode=self._mode)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.info("SYSTEM", f"Engine error: {e}")
        finally:
            self.broadcast({"type": "status", "data": self.get_status()})

    async def stop(self):
        if self._engine and self._engine.is_running:
            self._engine.request_stop()
            if self._run_task:
                self._run_task.cancel()
                try:
                    await asyncio.wait_for(self._run_task, timeout=10)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass
        if self._docker_pool and self._docker_pool.is_started:
            self.logger.info("SYSTEM", "Stopping Docker containers...")
            await self._docker_pool.cleanup()

    async def run_single(self, category_name):
        try:
            pool = await self._get_active_pool()
            engine = Engine(self.config, self.logger, self.stats, pool=pool)
            self._single_run_task = asyncio.create_task(
                engine.run_single_category(category_name)
            )
            await self._single_run_task
        except asyncio.CancelledError:
            self.logger.info("SYSTEM", f"Single run cancelled: {category_name}")
        except Exception as e:
            self.logger.info("ERROR", f"Single run error ({category_name}): {type(e).__name__}: {e}")
            raise
        finally:
            self._single_run_task = None

    async def stop_single(self):
        if self._single_run_task and not self._single_run_task.done():
            self._single_run_task.cancel()
            try:
                await asyncio.wait_for(self._single_run_task, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
            self._single_run_task = None

    def update_config(self, section, key, data):
        if section == "generator":
            self.config["generator"].update(data)
        elif section == "categories" and key:
            if key in self.config["categories"]:
                self.config["categories"][key] = data
            else:
                raise ValueError(f"Unknown category: {key}")
        elif section == "clients":
            self.config["client_profiles"] = data
        elif section == "legitimate":
            self.config["legitimate_traffic"].update(data)
        else:
            raise ValueError(f"Unknown config section: {section}")

        self._save_config()

    def _save_config(self):
        dir_name = os.path.dirname(os.path.abspath(self.config_path))
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(self.config, f, indent=2)
                f.write("\n")
            os.replace(tmp_path, self.config_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def get_docker_pool(self):
        if self._docker_pool is None:
            from ..docker_clients import DockerClientPool
            self._docker_pool = DockerClientPool(self.config)
        return self._docker_pool

    async def cleanup(self):
        await self.stop()
        await self._pool.cleanup()
        if self._docker_pool:
            await self._docker_pool.cleanup()
        self.logger.close()
