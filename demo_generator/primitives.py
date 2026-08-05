"""Async test primitive functions — ping, DNS, web, SSH, TCP."""

import asyncio
import socket
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TestResult:
    test_type: str
    target: str
    success: bool
    message: str = ""
    status_code: Optional[int] = None
    duration_ms: float = 0.0
    client_name: str = ""
    category: str = ""

    def to_dict(self):
        return {
            "test_type": self.test_type,
            "target": self.target,
            "success": self.success,
            "message": self.message,
            "status_code": self.status_code,
            "duration_ms": self.duration_ms,
            "client_name": self.client_name,
            "category": self.category,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(**d)


def apply_expected(result, expected):
    if expected in ("block", "reject"):
        result.success = not result.success
    if expected:
        result.message = f"[expected: {expected}] {result.message}"


async def ping(ip, name="", source_ip=None, timeout=5):
    start = time.monotonic()
    cmd = ["ping", "-c", "1", "-W", "2"]
    if source_ip:
        cmd.extend(["-I", source_ip])
    cmd.append(ip)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=timeout)
        elapsed = (time.monotonic() - start) * 1000
        label = f"{name} ({ip})" if name else ip
        if proc.returncode == 0:
            return TestResult("PING", label, True, duration_ms=elapsed)
        return TestResult("PING", label, False, message="No response", duration_ms=elapsed)
    except asyncio.TimeoutError:
        elapsed = (time.monotonic() - start) * 1000
        label = f"{name} ({ip})" if name else ip
        return TestResult("PING", label, False, message="Timeout", duration_ms=elapsed)
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        label = f"{name} ({ip})" if name else ip
        return TestResult("PING", label, False, message=str(e)[:80], duration_ms=elapsed)


async def dns_query(domain):
    start = time.monotonic()
    try:
        loop = asyncio.get_event_loop()
        results = await asyncio.wait_for(
            loop.getaddrinfo(domain, None, family=socket.AF_INET),
            timeout=5,
        )
        elapsed = (time.monotonic() - start) * 1000
        if results:
            ip = results[0][4][0]
            return TestResult("DNS", domain, True, message=f"Resolved to {ip}", duration_ms=elapsed)
        return TestResult("DNS", domain, False, message="No results", duration_ms=elapsed)
    except asyncio.TimeoutError:
        elapsed = (time.monotonic() - start) * 1000
        return TestResult("DNS", domain, False, message="Timeout", duration_ms=elapsed)
    except socket.gaierror:
        elapsed = (time.monotonic() - start) * 1000
        return TestResult("DNS", domain, False, message="Resolution failed", duration_ms=elapsed)
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        return TestResult("DNS", domain, False, message=str(e)[:80], duration_ms=elapsed)


async def web_request(url, context, timeout=30):
    start = time.monotonic()
    page = None
    try:
        page = await context.new_page()
        response = await page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
        elapsed = (time.monotonic() - start) * 1000

        if response and response.status < 400:
            return TestResult("WEB", url, True, message=f"Status: {response.status}",
                              status_code=response.status, duration_ms=elapsed)
        status = response.status if response else None
        return TestResult("WEB", url, False, message=f"Status: {status}",
                          status_code=status, duration_ms=elapsed)
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        msg = "Timeout" if "Timeout" in type(e).__name__ else str(e)[:80]
        return TestResult("WEB", url, False, message=msg, duration_ms=elapsed)
    finally:
        if page:
            try:
                await page.close()
            except Exception:
                pass


async def http_to_ip(ip, description="", context=None, timeout=15):
    url = f"http://{ip}"
    label = f"{ip} ({description})" if description else ip
    start = time.monotonic()
    page = None

    if context is None:
        return await tcp_connect(ip, 80, timeout=timeout)

    try:
        page = await context.new_page()
        response = await page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
        elapsed = (time.monotonic() - start) * 1000

        if response and response.status < 400:
            return TestResult("HTTP", label, True, message=f"Status: {response.status}",
                              status_code=response.status, duration_ms=elapsed)
        status = response.status if response else None
        return TestResult("HTTP", label, False, message=f"Status: {status}",
                          status_code=status, duration_ms=elapsed)
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        msg = "Timeout" if "Timeout" in type(e).__name__ else str(e)[:80]
        return TestResult("HTTP", label, False, message=msg, duration_ms=elapsed)
    finally:
        if page:
            try:
                await page.close()
            except Exception:
                pass


async def ssh_connect(host, port=22, timeout=5):
    start = time.monotonic()
    label = f"{host}:{port}"

    def _attempt():
        import paramiko
        transport = paramiko.Transport((host, port))
        try:
            transport.connect()
        except paramiko.ssh_exception.SSHException:
            pass
        finally:
            try:
                transport.close()
            except Exception:
                pass

    try:
        await asyncio.wait_for(asyncio.to_thread(_attempt), timeout=timeout)
        elapsed = (time.monotonic() - start) * 1000
        return TestResult("SSH", label, True, message="SSH handshake completed", duration_ms=elapsed)
    except asyncio.TimeoutError:
        elapsed = (time.monotonic() - start) * 1000
        return TestResult("SSH", label, False, message="Timeout", duration_ms=elapsed)
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        return TestResult("SSH", label, False, message=str(e)[:80], duration_ms=elapsed)


async def tcp_connect(ip, port=80, timeout=5):
    start = time.monotonic()
    label = f"{ip}:{port}"
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port),
            timeout=timeout,
        )
        writer.close()
        await writer.wait_closed()
        elapsed = (time.monotonic() - start) * 1000
        return TestResult("TCP", label, True, message="Connection established", duration_ms=elapsed)
    except asyncio.TimeoutError:
        elapsed = (time.monotonic() - start) * 1000
        return TestResult("TCP", label, False, message="Timeout", duration_ms=elapsed)
    except ConnectionRefusedError:
        elapsed = (time.monotonic() - start) * 1000
        return TestResult("TCP", label, False, message="Connection refused", duration_ms=elapsed)
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        return TestResult("TCP", label, False, message=str(e)[:80], duration_ms=elapsed)
