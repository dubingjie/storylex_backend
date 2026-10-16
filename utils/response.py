from flask import jsonify

def success_response(data=None, msg="success", code=200):
    """统一成功响应"""
    return jsonify({
        "code": code,
        "msg": msg,
        "data": data if data is not None else {}
    }), 200

def error_response(msg="error", code=400, http_status=200):
    """
    统一错误响应
    code: 业务状态码 (400 参数错误, 401 未登录/Token过期, 500 服务端异常)
    http_status: HTTP协议状态码，默认返回 200 交由前端读取业务 code
    """
    return jsonify({
        "code": code,
        "msg": msg,
        "data": {}
    }), http_status