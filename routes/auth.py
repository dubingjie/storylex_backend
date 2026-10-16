from flask import Blueprint, request, g
from services.auth_service import AuthService
from utils.response import success_response, error_response
from utils.auth_helper import login_required

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

@auth_bp.route('/register', methods=['POST'])
def register():
    """用户注册接口"""
    data = request.get_json() or {}
    username = data.get("username")
    password = data.get("password")

    success, msg, res_data = AuthService.register(username, password)
    if not success:
        return error_response(msg=msg, code=400)
    return success_response(data=res_data, msg=msg)

@auth_bp.route('/login', methods=['POST'])
def login():
    """用户登录接口"""
    data = request.get_json() or {}
    username = data.get("username")
    password = data.get("password")

    success, msg, res_data = AuthService.login(username, password)
    if not success:
        return error_response(msg=msg, code=400)
    return success_response(data=res_data, msg=msg)

@auth_bp.route('/me', methods=['GET'])
@login_required
def get_current_user():
    """测试接口：用于验证 @login_required 是否能正确解析 Token"""
    return success_response({
        "user_id": g.user_id,
        "username": g.username
    }, msg="Token 验证成功")