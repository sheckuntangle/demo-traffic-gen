"""IDPS — intrusion detection/prevention signature testing via shell script."""

import asyncio
import os
import tempfile
import time

from . import TestCategory
from ..primitives import TestResult


DEFAULT_SCRIPT = r"""#!/bin/sh
sleep 2

# ==========================================
# ALERT TESTS (Using Reliable URI Triggers)
# ==========================================
echo "========================================"
echo " RUNNING ALERT TESTS"
echo "========================================"
echo ""

echo "Test A1: SID 2049400 - /etc/passwd Detected in URI"
curl -s "http://example.com/etc/passwd" > /dev/null 2>&1
echo "-> Request sent"
echo ""
sleep 2

echo "Test A2: SID 2033891 - Observed Suspicious Request nc.exe in URI"
curl -s "http://example.com/nc.exe" > /dev/null 2>&1
echo "-> Request sent"
echo ""
sleep 2

# ==========================================
# REJECT TESTS (Using Reliable SQLi Triggers)
# ==========================================
echo "========================================"
echo " RUNNING REJECT TESTS"
echo "========================================"
echo ""

echo "Test R1: SID 2007337 - UNION SELECT SQL Injection"
curl -s -m 5 "http://example.com/index.php?pageid=1%20UNION%20SELECT%20username,password" > /dev/null 2>&1
echo "-> Request sent"
echo ""
sleep 2

echo "Test R2: SID 2006124 - detail.asp UNION SELECT SQL Injection"
curl -s -m 5 "http://example.com/detail.asp?ID=1%20UNION%20SELECT%20username,password" > /dev/null 2>&1
echo "-> Request sent"
echo ""
sleep 2

echo "Test R3: SID 2005082 - faq.php UNION SELECT SQL Injection"
curl -s -m 5 "http://example.com/faq.php?id=1%20UNION%20SELECT%20username,password" > /dev/null 2>&1
echo "-> Request sent"
echo ""

echo "Testing complete."
"""


class IDPS(TestCategory):
    name = "idps"
    display_name = "IDPS"

    async def run(self, context, config, source_ip=None):
        cat_config = config["categories"].get("idps", {})
        script = cat_config.get("script", DEFAULT_SCRIPT)

        fd, script_path = tempfile.mkstemp(suffix=".sh")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(script)
            os.chmod(script_path, 0o755)

            start = time.monotonic()
            proc = await asyncio.create_subprocess_exec(
                "/bin/sh", script_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            results = await self._stream_output(proc, start)

            try:
                await asyncio.wait_for(proc.wait(), timeout=10)
            except asyncio.TimeoutError:
                proc.kill()

            if not results:
                elapsed = (time.monotonic() - start) * 1000
                results.append(TestResult(
                    test_type="IDPS", target="script", success=proc.returncode == 0,
                    message=f"Exit code {proc.returncode}", duration_ms=elapsed,
                    category=self.name,
                ))

            return results
        except asyncio.CancelledError:
            proc.kill()
            raise
        except Exception as e:
            return [TestResult(
                test_type="IDPS", target="script", success=False,
                message=f"{type(e).__name__}: {e}", category=self.name,
            )]
        finally:
            try:
                os.unlink(script_path)
            except OSError:
                pass

    async def _stream_output(self, proc, start):
        results = []
        current_test = None

        while True:
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=30)
            except asyncio.TimeoutError:
                r = TestResult(
                    test_type="IDPS", target=current_test or "script",
                    success=False, message="Timed out waiting for output",
                    duration_ms=(time.monotonic() - start) * 1000,
                    category=self.name,
                )
                self.emit_result(r)
                results.append(r)
                proc.kill()
                break

            if not line:
                break

            stripped = line.decode(errors="replace").strip()
            if not stripped:
                continue

            elapsed = (time.monotonic() - start) * 1000

            if stripped.startswith("Test "):
                current_test = stripped
                r = TestResult(
                    test_type="IDPS", target=stripped, success=True,
                    message="Running...", duration_ms=elapsed,
                    category=self.name,
                )
                self.emit_result(r)
                results.append(r)
            elif stripped.startswith("-> ") and current_test:
                r = TestResult(
                    test_type="IDPS", target=current_test, success=True,
                    message=stripped[3:], duration_ms=elapsed,
                    category=self.name,
                )
                self.emit_result(r)
                results.append(r)
                current_test = None
            elif stripped.startswith("RUNNING") or stripped == "Testing complete.":
                r = TestResult(
                    test_type="IDPS", target=stripped, success=True,
                    message="", duration_ms=elapsed,
                    category=self.name,
                )
                self.emit_result(r)
                results.append(r)

        return results
