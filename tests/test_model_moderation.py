import asyncio
import httpx
import pytest
from app import llm


def test_moderation_has_specific_exception_and_no_retry(monkeypatch):
    monkeypatch.setenv('LLM_API_KEY', 'test')
    calls = []
    class Client:
        def __init__(self, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def post(self, *args, **kwargs):
            calls.append(1)
            return httpx.Response(400, json={'code': -20058, 'message': 'sensitive vendor text'})
    monkeypatch.setattr(llm.httpx, 'AsyncClient', Client)
    with pytest.raises(llm.ModelContentReviewRequired, match='人工复核') as exc:
        asyncio.run(llm.complete([{'role':'user','content':'test'}]))
    assert 'sensitive vendor text' not in str(exc.value)
    assert len(calls) == 1
