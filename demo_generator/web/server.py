"""FastAPI application and uvicorn launcher."""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .run_manager import RunManager
from .routes_api import router as api_router
from .routes_ws import router as ws_router

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


def create_app(config, config_path):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        manager = RunManager(config, config_path)
        app.state.manager = manager
        yield
        await manager.cleanup()

    app = FastAPI(title="Firewall Demo Traffic Generator", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(api_router, prefix="/api")
    app.include_router(ws_router)

    @app.get("/")
    async def index():
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))

    return app


def run_web(config, config_path, host="0.0.0.0", port=8080):
    import uvicorn

    app = create_app(config, config_path)
    print(f"\n  Traffic Generator Web GUI: http://{host}:{port}\n")
    uvicorn.run(app, host=host, port=port, log_level="warning")
