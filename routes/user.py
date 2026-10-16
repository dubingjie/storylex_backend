from flask import Blueprint, g
from services.user_service import UserService
from utils.response import success_response, error_response
from utils.auth_helper import login_required

user_bp = Blueprint('user', __name__, url_prefix='/api/user')

@user_bp.route('/dashboard', methods=['GET'])
@login_required
def get_dashboard():
    """4.1 获取首页学习看板与进度"""
    success, msg, data = UserService.get_dashboard_stats(user_id=g.user_id)
    if not success:
        return error_response(msg=msg, code=400)
    return success_response(data=data, msg=msg)