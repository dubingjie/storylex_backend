from flask import Blueprint, request, g
from services.word_service import WordService
from utils.response import success_response, error_response
from utils.auth_helper import login_required

words_bp = Blueprint('words', __name__, url_prefix='/api/words')

@words_bp.route('/learn/group', methods=['GET'])
@login_required
def get_learn_group():
    """1.3 拉取新学10词组题目"""
    success, msg, data = WordService.get_learn_group(user_id=g.user_id)
    if not success:
        return error_response(msg=msg, code=400)
    return success_response(data=data, msg=msg)

def answer_request(kind):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response(msg="请求体必须为 JSON 对象", code=400)
    method = WordService.check_learn_answer if kind == 'learn' else WordService.answer_review_word
    success, msg, result = method(
        user_id=g.user_id, group_id=data.get('group_id'),
        word_id=data.get('word_id'), question_id=data.get('question_id'),
        request_id=data.get('request_id'), selected_key=data.get('selected_key'),
        is_show_answer=data.get('is_show_answer', False))
    return success_response(data=result, msg=msg) if success else error_response(msg=msg, code=400)


@words_bp.route('/learn/answer', methods=['POST'])
@login_required
def check_learn_answer():
    return answer_request('learn')


@words_bp.route('/learn/group/complete', methods=['POST'])
@login_required
def complete_learn_group():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response(msg="请求体必须为 JSON 对象", code=400)
    success, msg, result = WordService.complete_learn_group(g.user_id, data.get('group_id'))
    return success_response(data=result, msg=msg) if success else error_response(msg=msg, code=400)


@words_bp.route('/review/queue', methods=['GET'])
@words_bp.route('/review/group', methods=['GET'])
@login_required
def get_review_group():
    success, msg, data = WordService.get_review_group(user_id=g.user_id)
    return success_response(data=data, msg=msg) if success else error_response(msg=msg, code=400)


@words_bp.route('/review/answer', methods=['POST'])
@login_required
def answer_review_word():
    return answer_request('review')


@words_bp.route('/review/complete', methods=['POST'])
@login_required
def complete_review_group():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response(msg="请求体必须为 JSON 对象", code=400)
    success, msg, result = WordService.complete_review_group(g.user_id, data.get('group_id'))
    return success_response(data=result, msg=msg) if success else error_response(msg=msg, code=400)


@words_bp.route('/master', methods=['POST'])
@login_required
def master_word():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response(msg="请求体必须为 JSON 对象", code=400)
    success, msg, result = WordService.master_word(g.user_id, data.get('word_id'), data.get('group_id'))
    return success_response(data=result, msg=msg) if success else error_response(msg=msg, code=400)


@words_bp.route('/favorite/toggle', methods=['POST'])
@login_required
def toggle_favorite():
    """3.1 切换单词收藏状态"""
    req_data = request.get_json(silent=True)
    if not isinstance(req_data, dict):
        return error_response(msg="请求体必须为JSON对象", code=400)
    word_id = req_data.get("word_id")
    source_type = req_data.get("source_type", "flashcard")

    if not word_id:
        return error_response(msg="word_id 不能为空", code=400)

    success, msg, data = WordService.toggle_favorite(
        user_id=g.user_id,
        word_id=word_id,
        source_type=source_type
    )
    if not success:
        return error_response(msg=msg, code=400)
    return success_response(data=data, msg=msg)

@words_bp.route('/favorite/list', methods=['GET'])
@login_required
def get_favorite_words():
    """3.2 分页获取我的生词本"""
    page = request.args.get("page", 1, type=int)
    page_size = request.args.get("page_size", 15, type=int)
    keyword = request.args.get("keyword", None)

    success, msg, data = WordService.get_favorite_words(
        user_id=g.user_id,
        page=page,
        page_size=page_size,
        keyword=keyword
    )
    if not success:
        return error_response(msg=msg, code=400)
    return success_response(data=data, msg=msg)




