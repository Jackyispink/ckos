from app.llm import safe_service_error


def test_no_vendor_secret_echo():
    message = safe_service_error(500, {'error': {'code': 'secret-key', 'message': 'secret prompt'}})
    assert 'HTTP 500' in message and '网关' in message
    assert 'secret' not in message


def test_context_limit():
    assert '上下文限制' in safe_service_error(400, {'error': {'message': 'maximum context length exceeded'}})


def test_numeric_code_and_output_budget():
    message = safe_service_error(400, {'code': -12, 'message': 'max_tokens invalid'})
    assert '错误码-12' in message and '输出token' in message
