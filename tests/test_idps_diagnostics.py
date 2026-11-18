import asyncio
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from demo_generator.categories.idps import IDPS, LEGACY_SCRIPTS


class IDPSDiagnosticTests(unittest.IsolatedAsyncioTestCase):
    async def run_script(self, code=0, output=b"", expected="block", script="custom probe", timed_out=False):
        process = SimpleNamespace(pid=12345, returncode=code,
            communicate=AsyncMock(side_effect=[asyncio.TimeoutError(), (output, None)]) if timed_out
            else AsyncMock(return_value=(output, None)))
        scripts = []
        async def launch(*args, **kwargs):
            scripts.append(Path(args[1]).read_text())
            return process
        category = IDPS()
        emitted = []
        category._on_result = emitted.append
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=launch)), \
             patch("demo_generator.categories.idps.os.killpg"), \
             patch("demo_generator.categories.idps.random.uniform", return_value=0):
            results = await category.run(None, {"categories": {"idps": {"signatures": [
                {"sid": "123", "description": "Test signature", "expected": expected, "script": script}
            ]}}})
        self.assertEqual(results, emitted)
        return results[0], scripts[0]

    async def test_successful_command_reports_http_response_and_policy_mismatch(self):
        result, _ = await self.run_script(output=b"HTTP status: 200; remote: 192.0.2.1:80; total: 0.5s\n")
        self.assertFalse(result.success)
        for detail in ("HTTP status: 200", "192.0.2.1:80", "Expected block", "verify in firewall logs"):
            self.assertIn(detail, result.message)
        self.assertIn("SID 123", result.target)

    async def test_connection_errors_are_preserved(self):
        result, _ = await self.run_script(code=7, output=b"curl: (7) Failed to connect to example.com port 80\nHTTP status: 000\n")
        self.assertTrue(result.success)  # Existing expected-block inference; message explains the evidence.
        self.assertIn("Failed to connect", result.message)
        self.assertIn("HTTP status: 000", result.message)

    async def test_silent_custom_script_is_explained_and_unchanged(self):
        result, executed = await self.run_script(script="my-command > /dev/null", expected="alert")
        self.assertIn("No stdout/stderr", result.message)
        self.assertIn("Script reported success", result.message)
        self.assertIn("my-command > /dev/null", executed)

    async def test_legacy_defaults_are_upgraded_to_report_diagnostics(self):
        for legacy, replacement in LEGACY_SCRIPTS.items():
            with self.subTest(script=legacy):
                _, executed = await self.run_script(script=legacy)
                self.assertIn(replacement, executed)
                self.assertIn("--write-out", executed)
                self.assertIn("--show-error", executed)

    async def test_missing_command_and_execution_timeout_never_pass_expected_block(self):
        missing, _ = await self.run_script(code=127, output=b"custom probe: not found")
        self.assertFalse(missing.success)
        self.assertIn("not found", missing.message)
        timeout, _ = await self.run_script(code=-9, output=b"Partial output", timed_out=True)
        self.assertFalse(timeout.success)
        self.assertIn("15s limit", timeout.message)
        self.assertIn("Partial output", timeout.message)
