#!/usr/bin/env python3
"""
清空 Neo4j 当前库中全部节点与关系（MATCH (n) DETACH DELETE n）。

用法（在 backend 目录下，以便读取 .env）：

  cd backend
  python scripts/neo4j_wipe.py --dry-run          # 仅统计节点数
  python scripts/neo4j_wipe.py --yes              # 执行清空

亦可在 Neo4j Browser / cypher-shell 中手动执行：

  MATCH (n) DETACH DELETE n
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from neo4j import GraphDatabase

from app.config import get_settings


def _open_session(driver, database: str | None):
    if database:
        return driver.session(database=database)
    return driver.session()


def _count_nodes(session) -> int:
    def work(tx):
        rec = tx.run("MATCH (n) RETURN count(n) AS c").single()
        return int(rec["c"]) if rec else 0

    return session.execute_read(work)


def main() -> None:
    parser = argparse.ArgumentParser(description="清空 Neo4j 图库（需显式 --yes）")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="确认删除全部节点与关系，否则不执行写操作",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅查询节点总数，不写库",
    )
    args = parser.parse_args()

    s = get_settings()
    driver = GraphDatabase.driver(
        s.neo4j_uri,
        auth=(s.neo4j_user, s.neo4j_password),
    )
    db = s.neo4j_database

    try:
        driver.verify_connectivity()
    except Exception as e:
        print(f"连接 Neo4j 失败: {e}", file=sys.stderr)
        sys.exit(1)

    with _open_session(driver, db) as session:
        n = _count_nodes(session)
        if args.dry_run:
            print(f"[dry-run] 当前库约 {n} 个节点（含所有标签）。未执行删除。")
            driver.close()
            return

        if not args.yes:
            print(
                "未指定 --yes，拒绝执行。先加 --dry-run 查看数量，再加 --yes 清空。",
                file=sys.stderr,
            )
            sys.exit(2)

        print(f"即将删除约 {n} 个节点及其关系…")

        def wipe(tx):
            tx.run("MATCH (n) DETACH DELETE n")

        session.execute_write(wipe)

        n_after = _count_nodes(session)
        print(f"完成。剩余节点数: {n_after}")

    driver.close()


if __name__ == "__main__":
    main()
