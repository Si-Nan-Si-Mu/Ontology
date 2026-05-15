from __future__ import annotations

from typing import Any

from neo4j import Driver, GraphDatabase, Session


class Neo4jConnection:
    """Neo4j 驱动封装：生命周期由 FastAPI lifespan 管理。"""

    def __init__(
        self,
        *,
        uri: str,
        user: str,
        password: str,
        database: str | None = None,
    ) -> None:
        self._database = database
        self._driver: Driver = GraphDatabase.driver(uri, auth=(user, password))

    @property
    def driver(self) -> Driver:
        return self._driver

    def verify_connectivity(self) -> None:
        self._driver.verify_connectivity()

    def close(self) -> None:
        self._driver.close()

    def session(self) -> Session:
        if self._database:
            return self._driver.session(database=self._database)
        return self._driver.session()

    def execute_read(
        self,
        cypher: str,
        parameters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        params = parameters or {}

        def work(tx: Any) -> list[dict[str, Any]]:
            result = tx.run(cypher, params)
            return [record.data() for record in result]

        with self.session() as session:
            return session.execute_read(work)

    def execute_write(
        self,
        cypher: str,
        parameters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        params = parameters or {}

        def work(tx: Any) -> list[dict[str, Any]]:
            result = tx.run(cypher, params)
            return [record.data() for record in result]

        with self.session() as session:
            return session.execute_write(work)
