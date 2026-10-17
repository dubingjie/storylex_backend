from flask import Blueprint, request, g
from services.page_service import PageService
from services.word_service import WordService
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

def page_response(result):
    success, msg, data = result
    return success_response(data=data, msg=msg) if success else error_response(msg=msg, code=400)


@user_bp.route('/stats', methods=['GET'])
@login_required
def get_personal_stats():
    return page_response(PageService.stats(g.user_id))


@user_bp.route('/books', methods=['GET'])
@login_required
def get_books():
    return page_response(PageService.books(g.user_id))


@user_bp.route('/book', methods=['PUT'])
@login_required
def switch_book():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response(msg='请求体必须为 JSON 对象', code=400)
    return page_response(PageService.switch_book(g.user_id, data.get('book_id')))


@user_bp.route('/favorites', methods=['GET'])
@login_required
def get_favorites():
    try:
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 50))
    except (TypeError, ValueError):
        return error_response(msg='page、page_size 必须为整数', code=400)
    if page < 1 or not 1 <= page_size <= 200:
        return error_response(msg='page 必须大于0，page_size 必须为1到200', code=400)
    return page_response(WordService.get_favorite_words(g.user_id, page, page_size, request.args.get('keyword')))


@user_bp.route('/favorites/batch-delete', methods=['POST'])
@login_required
def batch_delete_favorites():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response(msg='请求体必须为 JSON 对象', code=400)
    return page_response(PageService.batch_delete_favorites(g.user_id, data.get('word_ids')))


@user_bp.route('/favorites/practice', methods=['POST'])
@login_required
def create_favorite_practice():
    from services.independent_practice_service import IndependentPracticeService
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response(msg='请求体必须为JSON对象', code=400)
    return page_response(IndependentPracticeService.create(
        g.user_id, 'favorites', data.get('word_ids'), data.get('request_id'), data.get('mode', 'mixed')))
