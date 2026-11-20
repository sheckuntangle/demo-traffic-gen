import asyncio
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException, WebSocketDisconnect

from demo_generator.web.run_manager import RunManager
from demo_generator.web.routes_api import CategoryRunRequest, StartRequest, run_single, start
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
        engine = SimpleNamespace(log_summary=Mock(), on=lambda *args: None, run_single_category=AsyncMock(),
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

    async def test_manual_repetitions_run_sequentially_without_resetting_stats(self):
        from unittest.mock import call
        engine = SimpleNamespace(log_summary=Mock(), on=lambda *args: None, run_single_category=AsyncMock(), round_num=0)
        with patch.object(self.manager, "_get_active_pool", new=AsyncMock()), \
             patch("demo_generator.web.run_manager.Engine", return_value=engine), \
             patch.object(self.manager.stats, "reset_category") as reset:
            await run_single("legitimate", self.request, CategoryRunRequest(run_count=5))
            with self.assertRaises(HTTPException) as error:
                await run_single("security", self.request)
            self.assertEqual(error.exception.status_code, 409)
            await self.manager._single_run_task
            self.assertEqual(engine.run_single_category.await_args_list,
                             [call("legitimate", reset_stats=False)] * 5)
            reset.assert_called_once_with("legitimate")
            self.assertFalse(self.manager.get_status()["running"])

    async def test_stop_cancels_remaining_manual_repetitions(self):
        entered = asyncio.Event()
        async def run(*args, **kwargs):
            entered.set()
            await asyncio.Event().wait()
        engine = SimpleNamespace(log_summary=Mock(), on=lambda *args: None, run_single_category=AsyncMock(side_effect=run),
                                 request_stop=lambda: None, round_num=0)
        with patch.object(self.manager, "_get_active_pool", new=AsyncMock()), \
             patch("demo_generator.web.run_manager.Engine", return_value=engine):
            await self.manager.run_single("legitimate", run_count=5)
            await entered.wait()
            await self.manager.stop()
            self.assertEqual(engine.run_single_category.await_count, 1)
            self.assertFalse(self.manager.get_status()["running"])

    async def test_stopped_full_run_prints_client_summary_after_docker_cleanup(self):
        from demo_generator.primitives import TestResult
        entered = asyncio.Event()
        async def run(category, config):
            category.emit_result(TestResult("DNS", "example.com", True))
            entered.set()
            await asyncio.Event().wait()
        client = SimpleNamespace(profile=SimpleNamespace(name="client-50"), macvlan_ip="192.168.77.50", run_category=run)
        pool = SimpleNamespace(start=AsyncMock(), get_clients=lambda: [client])
        self.manager.config["generator"].update(round_interval_seconds=300, legitimate_interval_seconds=45, max_rounds=0)
        self.manager.config["categories"] = {}
        async def cleanup():
            self.manager.logger.info("DOCKER", "All 1 Docker client containers stopped and removed.")
        self.manager._docker_pool = SimpleNamespace(cleanup=cleanup)
        with patch.object(self.manager, "_get_active_pool", new=AsyncMock(return_value=pool)):
            await self.manager.start("full")
            await asyncio.wait_for(entered.wait(), 1)
            await self.manager.stop()
        entries = self.manager.get_log_history()
        cleanup_index = next(i for i, entry in enumerate(entries) if "All 1 Docker" in entry["message"])
        summary_index = next(i for i, entry in enumerate(entries) if entry["category"] == "RUN SUMMARY")
        self.assertLess(cleanup_index, summary_index)
        summary = "\n".join(entry["message"] for entry in entries if entry["category"] == "RUN SUMMARY")
        for text in ("stopped by user/controller", "client-50", "192.168.77.50", "Legitimate Traffic", "1 passed", "1 cancelled"):
            self.assertIn(text, summary)
        report = next(entry["report"] for entry in entries if entry["test_type"] == "SUMMARY")
        self.assertEqual(report["clients"][0]["sections"][0]["category"], "legitimate")
        self.assertFalse(self.manager.get_status()["running"])

    async def test_invalid_manual_counts_do_not_reserve_runner(self):
        from pydantic import ValidationError
        for count in (0, -1, 1001, True, 2.5, "5"):
            with self.subTest(count=count):
                with self.assertRaises(ValidationError):
                    CategoryRunRequest(run_count=count)
                with self.assertRaises(ValueError):
                    await self.manager.run_single("legitimate", run_count=count)
                self.assertFalse(self.manager.get_status()["running"])

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
        stamp = self.manager.get_log_history()[-1]["timestamp"]
        self.assertIsNotNone(datetime.fromisoformat(stamp).utcoffset())
        self.manager.logger.log_result("legitimate", "DNS", "example.com", "PASS")
        self.assertIsNotNone(datetime.fromisoformat(self.manager.get_log_history()[-1]["timestamp"]).utcoffset())
        self.manager.logger.info("SYSTEM", "Saved history")
        await self.manager.cleanup()
        self.manager = RunManager(self.config, self.directory.name + "/config.json")
        self.assertEqual(self.manager.get_log_history()[-1]["message"], "Saved history")
        self.assertFalse(self.manager.get_status()["running"])

    async def test_structured_summary_survives_restart(self):
        report = {"outcome": "completed", "totals": {"passed": 3}, "clients": []}
        self.manager.logger.summary("RUN SUMMARY", report, "Summary\n3 passed")
        await self.manager.cleanup()
        self.manager = RunManager(self.config, self.directory.name + "/config.json")
        entry = self.manager.get_log_history()[-1]
        self.assertEqual(entry["test_type"], "SUMMARY")
        self.assertEqual(entry["report"], report)
        self.assertEqual(entry["message"], "Summary\n3 passed")

    async def test_delete_removes_only_generated_logs_and_logging_continues(self):
        from demo_generator.web.routes_api import delete_logs
        self.manager.logger.info("SYSTEM", "Old saved log")
        self.manager.stats.record("app_control", True)
        self.manager.stats.record("legitimate", False)
        log_dir = Path(self.directory.name)
        archives = [log_dir / "traffic_generator_20260101_120000.log",
                    log_dir / "traffic_generator_20260101_120000.log.1", log_dir / "web_history.jsonl.1"]
        for path in archives:
            path.write_text("old log")
        unrelated = log_dir / "keep-me.txt"
        unrelated.write_text("keep me")
        with patch.object(self.manager, "broadcast") as broadcast:
            response = await delete_logs(self.request)
        self.assertEqual(response["status"], "deleted")
        self.assertEqual(broadcast.call_count, 2)
        self.assertEqual(broadcast.call_args_list[0].args[0], {"type": "logs_deleted"})
        self.assertEqual(broadcast.call_args_list[1].args[0], {"type": "stats", "data": self.manager.get_stats()})
        self.assertEqual(self.manager.get_stats()["total_pass"], 0)
        self.assertEqual(self.manager.get_stats()["total_fail"], 0)
        self.assertEqual(self.manager.get_log_history(), [])
        self.assertTrue(all(not path.exists() for path in archives))
        self.assertEqual(unrelated.read_text(), "keep me")
        self.assertEqual(Path(self.manager.logger.log_filename).read_text(), "")
        self.assertEqual((log_dir / "web_history.jsonl").read_text(), "")
        self.manager.logger.info("SYSTEM", "New saved log")
        self.assertIn("New saved log", Path(self.manager.logger.log_filename).read_text())
        await self.manager.cleanup()
        self.manager = RunManager(self.config, self.directory.name + "/config.json")
        self.assertEqual([entry["message"] for entry in self.manager.get_log_history()], ["New saved log"])

    async def test_clear_counters_preserves_logs_and_running_state_and_broadcasts(self):
        from demo_generator.web.routes_api import clear_counters
        self.manager.logger.info("SYSTEM", "Preserved log")
        self.manager.stats.record("app_control", True)
        self.manager.stats.finish_round()
        self.manager.stats.record("legitimate", False)
        self.manager._phase = "running"
        with patch.object(self.manager, "broadcast") as broadcast:
            result = await clear_counters(self.request)
        self.assertEqual(result["total_pass"], 0)
        self.assertEqual(result["total_fail"], 0)
        self.assertEqual(result["categories"], {})
        self.assertEqual(result["total_rounds"], 1)
        self.assertEqual(self.manager.stats.get_round_summary()["total_fail"], 0)
        self.assertEqual(self.manager._phase, "running")
        broadcast.assert_called_once_with({"type": "stats", "data": result})
        self.assertEqual(self.manager.get_log_history()[-1]["message"], "Preserved log")
        self.assertIn("Preserved log", Path(self.manager.logger.log_filename).read_text())
        self.manager.stats.record("legitimate", True)
        self.assertEqual(self.manager.get_stats()["total_pass"], 1)
        self.manager._phase = "idle"

    async def test_legacy_history_gets_controller_timezone_before_replay(self):
        await self.manager.cleanup()
        path = Path(self.directory.name) / "web_history.jsonl"
        path.write_text(json.dumps({"timestamp": "2026-11-18 18:39:00", "message": "Legacy"}) + "\n")
        self.manager = RunManager(self.config, self.directory.name + "/config.json")
        stamp = self.manager.get_log_history()[-1]["timestamp"]
        expected = datetime(2026, 11, 18, 18, 39).astimezone()
        self.assertEqual(datetime.fromisoformat(stamp), expected)


if __name__ == "__main__":
    unittest.main()
