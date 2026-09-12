import uuid

import pytest
from psycopg import sql

from app import database, kb
from app.industry_research import database as industry_database, writer as industry_writer


@pytest.fixture(autouse=True)
def isolated_postgres(request, monkeypatch):
    if request.module.__name__.split('.')[-1] not in ('test_kb', 'test_migration', 'test_structured', 'test_uploads', 'test_management', 'test_duplicates', 'test_duplicate_index', 'test_upload_preview', 'test_industry_research', 'test_chart_download'):
        yield
        return
    original_connect = database.connect
    schema = 'test_ckos_' + uuid.uuid4().hex
    with original_connect() as db:
        db.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    def test_connect():
        db = original_connect()
        db.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
        return db
    monkeypatch.setattr(database, 'connect', test_connect)
    monkeypatch.setattr(kb, 'connect', test_connect)
    # These modules imported the function by value; patching only app.database
    # left industry tests writing into the user's public schema.
    monkeypatch.setattr(industry_database, 'connect', test_connect)
    monkeypatch.setattr(industry_writer, 'connect', test_connect)
    try:
        yield
    finally:
        with original_connect() as db:
            db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
