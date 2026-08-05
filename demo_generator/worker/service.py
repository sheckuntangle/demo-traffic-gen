"""Worker service that runs inside each Docker container."""

import logging
import os
import socket
import traceback

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..clients import (
    ANTI_DETECTION_SCRIPT,
    BROWSER_LAUNCH_ARGS,
    EXTRA_HTTP_HEADERS,
)
from ..categories import get_all_categories
from ..primitives import TestResult

logger = logging.getLogger("demo_generator.worker")


def _get_container_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "unknown"


class WorkerState:
    def __init__(self):
        self.profile_name = os.environ.get("WORKER_PROFILE_NAME", "worker")
        self.user_agent = os.environ.get("WORKER_USER_AGENT", "")
        self.viewport_width = int(os.environ.get("WORKER_VIEWPORT_WIDTH", "1920"))
        self.viewport_height = int(os.environ.get("WORKER_VIEWPORT_HEIGHT", "1080"))
        self.timezone = os.environ.get("WORKER_TIMEZONE", "America/New_York")
        self.locale = os.environ.get("WORKER_LOCALE", "en-US")
        self.playwright = None
        self.browser = None
        self.browser_context = None

    async def start(self):
        from playwright.async_api import async_playwright
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=True,
            args=BROWSER_LAUNCH_ARGS,
        )
        await self._create_context()
        logger.info(f"Worker started: {self.profile_name} (viewport: {self.viewport_width}x{self.viewport_height})")

    async def _create_context(self):
        self.browser_context = await self.browser.new_context(
            viewport={"width": self.viewport_width, "height": self.viewport_height},
            user_agent=self.user_agent,
            locale=self.locale,
            timezone_id=self.timezone,
            extra_http_headers=EXTRA_HTTP_HEADERS,
        )
        await self.browser_context.add_init_script(ANTI_DETECTION_SCRIPT)

    async def recycle(self):
        if self.browser_context:
            try:
                await self.browser_context.close()
            except Exception:
                pass
        await self._create_context()
        logger.info("Browser context recycled")

    async def cleanup(self):
        if self.browser_context:
            try:
                await self.browser_context.close()
            except Exception:
                pass
        if self.browser:
            try:
                await self.browser.close()
            except Exception:
                pass
        if self.playwright:
            try:
                await self.playwright.stop()
            except Exception:
                pass


def create_app():
    state = WorkerState()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await state.start()
        app.state.worker = state
        yield
        await state.cleanup()

    app = FastAPI(title="Demo Generator Worker", lifespan=lifespan)

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "ip": _get_container_ip(),
            "profile": state.profile_name,
        }

    class RunRequest(BaseModel):
        category: str
        config: dict

    @app.post("/run")
    async def run_category(req: RunRequest):
        all_categories = get_all_categories()
        cat_cls = all_categories.get(req.category)
        if not cat_cls:
            return JSONResponse(status_code=400, content={"detail": f"Unknown category: {req.category}"})

        try:
            category = cat_cls()
            results = await category.run(state.browser_context, req.config)
            return [r.to_dict() for r in results]
        except Exception as e:
            logger.error(f"Category {req.category} failed: {e}")
            logger.error(traceback.format_exc())
            return JSONResponse(status_code=500, content={"detail": str(e)})

    @app.post("/recycle")
    async def recycle():
        await state.recycle()
        return {"status": "recycled"}

    return app


def main():
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    port = int(os.environ.get("WORKER_PORT", "8090"))
    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
