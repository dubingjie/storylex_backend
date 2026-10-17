"""仅输出固定诊断信息，不回传供应商原始响应、请求头或密钥。"""
from openai import APIConnectionError, APIStatusError, APITimeoutError


def status_error(status):
    messages = {
        400: ('MODEL_BAD_REQUEST', '模型服务拒绝请求参数，请核对模型能力与请求配置'),
        401: ('MODEL_AUTH_FAILED', '模型服务鉴权失败（HTTP 401），请检查后端实际加载的API Key与服务地址是否匹配'),
        402: ('MODEL_QUOTA_EXHAUSTED', '模型服务额度不足（HTTP 402），请检查余额或密钥额度'),
        403: ('MODEL_ACCESS_DENIED', '模型服务拒绝访问（HTTP 403），请检查模型权限或服务访问限制'),
        404: ('MODEL_NOT_FOUND', '模型或接口不存在（HTTP 404），请核对模型ID与Base URL'),
        408: ('MODEL_TIMEOUT', '模型服务请求超时（HTTP 408），请稍后重试'),
        413: ('MODEL_REQUEST_TOO_LARGE', '模型服务拒绝过大的请求（HTTP 413），请减少目标词或主题长度'),
        429: ('MODEL_RATE_LIMITED', '模型服务限流（HTTP 429），免费模型或账号可能达到频率/每日限制，请稍后重试'),
    }
    code, message = messages.get(status, ('MODEL_SERVICE_ERROR', '模型服务异常，请稍后重试'))
    return {'error_code': code, 'http_status': status, 'error': message}


def model_error(exc):
    if isinstance(exc, APITimeoutError):
        return {'error_code': 'MODEL_TIMEOUT', 'http_status': None,
                'error': '模型调用超过等待时间，请稍后重试或使用响应更快的模型'}
    if isinstance(exc, APIConnectionError):
        return {'error_code': 'MODEL_CONNECTION_FAILED', 'http_status': None,
                'error': '后端无法连接模型服务，请检查服务器DNS、网络、代理或TLS证书'}
    if isinstance(exc, APIStatusError):
        return status_error(exc.status_code)
    return {'error_code': 'MODEL_CALL_FAILED', 'http_status': None,
            'error': '模型调用发生未分类异常，请检查后端模型调用依赖或响应格式'}
