import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .db import init_db
from .routers import router
from . import scheduler

app = FastAPI(title="RAKSHAK-1 Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


@app.on_event("startup")
async def startup():
    init_db()
    asyncio.create_task(scheduler.loop())


@app.get("/")
def root():
    return {"service": "RAKSHAK-1 backend", "docs": "/docs"}
