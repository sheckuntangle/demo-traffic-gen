import asyncio
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, WebSocketDisconnect

from demo_generator.web.run_manager import RunManager
from demo_generator.web.routes_api import StartRequest, run_single, start
from demo_generator.web.routes_ws import websocket_endpoint


class SharedRunsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.config = {"generator": {"log_dir": self.directory.name}, "client_profiles": []}
        self.manager = RunManager(self.config, self.directory.name + "/config.json")
        self.request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(manager=self.manager)))

    async def asyncTearDown(self):
        await self.manager.cleanup()
        self.directory.cleanup()

    async def test_new_browser_receives_logs_and_active_category(self):
        gate = asyncio.Event()
        with patch.object(self.manager, "_get_active_pool", side_effect=gate.wait):
            self.manager.logger.info("SYSTEM", "Visible in another browser")
            await self.manager.run_single("dns_filter")
            socket = SimpleNamespace(
                app=self.request.app, accept=AsyncMock(), send_json=AsyncMock(),
                receive_text=AsyncMock(side_effect=WebSocketDisconnect()),
            )
            # WebSocket objects need identity hashing, as Starlette's objects do.
            class Socket:
                pass
            ws = Socket()
            ws.__dict__.update(socket.__dict__)
            await websocket_endpoint(ws)
            snapshot = ws.send_json.call_args_list[0].args[0]["data"]
            self.assertEqual(snapshot["logs"][-1]["message"], "Visible in another browser")
            self.assertEqual(snapshot["status"]["category"], "dns_filter")
            self.assertTrue(snapshot["status"]["running"])
            await self.manager.stop()
            self.assertFalse(self.manager.get_status()["running"])

    async def test_all_run_combinations_rejected_during_startup(self):
        for first in ("category", "scheduled"):
            with patch.object(self.manager, "_get_active_pool", new=AsyncMock(side_effect=asyncio.CancelledError)):
                if first == "category":
                    await self.manager.run_single("security")
                else:
                    await self.manager.start("full")
                for endpoint, args in ((run_single, ("dns_filter", self.request)),
                                       (start, (StartRequest(), self.request))):
                    with self.assertRaises(HTTPException) as error:
                        await endpoint(*args)
                    self.assertEqual(error.exception.status_code, 409)
                await self.manager.stop()
                self.assertEqual(self.manager.get_status()["phase"], "idle")

    async def test_completion_and_failure_release_runner(self):
        engine = SimpleNamespace(on=lambda *args: None, run_single_category=AsyncMock(),
                                 start=AsyncMock(), round_num=0)
        with patch.object(self.manager, "_get_active_pool", new=AsyncMock()), \
             patch("demo_generator.web.run_manager.Engine", return_value=engine):
            await self.manager.run_single("security")
            await self.manager._single_run_task
            self.assertFalse(self.manager.get_status()["running"])
            await self.manager.start()
            await self.manager._run_task
            self.assertFalse(self.manager.get_status()["running"])
        with patch.object(self.manager, "_get_active_pool", new=AsyncMock(side_effect=RuntimeError("startup failed"))):
            await self.manager.start()
            await self.manager._run_task
            self.assertFalse(self.manager.get_status()["running"])
            self.assertIn("startup failed", self.manager.get_log_history()[-1]["message"])

    async def test_runner_stays_reserved_until_cleanup_finishes(self):
        cleanup_started = asyncio.Event()
        release_cleanup = asyncio.Event()

        async def cleanup():
            cleanup_started.set()
            await release_cleanup.wait()

        self.manager._docker_pool = SimpleNamespace(cleanup=cleanup)
        with patch.object(self.manager, "_get_active_pool", new=AsyncMock(side_effect=RuntimeError("failed"))):
            await self.manager.start()
            await cleanup_started.wait()
            self.assertEqual(self.manager.get_status()["phase"], "stopping")
            with self.assertRaises(HTTPException) as error:
                await run_single("security", self.request)
            self.assertEqual(error.exception.status_code, 409)
            stop_task = asyncio.create_task(self.manager.stop())
            await asyncio.sleep(0)
            self.assertFalse(stop_task.done())
            release_cleanup.set()
            await stop_task
            self.assertFalse(self.manager.get_status()["running"])
        self.manager._docker_pool = None

    async def test_history_survives_manager_restart(self):
        self.manager.logger.info("SYSTEM", "Saved history")
        await self.manager.cleanup()
        self.manager = RunManager(self.config, self.directory.name + "/config.json")
        self.assertEqual(self.manager.get_log_history()[-1]["message"], "Saved history")
        self.assertFalse(self.manager.get_status()["running"])


if __name__ == "__main__":
    unittest.main()
