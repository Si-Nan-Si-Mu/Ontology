from typing import Annotated

from fastapi import Depends, Request

from app.db.neo4j import Neo4jConnection


def get_neo4j(request: Request) -> Neo4jConnection:
    neo4j: Neo4jConnection | None = getattr(request.app.state, "neo4j", None)
    if neo4j is None:
        raise RuntimeError("Neo4j 未初始化：请确认应用 lifespan 已挂载驱动。")
    return neo4j


Neo4jDep = Annotated[Neo4jConnection, Depends(get_neo4j)]
