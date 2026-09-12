import os
import re

import httpx
from dotenv import load_dotenv

from .kb import ROOT

load_dotenv(ROOT / '.env')

DEFAULT_URL = 'https://chat.intern-ai.org.cn/api/v1/chat/completions'
THINKING_MODELS = {'intern-s2-preview-397b', 'intern-s2-preview-35b', 'intern-s2-preview', 'intern-s1-pro', 'intern-s1', 'intern-s1-mini'}
ERRORS = {
    '-10002': '请求参数错误，请检查问题和模型配置。',
    '-20004': '账号尚未获得 API 调用权限，请在书生平台申请。',
    '-20013': '模型不存在，请检查 LLM_MODEL。',
    '-20018': '对话消息格式错误。',
    '-20035': '账号尚未绑定手机号，请在书生平台绑定。',
    '-20053': '已超过 API 调用频率限制，请稍后重试。',
    'A0202': 'API 鉴权失败，请检查 LLM_API_KEY。',
    'A0211': 'API token 已过期，请更新 LLM_API_KEY 并重启服务。',
    'C1114': 'token 不属于书生 ChatAPI 服务，请更换 token。',
}


class ModelError(Exception):
    """Only locally defined, credential-free messages may be exposed to users."""


class ModelContentReviewRequired(ModelError):
    """Provider moderation rejection: do not automatically retry or rewrite input."""


def safe_service_error(status, data):
    error = data.get('error')
    nested = error if isinstance(error, dict) else {}
    message = str(nested.get('message') or data.get('message') or '').lower()
    # Classify locally; never return vendor text, which may echo prompts or keys.
    if any(s in message for s in ('context length', 'context_length', 'maximum context', 'too many tokens')):
        advice = '输入与输出总长度超过模型上下文限制，请降低每章资料或输出预算。'
    elif any(s in message for s in ('max_tokens', 'max_completion_tokens')):
        advice = '模型不接受当前输出token参数或预算，请核对该模型的输出上限。'
    elif status == 413:
        advice = '请求体超过服务限制，请减少每章输入资料。'
    elif status == 402 or any(s in message for s in ('insufficient_quota', 'insufficient balance')):
        advice = '账户额度或余额不足，请检查模型服务账户。'
    elif status >= 500:
        advice = '模型服务或网关异常，请稍后继续；未自动重试。'
    elif status == 400 or status == 422:
        advice = '模型请求参数被拒绝，请核对模型名称、上下文及输出上限。'
    else:
        advice = '模型服务拒绝请求，请检查服务端调用记录。'
    code = nested.get('code', data.get('code', data.get('error_code')))
    # Only numeric vendor codes are exposed; arbitrary string codes can contain secrets.
    code_text = f'，错误码{code}' if re.fullmatch(r'-?\d{1,10}', str(code)) else ''
    return f'模型服务错误（HTTP {status}{code_text}）：{advice}已完成章节保留。'


def setting(name, default):
    return os.getenv(name, '').strip() or default


def configured():
    return bool(os.getenv('LLM_API_KEY', '').strip())


async def complete(messages, *, output_tokens=None):
    token = os.getenv('LLM_API_KEY', '').strip()
    if token.lower().startswith('bearer '):
        token = token[7:].strip()
    if not token:
        raise ModelError('请先在 .env 中配置 LLM_API_KEY。')
    model = setting('LLM_MODEL', 'intern-s1-mini')
    try:
        timeout = float(setting('LLM_TIMEOUT', '150'))
        max_tokens = int(setting('LLM_MAX_TOKENS', '3000'))
        if timeout <= 0 or max_tokens < 0:
            raise ValueError()
    except ValueError:
        raise ModelError('LLM_TIMEOUT 必须大于零，LLM_MAX_TOKENS 必须是非负整数。') from None
    payload = {'model': model, 'messages': messages, 'temperature': 0.2, 'stream': False, 'max_tokens': max_tokens}
    if output_tokens is not None:
        if not isinstance(output_tokens, int) or not 1 <= output_tokens <= 12000:
            raise ModelError('单次输出预算必须为1—12000 tokens。')
        payload['max_tokens'] = output_tokens
    thinking = os.getenv('LLM_THINKING_MODE', '').strip().lower()
    if thinking and model in THINKING_MODELS:
        if thinking not in ('true', 'false'):
            raise ModelError('LLM_THINKING_MODE 只能填写 true、false 或留空。')
        payload['thinking_mode'] = thinking == 'true'
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(setting('LLM_CHAT_URL', DEFAULT_URL), headers={'Authorization': 'Bearer ' + token}, json=payload)
    except httpx.TimeoutException:
        raise ModelError('模型服务未在等待时间内返回，本轮未保存，请重试。持续超时时请检查模型负载与思考模式；调大客户端超时不能延长服务端限制。') from None
    except httpx.RequestError:
        raise ModelError('无法连接模型服务，请检查网络和 LLM_CHAT_URL。') from None
    try:
        data = response.json()
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    error = data.get('error')
    codes = [data.get('code'), data.get('error_code')]
    if isinstance(error, dict):
        codes.extend([error.get('code'), error.get('error_code')])
    elif isinstance(error, (str, int)):
        codes.append(error)
    for code in codes:
        if str(code) == '-20058':
            raise ModelContentReviewRequired(
                '模型厂商内容审核拦截（-20058），需要人工复核本章资料或向厂商申请误判复核。'
                '未自动改写资料、重试或切换模型；已完成章节保留。'
                '请先完成资料人工核验及厂商复核，再继续生成。')
        if str(code) in ERRORS:
            raise ModelError(ERRORS[str(code)])
    if response.status_code == 429:
        raise ModelError(ERRORS['-20053'])
    if response.status_code in (401, 403):
        raise ModelError('API 鉴权或权限检查失败，请检查 token 和账号调用权限。')
    if response.is_error or error or data.get('object') == 'error':
        raise ModelError(safe_service_error(response.status_code, data))
    try:
        choice = data['choices'][0]
        text = choice['message']['content']
        if not isinstance(text, str) or not text.strip():
            raise ValueError()
    except (KeyError, IndexError, TypeError, ValueError):
        raise ModelError('模型未返回有效文本，请稍后重试。') from None
    if choice.get('finish_reason') == 'length':
        raise ModelError('模型输出被截断，本轮未保存。请缩小问题范围或增加 LLM_MAX_TOKENS 后重试。')
    return text
