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

@words_bp.route('/learn/answer', methods=['POST'])
@login_required
def check_learn_answer():
    """1.4 单题提交答案判定与解析获取"""
    req_data = request.get_json() or {}
    word_id = req_data.get("word_id")
    selected_key = req_data.get("selected_key")
    is_show_answer = req_data.get("is_show_answer", False)
    options = req_data.get("options", [])  # 前端当前渲染的 A/B/C/D 选项列表

    if not word_id:
        return error_response(msg="word_id 不能为空", code=400)

    success, msg, data = WordService.check_learn_answer(
        user_id=g.user_id,
        word_id=word_id,
        selected_key=selected_key,
        is_show_answer=is_show_answer,
        options=options
    )
    if not success:
        return error_response(msg=msg, code=400)
    return success_response(data=data, msg=msg)

@words_bp.route('/learn/group/complete', methods=['POST'])
@login_required
def complete_learn_group():
    """1.5 组结清零小结结算与数据入库"""
    req_data = request.get_json() or {}
    group_id = req_data.get("group_id")
    word_mistakes = req_data.get("word_mistakes")

    if not group_id or word_mistakes is None:
        return error_response(msg="参数缺失: group_id 与 word_mistakes 不能为空", code=400)

    success, msg, data = WordService.complete_learn_group(
        user_id=g.user_id,
        group_id=group_id,
        word_mistakes=word_mistakes
    )
    if not success:
        return error_response(msg=msg, code=400)
    return success_response(data=data, msg=msg)



@words_bp.route('/review/group', methods=['GET'])
@login_required
def get_review_group():
    """2.1 获取今日待复习单词组"""
    success, msg, data = WordService.get_review_group(user_id=g.user_id)
    if not success:
        return error_response(msg=msg, code=400)
    return success_response(data=data, msg=msg)

@words_bp.route('/review/answer', methods=['POST'])
@login_required
def answer_review_word():
    """2.2 复习单题判题与艾宾浩斯更新"""
    req_data = request.get_json() or {}
    word_id = req_data.get("word_id")
    selected_key = req_data.get("selected_key")
    is_show_answer = req_data.get("is_show_answer", False)
    options = req_data.get("options", [])

    if not word_id:
        return error_response(msg="word_id 不能为空", code=400)

    success, msg, data = WordService.answer_review_word(
        user_id=g.user_id,
        word_id=word_id,
        selected_key=selected_key,
        is_show_answer=is_show_answer,
        options=options
    )
    if not success:
        return error_response(msg=msg, code=400)
    return success_response(data=data, msg=msg)

@words_bp.route('/review/complete', methods=['POST'])
@login_required
def complete_review_group():
    """2.3 复习组结算归档"""
    req_data = request.get_json() or {}
    reviewed_count = req_data.get("reviewed_count", 0)

    success, msg, data = WordService.complete_review_group(
        user_id=g.user_id,
        reviewed_count=reviewed_count
    )
    if not success:
        return error_response(msg=msg, code=400)
    return success_response(data=data, msg=msg)




@words_bp.route('/favorite/toggle', methods=['POST'])
@login_required
def toggle_favorite():
    """3.1 切换单词收藏状态"""
    req_data = request.get_json() or {}
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
    data = request.get_json() or {}
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
    """1.6 当堂小结巩固练习题抽取"""
    data = request.get_json() or {}
    word_ids = data.get("word_ids", [])

    if not word_ids or not isinstance(word_ids, list):
        return error_response(msg="word_ids 必须为非空整数列表", code=400)

    success, msg, res_data = WordService.get_group_practice_questions(
        user_id=g.user_id,
        word_ids=word_ids
    )
    if not success:
        return error_response(msg=msg, code=400)
    return success_response(data=res_data, msg=msg)




@words_bp.route('/book/list', methods=['GET'])
@login_required
def get_book_words_list():
    """2.5 获取词书总词表列表"""
    book_id = request.args.get('book_id')
    filter_type = request.args.get('filter', 'all')  # all, learned, unlearned
    page = int(request.args.get('page', 1))
    page_size = int(request.args.get('page_size', 20))

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


