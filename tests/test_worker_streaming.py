import asyncio
from contextlib import ExitStack
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from demo_generator.categories import TestCategory
from demo_generator.docker_clients import DockerClient
from demo_generator.primitives import TestResult
from demo_generator.worker.service import stream_category


class WorkerStreamingTests(unittest.IsolatedAsyncioTestCase):
    async def test_categories_emit_each_result_before_the_next_delay(self):
        from demo_generator.categories import get_all_categories
        config = json.loads((Path(__file__).resolve().parents[1] / "config.example.json").read_text())
        for name, cls in get_all_categories().items():
            if name == "idps":  # IDPS already emits each script result.
                continue
            with self.subTest(category=name), ExitStack() as stack:
                category = cls()
                module = importlib.import_module(cls.__module__)
                seen = []
                category._on_result = seen.append
                async def primitive(*args, **kwargs):
                    return TestResult("TEST", str(args[0]), True)
                for primitive_name in ("ping", "tcp_connect", "dns_query", "web_request", "ssh_connect"):
                    if hasattr(module, primitive_name):
                        stack.enter_context(patch.object(module, primitive_name, side_effect=primitive))
                async def delay():
                    self.assertTrue(seen, "No result emitted before the inter-test delay")
                for delay_name in ("_delay", "_human_delay", "_dns_delay", "_web_delay", "_ping_delay"):
                    if hasattr(module, delay_name):
                        stack.enter_context(patch.object(module, delay_name, side_effect=delay))
                results = await category.run(SimpleNamespace(clear_cookies=AsyncMock()), config)
                self.assertGreater(len(results), 0)
                self.assertEqual([id(result) for result in results], [id(result) for result in seen])

    async def test_client_receives_results_before_worker_finishes_without_duplicates(self):
        gate = asyncio.Event()
        received = asyncio.Event()
        finished = asyncio.Event()

        class Category(TestCategory):
            async def run(self, context, config, source_ip=None):
                first = TestResult("DNS", "example.com", True)
                self.emit_result(first)
                await gate.wait()
                second = TestResult("PING", "1.1.1.1", True)
                finished.set()
                return [first, second]  # Mix emitted and returned-only results.

        worker_category = Category()
        controller_category = Category()
        seen = []

        def on_result(result):
            result.client_name = "client-1"
            seen.append(result)
            received.set()

        controller_category._on_result = on_result
        async def content():
            async for line in stream_category(worker_category, None, {}):
                yield line.encode()

        response = MagicMock(status=200, content_type="application/x-ndjson", content=content())
        response.__aenter__ = AsyncMock(return_value=response)
        session = MagicMock()
        session.post.return_value = response
        session.__aenter__ = AsyncMock(return_value=session)
        client = DockerClient(SimpleNamespace(name="client-1"), "id", "name", "10.0.0.1", "172.18.0.2")
        with patch("aiohttp.ClientSession", return_value=session):
            task = asyncio.create_task(client.run_category(controller_category, {}))
            try:
                await asyncio.wait_for(received.wait(), 1)
                self.assertFalse(finished.is_set())
                self.assertFalse(task.done())
                self.assertEqual([result.target for result in seen], ["example.com"])
            finally:
                gate.set()
            results = await asyncio.wait_for(task, 1)
        self.assertEqual([result.target for result in seen], ["example.com", "1.1.1.1"])
        self.assertEqual(results, seen)
        self.assertTrue(all(result.client_name for result in results))
        self.assertIsNone(worker_category._on_result)

    async def test_worker_errors_follow_already_emitted_results(self):
        class Category(TestCategory):
            async def run(self, context, config, source_ip=None):
                self.emit_result(TestResult("DNS", "example.com", True))
                raise RuntimeError("test failure")
        with self.assertLogs("demo_generator.worker", level="ERROR"):
            events = [json.loads(line) async for line in stream_category(Category(), None, {})]
        self.assertEqual([event["type"] for event in events], ["result", "error"])
        self.assertEqual(events[-1]["detail"], "test failure")

    async def test_disconnected_stream_cancels_worker(self):
        cancelled = asyncio.Event()
        class Category(TestCategory):
            async def run(self, context, config, source_ip=None):
                try:
                    self.emit_result(TestResult("DNS", "example.com", True))
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
        category = Category()
        stream = stream_category(category, None, {})
        await anext(stream)
        await stream.aclose()
        self.assertTrue(cancelled.is_set())
        self.assertIsNone(category._on_result)
