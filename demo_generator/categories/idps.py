"""IDPS — intrusion detection/prevention signature testing."""

import asyncio
import os
import random
import signal
import shlex
import tempfile
import time

from . import TestCategory
from ..primitives import TestResult, apply_expected


def diagnostic_curl_script(url, timeout=10):
    metrics = "HTTP status: %{http_code}; remote: %{remote_ip}:%{remote_port}; connect: %{time_connect}s; total: %{time_total}s\\n"
    return (f"curl --silent --show-error --max-time {timeout} --output /dev/null "
            f"--write-out {shlex.quote(metrics)} {shlex.quote(url)}")


# Upgrade only exact built-in scripts from older configs; custom scripts run unchanged.
LEGACY_SCRIPTS = {
    'curl -s "http://example.com/etc/passwd" > /dev/null': diagnostic_curl_script("http://example.com/etc/passwd"),
    'curl -s "http://example.com/nc.exe" > /dev/null': diagnostic_curl_script("http://example.com/nc.exe"),
    'curl -s "http://ip.jsontest.com/" > /dev/null': diagnostic_curl_script("http://ip.jsontest.com/"),
    **{f'curl -v -m 5 "{url}" 2>/dev/null': diagnostic_curl_script(url, 5) for url in (
        "http://example.com/index.php?pageid=1%20UNION%20SELECT%20username,password",
        "http://example.com/detail.asp?ID=1%20UNION%20SELECT%20username,password",
        "http://example.com/faq.php?id=1%20UNION%20SELECT%20username,password",
    )},
}


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
            script = LEGACY_SCRIPTS.get(script.strip(), script)

            target = f"SID {sid} - {description}" if sid else description

            fd, script_path = tempfile.mkstemp(suffix=".sh")
            proc = None
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
                    start_new_session=True,
                )
                timed_out = False
                try:
                    output, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
                except asyncio.TimeoutError:
                    timed_out = True
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    output, _ = await proc.communicate()

                elapsed = (time.monotonic() - start) * 1000
                success = proc.returncode == 0 and not timed_out
                if timed_out:
                    message = "Script exceeded the 15s limit and was stopped."
                elif success:
                    message = "Script reported success (exit code 0)."
                    if expected in ("block", "reject"):
                        message += f" Expected {expected}, but the script completed successfully."
                else:
                    message = f"Script failed (exit code {proc.returncode})."
                diagnostic = output.decode(errors="replace").strip()
                message += (f"\nOutput:\n{diagnostic[:4000]}" + ("\n[Output truncated]" if len(diagnostic) > 4000 else "")) if diagnostic else " No stdout/stderr was produced; the script may suppress output."
                message += "\nScript results alone do not confirm an IDPS match or alert; verify in firewall logs."

                r = TestResult(
                    test_type="IDPS", target=target, success=success,
                    message=message,
                    duration_ms=elapsed, category=self.name,
                )
                apply_expected(r, expected)
                if timed_out or proc.returncode in (126, 127):
                    r.success = False  # A stopped or unlaunchable script cannot validate policy.
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
                r.success = False  # Local execution errors must not pass expected-block checks.
                self.emit_result(r)
                results.append(r)
            finally:
                if proc is not None and proc.returncode is None:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    await proc.communicate()
                try:
                    os.unlink(script_path)
                except OSError:
                    pass

            await asyncio.sleep(random.uniform(1, 3))

        return results
