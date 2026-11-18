from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from demo_generator.primitives import apply_expected, ping


class PingDiagnosticTests(unittest.IsolatedAsyncioTestCase):
    async def result(self, code, stdout=b"", stderr=b""):
        proc = SimpleNamespace(returncode=code, communicate=AsyncMock(return_value=(stdout, stderr)))
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
            return await ping("192.0.2.1")

    async def test_reply_explains_failed_expected_block_check(self):
        result = await self.result(0, b"PING 192.0.2.1 (192.0.2.1)\n64 bytes from 192.0.2.1: icmp_seq=1 ttl=64 time=1.2 ms\n")
        self.assertTrue(result.success)
        apply_expected(result, "block")
        self.assertFalse(result.success)
        self.assertIn("[expected: block]", result.message)
        self.assertIn("echo reply received", result.message)
        self.assertIn("time=1.2 ms", result.message)

    async def test_no_response_preserves_packet_loss_diagnostics(self):
        result = await self.result(1, b"PING 192.0.2.1 (192.0.2.1)\n--- 192.0.2.1 ping statistics ---\n1 packets transmitted, 0 received, 100% packet loss\n")
        self.assertFalse(result.success)
        self.assertIn("No ICMP echo reply", result.message)
        self.assertIn("100% packet loss", result.message)

    async def test_unreachable_and_permission_errors_preserve_real_reason(self):
        unreachable = await self.result(1, b"From 192.0.2.254 icmp_seq=1 Destination Host Unreachable\n")
        self.assertIn("Destination Host Unreachable", unreachable.message)
        denied = await self.result(2, stderr=b"ping: socket: Operation not permitted\n")
        self.assertIn("Ping command failed", denied.message)
        self.assertIn("Operation not permitted", denied.message)

    async def test_missing_ping_command_is_explained(self):
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=FileNotFoundError("ping not installed"))):
            result = await ping("192.0.2.1")
        self.assertFalse(result.success)
        self.assertIn("Ping could not run", result.message)
        self.assertIn("ping not installed", result.message)
