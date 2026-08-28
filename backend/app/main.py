from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import conversations, roles
from .db import init_db
from .config import BACKEND_DIR

FRONTEND_DIST = BACKEND_DIR.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="PersonaFlow", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(conversations.router)
    app.include_router(roles.router)
    app.mount(
        "/static/assets",
        StaticFiles(directory=BACKEND_DIR / "static" / "assets"),
        name="assets",
    )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    # Production/demo: FastAPI serves the Vite build from the same origin.
    # In backend-only development/tests frontend/dist may not exist, so this is optional.
    if FRONTEND_DIST.is_dir():
        frontend_assets = FRONTEND_DIST / "assets"
        if frontend_assets.is_dir():
            app.mount("/assets", StaticFiles(directory=frontend_assets), name="frontend-assets")

        @app.get("/", include_in_schema=False)
        def frontend_index():
            return FileResponse(FRONTEND_DIST / "index.html")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa_fallback(full_path: str):
            # Never turn an unknown API/static/health URL into an HTML 200 response.
            reserved = ("api/", "static/", "health")
            if full_path == "api" or full_path == "static" or full_path.startswith(reserved):
                raise HTTPException(status_code=404, detail="not found")
            requested = (FRONTEND_DIST / Path(full_path)).resolve()
            if requested.is_file() and FRONTEND_DIST.resolve() in requested.parents:
                return FileResponse(requested)
            return FileResponse(FRONTEND_DIST / "index.html")

    return app


app = create_app()
