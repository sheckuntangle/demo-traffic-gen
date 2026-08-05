"""FastAPI application and uvicorn launcher."""

import logging
import os
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .run_manager import RunManager
from .routes_api import router as api_router, docker_router
from .routes_ws import router as ws_router

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

logger = logging.getLogger("demo_generator.web")


def create_app(config, config_path):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("Starting web server...")
        manager = RunManager(config, config_path)
        app.state.manager = manager
        logger.info(f"Config loaded from {config_path}")
        yield
        logger.info("Shutting down...")
        await manager.cleanup()

    app = FastAPI(title="Firewall Demo Traffic Generator", lifespan=lifespan)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.error(f"{request.method} {request.url.path} -> {type(exc).__name__}: {exc}")
        logger.error(traceback.format_exc())
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(api_router, prefix="/api")
    app.include_router(docker_router, prefix="/api")
    app.include_router(ws_router)

    @app.get("/")
    async def index():
        index_path = os.path.join(STATIC_DIR, "index.html")
        return FileResponse(index_path, headers={"Cache-Control": "no-cache"})

    return app


def run_web(config, config_path, host="0.0.0.0", port=8080):
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    app = create_app(config, config_path)
    print(f"\n  Traffic Generator Web GUI: http://{host}:{port}")
    print(f"  Serving static files from: {os.path.abspath(STATIC_DIR)}")
    print(f"  Config file: {os.path.abspath(config_path)}\n")
    uvicorn.run(app, host=host, port=port, log_level="info")
