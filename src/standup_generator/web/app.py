"""Local FastAPI app: one page plus a small JSON API."""

from __future__ import annotations

import dataclasses
from datetime import date, datetime
from importlib import resources

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..config import AppConfig
from ..generator import generate
from ..history import HistoryStore
from ..sources.base import Source
from ..window import compute_window, resolve_tz

ALLOWED_HOSTS = {"localhost", "127.0.0.1"}


class GenerateRequest(BaseModel):
    plans: str = ""
    blockers: str = ""
    since: date | None = None


class FinalRequest(BaseModel):
    final_standup: str


def create_app(config: AppConfig, sources: list[Source] | None = None) -> FastAPI:
    app = FastAPI(title="Standup generator", docs_url=None, redoc_url=None)
    static_dir = resources.files("standup_generator").joinpath("web/static")
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.middleware("http")
    async def host_guard(request: Request, call_next):
        # Blocks DNS-rebinding: only answer requests addressed to this machine.
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
        if host not in ALLOWED_HOSTS:
            return JSONResponse({"detail": "invalid host"}, status_code=400)
        return await call_next(request)

    def store() -> HistoryStore:
        if not config.history.enabled:
            raise HTTPException(404, "history disabled")
        return HistoryStore(config.history.db_path)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(str(static_dir.joinpath("index.html")))

    @app.get("/api/window")
    def window(since: date | None = None) -> dict:
        now = datetime.now(resolve_tz(config.timezone))
        w = compute_window(now, config.working_days, config.holidays, since)
        return {"start": w.start.isoformat(), "end": w.end.isoformat()}

    @app.post("/api/generate")
    def do_generate(req: GenerateRequest) -> dict:
        result = generate(config, plans=req.plans, blockers=req.blockers, since=req.since,
                          save=True, sources=sources)
        b = result.bundle
        return {
            "id": result.history_id,
            "prompt": result.prompt,
            "window": {"start": b.window.start.isoformat(), "end": b.window.end.isoformat()},
            "errors": b.source_errors,
            "info": b.source_info,
            "collected": _jsonable(dataclasses.asdict(b)),
        }

    @app.get("/api/history")
    def history(limit: int = 50) -> list[dict]:
        return [dataclasses.asdict(s) for s in store().list(limit)]

    @app.get("/api/history/{entry_id}")
    def history_entry(entry_id: int) -> dict:
        entry = store().get(entry_id)
        if entry is None:
            raise HTTPException(404, "not found")
        return dataclasses.asdict(entry)

    @app.patch("/api/history/{entry_id}")
    def save_final(entry_id: int, req: FinalRequest) -> dict:
        if not store().set_final(entry_id, req.final_standup):
            raise HTTPException(404, "not found")
        return {"ok": True}

    @app.delete("/api/history/{entry_id}", status_code=204)
    def delete_entry(entry_id: int) -> Response:
        if not store().delete(entry_id):
            raise HTTPException(404, "not found")
        return Response(status_code=204)

    return app


def _jsonable(value):
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value
