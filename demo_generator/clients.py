"""Client profile pool — manages multiple Playwright browser contexts with different fingerprints."""

import random
from dataclasses import dataclass, field
from typing import Optional

ANTI_DETECTION_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    window.navigator.chrome = { runtime: {} };
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
"""

BROWSER_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-web-security",
    "--disable-features=IsolateOrigins,site-per-process",
]

EXTRA_HTTP_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

FALLBACK_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]

FALLBACK_VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 2560, "height": 1440},
    {"width": 1366, "height": 768},
    {"width": 1680, "height": 1050},
    {"width": 1536, "height": 864},
]

FALLBACK_TIMEZONES = [
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Phoenix",
    "America/Detroit",
]


@dataclass
class ClientProfile:
    name: str
    user_agent: str
    viewport: dict
    timezone: str
    locale: str
    source_ip: Optional[str] = None


@dataclass
class ClientContext:
    profile: ClientProfile
    browser_context: object = None

    async def run_category(self, category, config):
        return await category.run(self.browser_context, config, source_ip=self.profile.source_ip)


class ClientPool:
    def __init__(self, config):
        self._config = config
        self._browser = None
        self._clients = []
        self._playwright = None
        self._rounds_since_recycle = 0
        self._recycle_interval = config["generator"].get("browser_recycle_rounds", 10)

    def _build_profiles(self):
        profiles = []
        configured = self._config.get("client_profiles", [])
        client_count = self._config["generator"]["client_count"]

        for p in configured[:client_count]:
            profiles.append(ClientProfile(
                name=p["name"],
                user_agent=p["user_agent"],
                viewport=p["viewport"],
                timezone=p["timezone"],
                locale=p["locale"],
                source_ip=p.get("source_ip"),
            ))

        i = len(profiles)
        while len(profiles) < client_count:
            profiles.append(ClientProfile(
                name=f"client-{i + 1}",
                user_agent=random.choice(FALLBACK_USER_AGENTS),
                viewport=random.choice(FALLBACK_VIEWPORTS),
                timezone=random.choice(FALLBACK_TIMEZONES),
                locale="en-US",
            ))
            i += 1

        return profiles

    @property
    def is_started(self):
        return self._browser is not None

    async def start(self):
        if self.is_started:
            return
        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=BROWSER_LAUNCH_ARGS,
        )
        await self._create_contexts()

    async def _create_contexts(self):
        profiles = self._build_profiles()
        self._clients = []

        for profile in profiles:
            ctx = await self._browser.new_context(
                viewport=profile.viewport,
                user_agent=profile.user_agent,
                locale=profile.locale,
                timezone_id=profile.timezone,
                extra_http_headers=EXTRA_HTTP_HEADERS,
            )
            await ctx.add_init_script(ANTI_DETECTION_SCRIPT)
            self._clients.append(ClientContext(profile=profile, browser_context=ctx))

    async def recycle_if_needed(self):
        self._rounds_since_recycle += 1
        if self._rounds_since_recycle >= self._recycle_interval:
            self._rounds_since_recycle = 0
            await self._close_contexts()
            await self._create_contexts()

    async def _close_contexts(self):
        for client in self._clients:
            if client.browser_context:
                try:
                    await client.browser_context.close()
                except Exception:
                    pass

    def get_clients(self):
        return list(self._clients)

    async def cleanup(self):
        await self._close_contexts()
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
