import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from demo_generator.categories.idps import IDPS
from demo_generator.primitives import ping


class SubprocessCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_ping_and_idps_clean_up_subprocesses(self):
        for category in ("ping", "idps"):
            with self.subTest(category=category):
                entered = asyncio.Event()
                calls = 0
                async def communicate():
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        entered.set()
                        await asyncio.Event().wait()
                    proc.returncode = -9
                    return b"", b""
                proc = SimpleNamespace(pid=12345, returncode=None, communicate=AsyncMock(side_effect=communicate), kill=Mock())
                with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)), \
                     patch("demo_generator.categories.idps.os.killpg") as kill_group:
                    if category == "ping":
                        work = ping("192.0.2.1")
                    else:
                        work = IDPS().run(None, {"categories": {"idps": {"signatures": [{"script": "sleep 10"}]}}})
                    task = asyncio.create_task(work)
                    await asyncio.wait_for(entered.wait(), 1)
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                    self.assertEqual(calls, 2)
                    if category == "ping":
                        proc.kill.assert_called_once()
                    else:
                        kill_group.assert_called_once()
