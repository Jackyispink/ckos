import sqlite3

import pytest

from app import database
from scripts.migrate_sqlite import migrate


def test_copy_preserves_ids_sources_and_sequence(tmp_path):
    source = tmp_path / 'old.sqlite3'
    with sqlite3.connect(source) as db:
        db.executescript('''
        CREATE TABLE documents(id TEXT, name TEXT, fingerprint TEXT, chunks INTEGER);
        CREATE TABLE chunks(id TEXT, document_id TEXT, location TEXT, text TEXT, tokens TEXT);
        CREATE TABLE sessions(id TEXT, title TEXT, created TEXT);
        CREATE TABLE messages(id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, sources TEXT);
        INSERT INTO documents VALUES ('d','报告','hash',1);
        INSERT INTO chunks VALUES ('c','d','表1','研发建议','["研发"]');
        INSERT INTO sessions VALUES ('s','问题','2026-09-03 08:00:00');
        INSERT INTO messages VALUES (42,'s','assistant','回答','[{"citation":1}]');
        ''')
    result = migrate(source)
    assert result['verified_counts'] == dict(documents=1, chunks=1, sessions=1, messages=1)
    with database.connect() as db:
        assert db.execute("INSERT INTO messages(session_id,role,content) VALUES ('s','user','追问') RETURNING id").fetchone()['id'] == 43
        assert db.execute('SELECT sources FROM messages WHERE id=42').fetchone()['sources'] == '[{"citation":1}]'
    with pytest.raises(ValueError, match='非空'):
        migrate(source)
    with database.connect() as db:
        assert db.execute('SELECT count(*) AS n FROM messages').fetchone()['n'] == 2
    assert source.exists()
