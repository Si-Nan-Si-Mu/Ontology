from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import router as api_v1_router
from app.api.wechat import router as wechat_router
from app.config import get_settings
from app.db.neo4j import Neo4jConnection
from app.deps import Neo4jDep


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    neo4j = Neo4jConnection(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password,
        database=settings.neo4j_database,
    )
    neo4j.verify_connectivity()
    app.state.neo4j = neo4j
    yield
    neo4j.close()


app = FastAPI(title="POG API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_v1_router)
app.include_router(wechat_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/neo4j")
def health_neo4j(neo4j: Neo4jDep) -> dict[str, object]:
    rows = neo4j.execute_read(
        "RETURN 1 AS ok, datetime({timezone: 'Z'}) AS server_time"
    )
    row = rows[0] if rows else {}
    return {
        "ok": row.get("ok") == 1,
        "server_time": row.get("server_time"),
    }
