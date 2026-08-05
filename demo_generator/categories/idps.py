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

echo "Test A3: SID 2029923 - IP Check (ip.jsontest.com)"
curl -s "http://ip.jsontest.com/" > /dev/null 2>&1
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
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
            elapsed = (time.monotonic() - start) * 1000
            output = stdout.decode(errors="replace")

            return self._parse_results(output, elapsed, proc.returncode)
        except asyncio.TimeoutError:
            elapsed = (time.monotonic() - start) * 1000
            return [TestResult(
                test_type="IDPS", target="script", success=False,
                message="Script timed out", duration_ms=elapsed, category=self.name,
            )]
        except Exception as e:
            return [TestResult(
                test_type="IDPS", target="script", success=False,
                message=str(e)[:80], category=self.name,
            )]
        finally:
            try:
                os.unlink(script_path)
            except OSError:
                pass

    def _parse_results(self, output, total_elapsed, returncode):
        results = []
        current_test = None

        for line in output.splitlines():
            stripped = line.strip()
            if stripped.startswith("Test "):
                current_test = stripped
            elif stripped.startswith("-> ") and current_test:
                results.append(TestResult(
                    test_type="IDPS",
                    target=current_test,
                    success=True,
                    message=stripped[3:],
                    duration_ms=total_elapsed / max(1, len(results) + 1),
                    category=self.name,
                ))
                current_test = None

        if not results:
            results.append(TestResult(
                test_type="IDPS",
                target="script",
                success=returncode == 0,
                message=f"Exit code {returncode}" + (f" | {output[:100]}" if output else ""),
                duration_ms=total_elapsed,
                category=self.name,
            ))

        return results
