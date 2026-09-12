import asyncio
import json

import httpx
import pytest

from app import llm


def setup_client(monkeypatch, response):
    monkeypatch.setenv('LLM_API_KEY', 'Bearer test-token')
    monkeypatch.setenv('LLM_MODEL', 'intern-latest')
    monkeypatch.setenv('LLM_CHAT_URL', llm.DEFAULT_URL)
    monkeypatch.setenv('LLM_THINKING_MODE', '')
    captured = []
    def handler(request):
        captured.append(request)
        return response
    original = httpx.AsyncClient
    monkeypatch.setattr(llm.httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    return captured


def test_request_and_multiturn(monkeypatch):
    captured = setup_client(monkeypatch, httpx.Response(200, json={'choices': [{'message': {'content': '答案'}, 'finish_reason': 'stop'}]}))
    messages = [{'role': 'user', 'content': '甲公司问题？'}, {'role': 'assistant', 'content': '研发管理'}, {'role': 'user', 'content': '怎么改？'}]
    assert asyncio.run(llm.complete(messages)) == '答案'
    assert captured[0].headers['Authorization'] == 'Bearer test-token'
    body = json.loads(captured[0].content)
    assert body['messages'] == messages
    assert body['stream'] is False
    assert 'thinking_mode' not in body
    monkeypatch.setenv('LLM_MODEL', 'intern-s2-preview-397b')
    monkeypatch.setenv('LLM_THINKING_MODE', 'false')
    asyncio.run(llm.complete(messages))
    assert json.loads(captured[1].content)['thinking_mode'] is False


@pytest.mark.parametrize('status,payload,expected', [
    (200, {'code': 'A0211', 'message': 'private-token'}, '已过期'),
    (200, {'error': {'code': -20053}}, '频率限制'),
    (401, {}, '鉴权'),
    (429, {}, '频率限制'),
    (200, {'choices': []}, '有效文本'),
    (200, {'choices': [{'message': {'content': 'partial'}, 'finish_reason': 'length'}]}, '截断'),
])
def test_errors(monkeypatch, status, payload, expected):
    setup_client(monkeypatch, httpx.Response(status, json=payload))
    with pytest.raises(llm.ModelError, match=expected) as err:
        asyncio.run(llm.complete([{'role': 'user', 'content': '问题'}]))
    assert 'private-token' not in str(err.value)