@words_bp.route('/target/update', methods=['PUT'])
@login_required
def update_daily_target():
    """1.2 修改每日学习目标"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response(msg="请求体必须为JSON对象", code=400)
    task_type = data.get("task_type")
    target_count = data.get("target_count")

    if not task_type or target_count is None:
        return error_response(msg="缺少必填参数 task_type 或 target_count", code=400)

    success, msg = WordService.update_daily_target(
        user_id=g.user_id,
        task_type=task_type,
        target_count=target_count
    )
    if not success:
        return error_response(msg=msg, code=400)
    return success_response(data=None, msg=msg)


@words_bp.route('/learn/group/practice', methods=['POST'])
@login_required
def get_group_practice_questions():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response(msg='请求体必须为JSON对象', code=400)
    success, msg, result = WordService.get_group_practice_questions(
        g.user_id, data.get('word_ids'), data.get('request_id'), data.get('mode', 'mixed'), data.get('group_id'))
    return success_response(data=result, msg=msg) if success else error_response(msg=msg, code=400)


@words_bp.route('/book/list', methods=['GET'])
@login_required
def get_book_words_list():
    """2.5 获取词书总词表列表"""
    book_id = request.args.get('book_id')
    filter_type = request.args.get('filter', 'all')  # all, learned, unlearned
    try:
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 20))
    except (TypeError, ValueError):
        return error_response(msg='page、page_size必须为整数', code=400)

    success, msg, res_data = WordService.get_book_words_list(
        user_id=g.user_id,
        book_id=book_id,
        filter_type=filter_type,
        page=page,
        page_size=page_size
    )
    if not success:
        return error_response(msg=msg, code=400)
    return success_response(data=res_data, msg=msg)




@words_bp.route('/dashboard/summary', methods=['GET'])
@login_required
def get_dashboard_summary():
    from services.page_service import PageService
    success, msg, data = PageService.dashboard(g.user_id)
    return success_response(data=data, msg=msg) if success else error_response(msg=msg, code=400)


@words_bp.route('/practice/<session_id>', methods=['GET'])
@login_required
def get_independent_practice(session_id):
    from services.independent_practice_service import IndependentPracticeService
    success, msg, result = IndependentPracticeService.get(g.user_id, session_id)
    return success_response(data=result, msg=msg) if success else error_response(msg=msg, code=400)


@words_bp.route('/practice/<session_id>/answer', methods=['POST'])
@login_required
def answer_independent_practice(session_id):
    from services.independent_practice_service import IndependentPracticeService
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response(msg='请求体必须为JSON对象', code=400)
    success, msg, result = IndependentPracticeService.answer(
        g.user_id, session_id, data.get('request_id'), data.get('answer'))
    return success_response(data=result, msg=msg) if success else error_response(msg=msg, code=400)


@words_bp.route('/practice/<session_id>/submit', methods=['POST'])
@login_required
def submit_independent_practice(session_id):
    from services.independent_practice_service import IndependentPracticeService
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response(msg='请求体必须为JSON对象', code=400)
    success, msg, result = IndependentPracticeService.submit(g.user_id, session_id, data.get('request_id'), data.get('answers'))
    return success_response(data=result, msg=msg) if success else error_response(msg=msg, code=400)


def change_review_state(action):
    from services.review_state_service import ReviewStateService
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response(msg='请求体必须为JSON对象', code=400)
    success, msg, result = ReviewStateService.change(g.user_id, data.get('word_id'), action, data.get('request_id'))
    return success_response(data=result, msg=msg) if success else error_response(msg=msg, code=400)


@words_bp.route('/review/pause', methods=['POST'])
@login_required
def pause_review_word():
    return change_review_state('pause')


@words_bp.route('/review/resume', methods=['POST'])
@login_required
def resume_review_word():
    return change_review_state('resume')


@words_bp.route('/master/reset', methods=['POST'])
@login_required
def reset_mastered_word():
    return change_review_state('reset')


@words_bp.route('/review/paused', methods=['GET'])
@login_required
def get_paused_review_words():
    from services.review_state_service import ReviewStateService
    try:
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 20))
    except ValueError:
        return error_response(msg='page、page_size必须为整数', code=400)
    success, msg, result = ReviewStateService.paused_words(g.user_id, page, page_size)
    return success_response(data=result, msg=msg) if success else error_response(msg=msg, code=400)
