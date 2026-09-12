"""Copy a SQLite snapshot to an EMPTY PostgreSQL target, atomically."""
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from psycopg import sql

from app import database

TABLES = {
    'documents': ('id', 'name', 'fingerprint', 'chunks'),
    'chunks': ('id', 'document_id', 'location', 'text', 'tokens'),
    'sessions': ('id', 'title', 'created'),
    'messages': ('id', 'session_id', 'role', 'content', 'sources'),
}


def digest(rows, columns):
    normalized = []
    for row in rows:
        values = [str(row[c]) if c == 'created' else row[c] for c in columns]
        normalized.append(json.dumps(values, ensure_ascii=False))
    return hashlib.sha256('\n'.join(sorted(normalized)).encode()).hexdigest()


def migrate(source: Path):
    if not source.is_file():
        raise ValueError('SQLite 源文件不存在')
    backup = source.with_name(f'knowledge-before-postgres-{datetime.now():%Y%m%d-%H%M%S-%f}.sqlite3')
    # SQLite backup API creates a consistent snapshot, including committed WAL data.
    with sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True) as original:
        snapshot = sqlite3.connect(backup)
        try:
            original.backup(snapshot)
        finally:
            snapshot.close()
    snapshot = sqlite3.connect(backup)
    snapshot.row_factory = sqlite3.Row
    try:
        rows = {t: list(snapshot.execute(f'SELECT * FROM {t}')) for t in TABLES}
    finally:
        snapshot.close()
    database.init()
    with database.connect() as db:
        db.execute('LOCK TABLE documents,chunks,sessions,messages IN ACCESS EXCLUSIVE MODE')
        for table in TABLES:
            count = db.execute(sql.SQL('SELECT count(*) AS n FROM {}').format(sql.Identifier(table))).fetchone()['n']
            if count:
                raise ValueError('目标表非空，已中止迁移；不会覆盖现有 PostgreSQL 数据。')
        for table, columns in TABLES.items():
            statement = sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(
                sql.Identifier(table), sql.SQL(',').join(map(sql.Identifier, columns)),
                sql.SQL(',').join(sql.Placeholder() for _ in columns))
            with db.cursor() as cursor:
                cursor.executemany(statement, [tuple(r[c] for c in columns) for r in rows[table]])
            copied = list(db.execute(sql.SQL('SELECT * FROM {}').format(sql.Identifier(table))))
            if digest(copied, columns) != digest(rows[table], columns):
                raise ValueError(f'{table} 内容校验不一致，事务已回滚')
        # Identity must continue after the copied SQLite message IDs.
        next_id = max((r['id'] for r in rows['messages']), default=0) + 1
        db.execute(sql.SQL('ALTER TABLE messages ALTER COLUMN id RESTART WITH {}').format(sql.Literal(next_id)))
    return {'backup': str(backup), 'verified_counts': {t: len(r) for t, r in rows.items()}}


if __name__ == '__main__':
    print(json.dumps(migrate(database.ROOT / 'storage' / 'knowledge.sqlite3'), ensure_ascii=False, indent=2))
