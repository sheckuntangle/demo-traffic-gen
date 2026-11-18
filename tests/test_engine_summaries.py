import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from demo_generator.categories.app_control import AppControl
from demo_generator.engine import Engine
from demo_generator.primitives import TestResult
from demo_generator.stats import Stats


class EngineSummaryTests(unittest.IsolatedAsyncioTestCase):
    def engine(self):
        return Engine({"generator": {"round_interval_seconds": 300, "legitimate_interval_seconds": 45,
                                     "max_rounds": 0}, "categories": {}}, Mock(), Stats(),
                      pool=SimpleNamespace(start=AsyncMock(), recycle_if_needed=AsyncMock()))

    async def test_section_and_schedule_summaries_identify_clients_and_exclude_phase_markers(self):
        engine = self.engine()
        category = AppControl()
        async def run(category, config):
            results = [TestResult("INFO", "Starting phase", True), TestResult("WEB", "good", True),
                       TestResult("WEB", "bad", False, message="Timeout")]
            for result in results:
                category.emit_result(result)
            return results
        client = SimpleNamespace(profile=SimpleNamespace(name="client-50"), macvlan_ip="192.168.77.50", run_category=run)
        await engine._run_category_on_client(client, category)
        self.assertEqual(len(engine._activity), 1)
        record = engine._activity[0]
        self.assertEqual((record["passed"], record["failed"], record["status"]), (1, 1, "completed"))
        self.assertEqual(record["source_ip"], "192.168.77.50")
        engine.log_summary("SCHEDULE SUMMARY", "completed")
        report = engine._logger.summary.call_args.args[1]
        self.assertEqual(report["totals"]["passed"], 1)
        self.assertEqual(report["totals"]["failed"], 1)
        self.assertEqual(report["clients"][0]["sections"][0]["category"], "app_control")
        messages = "\n".join(call.args[1] for call in engine._logger.info.call_args_list) + engine._logger.summary.call_args.args[2]
        for text in ("client-50", "192.168.77.50", "App Control", "1 passed, 1 failed", "Timeout", "execution="):
            self.assertIn(text, messages)
        self.assertEqual(engine._logger.log_result.call_count, 3)  # No duplicate returned results.
        self.assertEqual(engine._stats.get_cumulative()["total_pass"], 1)
        self.assertEqual(engine._stats.get_cumulative()["total_fail"], 1)

    async def test_partial_results_and_cancellation_are_summarized(self):
        engine = self.engine()
        entered = asyncio.Event()
        async def run(category, config):
            category.emit_result(TestResult("WEB", "done", True))
            entered.set()
            await asyncio.Event().wait()
        client = SimpleNamespace(profile=SimpleNamespace(name="client-51", source_ip="192.168.77.51"), run_category=run)
        task = asyncio.create_task(engine._run_category_on_client(client, AppControl()))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(engine._activity[0]["status"], "cancelled")
        self.assertEqual(engine._activity[0]["passed"], 1)

    async def test_worker_error_keeps_partial_results_in_summary(self):
        engine = self.engine()
        async def run(category, config):
            category.emit_result(TestResult("WEB", "done", True))
            raise RuntimeError("worker disconnected")
        client = SimpleNamespace(profile=SimpleNamespace(name="client-52"), run_category=run)
        await engine._run_category_on_client(client, AppControl())
        self.assertEqual(engine._activity[0]["status"], "error")
        self.assertEqual((engine._activity[0]["passed"], engine._activity[0]["failed"]), (1, 1))

    async def test_duration_cancels_inflight_work_and_selects_only_requested_loops(self):
        for selected, expected in ((["legitimate"], (True, False)), (["app_control"], (False, True)),
                                   (["app_control", "legitimate"], (True, True))):
            with self.subTest(selected=selected):
                engine = self.engine()
                cancelled = asyncio.Event()
                async def loops(**kwargs):
                    try:
                        await asyncio.Event().wait()
                    finally:
                        cancelled.set()
                engine._run_full_mode = AsyncMock(side_effect=loops)
                await engine.run_timed(0.01, selected)
                engine._run_full_mode.assert_awaited_once_with(include_legitimate=expected[0], include_triggers=expected[1])
                self.assertTrue(cancelled.is_set())
                self.assertFalse(engine.is_running)

    async def test_concurrent_loops_use_configured_intervals_and_delay_first_trigger(self):
        engine = self.engine()
        legit_finished = asyncio.Event()
        trigger_waiting = asyncio.Event()
        release_trigger = asyncio.Event()
        trigger_started = asyncio.Event()
        async def legit():
            legit_finished.set()
        async def triggers():
            trigger_started.set()
        async def sleep(seconds):
            if seconds == 300 and not trigger_started.is_set():
                trigger_waiting.set()
                await release_trigger.wait()
            else:
                await asyncio.Event().wait()
        engine._execute_legitimate_round = AsyncMock(side_effect=legit)
        engine._execute_trigger_round = AsyncMock(side_effect=triggers)
        engine._interruptible_sleep = AsyncMock(side_effect=sleep)
        task = asyncio.create_task(engine.run_timed(60, ["app_control", "legitimate"]))
        try:
            await asyncio.wait_for(legit_finished.wait(), 1)
            await asyncio.wait_for(trigger_waiting.wait(), 1)
            self.assertFalse(trigger_started.is_set())
            self.assertIn(45, [call.args[0] for call in engine._interruptible_sleep.await_args_list])
            release_trigger.set()
            await asyncio.wait_for(trigger_started.wait(), 1)
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertFalse(engine.is_running)
        self.assertEqual(engine._active_tasks, [])
