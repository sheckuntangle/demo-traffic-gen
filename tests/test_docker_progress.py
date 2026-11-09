import asyncio
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from demo_generator.docker_clients import DockerClientPool


class DockerProgressTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.messages = []
        self.pool = DockerClientPool({"generator": {}, "docker": {"start_ip": "10.0.1.101", "client_count": 1}}, self.messages.append)
        self.pool._loop = asyncio.get_running_loop()

    async def test_sdk_work_does_not_block_loop_and_forwards_progress(self):
        started = threading.Event()
        release = threading.Event()

        def work():
            started.set()
            release.wait(2)
            self.pool._log("SDK progress")
            return 42

        task = asyncio.create_task(self.pool._docker_call("Test operation", work))
        try:
            while not started.is_set():
                await asyncio.sleep(0.001)
            self.assertFalse(task.done())
        finally:
            release.set()
        self.assertEqual(await task, 42)
        await asyncio.sleep(0)
        self.assertIn("SDK progress", self.messages)

    async def test_stop_waits_for_inflight_docker_call_before_cleanup(self):
        started = threading.Event()
        release = threading.Event()

        def work():
            started.set()
            release.wait(2)

        task = asyncio.create_task(self.pool._docker_call("Creating worker", work))
        try:
            while not started.is_set():
                await asyncio.sleep(0.001)
            task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(task.done())
        finally:
            release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_build_output_streams_before_completion_and_errors_surface(self):
        self.pool._docker = Mock()

        def chunks():
            yield {"stream": "Step 1: pulling image"}
            # Logging happens as each chunk is consumed, before the next one.
            self.assertTrue(log.called)
            yield {"error": "registry unavailable"}

        self.pool._docker.api.build.return_value = chunks()
        with patch.object(self.pool, "_log") as log:
            with self.assertRaisesRegex(RuntimeError, "registry unavailable"):
                self.pool.build_image()
            self.assertTrue(any("pulling image" in call.args[0] for call in log.call_args_list))

    async def test_health_timeout_has_diagnostics_and_real_deadline(self):
        client = SimpleNamespace(container_name="test-worker", container_id="id", macvlan_ip="10.0.1.101", base_url="http://172.18.0.2:8090", health_check=AsyncMock(return_value=False))
        container = Mock(attrs={"State": {"Status": "exited", "ExitCode": 1}})
        container.logs.return_value = b"Chromium launch failed"
        self.pool._docker = Mock()
        self.pool._docker.containers.get.return_value = container
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            await self.pool._wait_for_health(client, timeout=0.02)
        await asyncio.sleep(0)
        self.assertLess(time.monotonic() - started, 1)
        self.assertTrue(any("Chromium launch failed" in message for message in self.messages))
        self.assertTrue(any("ExitCode" in message for message in self.messages))

    async def test_partial_startup_fails_and_tracks_failed_containers_for_cleanup(self):
        with patch.object(self.pool, "_init_docker"), \
             patch.object(self.pool, "image_exists", return_value=True), \
             patch.object(self.pool, "_remove_stale_containers"), \
             patch.object(self.pool, "_start_container", new=AsyncMock(side_effect=RuntimeError("worker failed"))):
            self.pool._network_mgr = Mock()
            self.pool._network_mgr.create_networks.return_value = (Mock(), Mock())
            with self.assertRaisesRegex(RuntimeError, "startup incomplete"):
                await self.pool.start()
        container = Mock()
        self.pool._containers.append(container)
        await self.pool.cleanup()
        container.remove.assert_called_once_with(force=True)
        self.assertFalse(self.pool.is_started)
