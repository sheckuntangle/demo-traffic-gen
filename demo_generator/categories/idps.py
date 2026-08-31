"""IDPS — intrusion detection/prevention signature testing."""

import asyncio
import os
import random
import tempfile
import time

from . import TestCategory
from ..primitives import TestResult, apply_expected


class IDPS(TestCategory):
    name = "idps"
    display_name = "IDPS"

    async def run(self, context, config, source_ip=None):
        cat_config = config["categories"].get("idps", {})
        signatures = cat_config.get("signatures", [])
        results = []

        for sig in signatures:
            sid = sig.get("sid", "")
            description = sig.get("description", "")
            expected = sig.get("expected", "")
            script = sig.get("script", "")
            if not script:
                continue

            target = f"SID {sid} - {description}" if sid else description

            fd, script_path = tempfile.mkstemp(suffix=".sh")
            try:
                with os.fdopen(fd, "w") as f:
                    f.write("#!/bin/sh\n")
                    f.write(script)
                    f.write("\n")
                os.chmod(script_path, 0o755)

                start = time.monotonic()
                proc = await asyncio.create_subprocess_exec(
                    "/bin/sh", script_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                try:
                    await asyncio.wait_for(proc.wait(), timeout=15)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()

                elapsed = (time.monotonic() - start) * 1000
                success = proc.returncode == 0

                r = TestResult(
                    test_type="IDPS", target=target, success=success,
                    message=f"exit code {proc.returncode}",
                    duration_ms=elapsed, category=self.name,
                )
                apply_expected(r, expected)
                self.emit_result(r)
                results.append(r)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                r = TestResult(
                    test_type="IDPS", target=target, success=False,
                    message=f"{type(e).__name__}: {e}", category=self.name,
                )
                apply_expected(r, expected)
                self.emit_result(r)
                results.append(r)
            finally:
                try:
                    os.unlink(script_path)
                except OSError:
                    pass

            await asyncio.sleep(random.uniform(1, 3))

        return results
