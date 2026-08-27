"""Signal CS API. Base path /api. No auth in MVP — the marketplace handles access."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, select

from typing import Optional

from auth import auth_enabled, current_user
from db import engine, get_session, init_db
from models import User
from engines import alerts as alert_engine
from engines import health as health_engine
from engines.attention import refresh_cached_scores
from routers import (
    columns,
    companies,
    board,
    contacts,
    deals,
    google,
    metrics,
    search,
    tasks,
)

APP_VERSION = os.getenv("APP_VERSION", "1.0.0")


def bootstrap() -> None:
    """Create tables, seed when empty, then run the health + alert jobs once."""
    init_db()
    from migrations import migrate
    from seed_demo import demo_seed_enabled, seed_if_empty

    with Session(engine) as session:
        # A deployed v1 database is persisted on the compose volume, so it will
        # be here when v2 boots. Migrate before anything queries it.
        migrate(session)

    init_db()  # pick up any table the migration dropped and the model still needs

    with Session(engine) as session:
        # A usable board needs an owner and columns even with no clients.
        from bootstrap import ensure_defaults

        ensure_defaults(session)

    with Session(engine) as session:
        # Production boots empty. The demo fixture is opt-in.
        seeded = seed_if_empty(session) if demo_seed_enabled() else False
        if not seeded:
            # Existing DB: keep derived state fresh across restarts.
            health_engine.recompute_all(session)
            alert_engine.evaluate(session)
            refresh_cached_scores(session)


@asynccontextmanager
async def lifespan(app: FastAPI):
    bootstrap()
    yield


app = FastAPI(title="Signal CS", version=APP_VERSION, lifespan=lifespan)

# The frontend container proxies /api on the same origin, so CORS matters only
# for local `npm run dev` against a separately-run backend.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

api = APIRouter(prefix="/api")


@api.get("/health")
def health_check():
    return {"status": "ok", "version": APP_VERSION}


@api.get("/me")
def me(user: Optional[User] = Depends(current_user)):
    """Who is asking. Null when sign-in is on and nobody is signed in.

    With AUTH_ENABLED off this answers with the single bootstrap CSM, which is
    what every demo and every existing deployment expects.
    """
    if user is None:
        return {"user": None, "auth_enabled": auth_enabled()}
    return {
        "auth_enabled": auth_enabled(),
        "user": {
            "id": user.id,
            "name": user.name,
            "initials": user.initials,
            "avatar_color": user.avatar_color,
            "email": user.email,
            "avatar_url": user.avatar_url,
        },
    }


@api.post("/jobs/recompute")
def recompute(session: Session = Depends(get_session)):
    """Dev helper: rerun health + alerts across the book."""
    count = health_engine.recompute_all(session)
    fired = alert_engine.evaluate(session)
    refresh_cached_scores(session)
    return {"accounts": count, "alerts": fired}


api.include_router(board.router)
api.include_router(columns.router)
api.include_router(companies.router)
api.include_router(deals.router)
api.include_router(tasks.router)
api.include_router(contacts.router)
api.include_router(search.router)
api.include_router(metrics.router)
api.include_router(google.router)

app.include_router(api)
