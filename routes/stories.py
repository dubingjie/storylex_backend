from flask import Blueprint, request, g
from services.story_service import StoryService
from utils.response import success_response, error_response
from utils.auth_helper import login_required

stories_bp = Blueprint('stories', __name__, url_prefix='/api/stories')

@stories_bp.route('/list', methods=['GET'])
@login_required
def get_story_list():
    """5.1 分页获取文章列表"""
    page = request.args.get("page", 1, type=int)
    page_size = request.args.get("page_size", 10, type=int)
    source_type = request.args.get("source_type", None)

    success, msg, data = StoryService.get_story_list(
        user_id=g.user_id,
        page=page,
        page_size=page_size,
        source_type=source_type
    )
    if not success:
        return error_response(msg=msg, code=400)
    return success_response(data=data, msg=msg)

@stories_bp.route('/detail/<int:story_id>', methods=['GET'])
@login_required
def get_story_detail(story_id):
    """5.2 获取文章正文及内嵌生词详情"""
    success, msg, data = StoryService.get_story_detail(
        user_id=g.user_id,
        story_id=story_id
    )
    if not success:
        return error_response(msg=msg, code=404)
    return success_response(data=data, msg=msg)

@stories_bp.route('/complete', methods=['POST'])
@login_required
def complete_story():
    """5.3 提交完读打卡"""
    req_data = request.get_json() or {}
    story_id = req_data.get("story_id")
    if not story_id:
        return error_response(msg="story_id 不能为空", code=400)

    success, msg, data = StoryService.complete_story(
        user_id=g.user_id,
        story_id=story_id
    )
    if not success:
        return error_response(msg=msg, code=400)
    return success_response(data=data, msg=msg)



@stories_bp.route('/generate', methods=['POST'])
@login_required
def generate_story():
    """5.4 基于生词生成 AI 故事"""
    data = request.get_json() or {}
    word_ids = data.get("word_ids", [])
    theme = data.get("theme", "天官赐福")

    if not word_ids or not isinstance(word_ids, list):
        return error_response(msg="word_ids 必须为非空整数列表", code=400)

    success, msg, res_data = StoryService.generate_ai_story(
        user_id=g.user_id,
        word_ids=word_ids,
        theme=theme
    )
    if not success:
        return error_response(msg=msg, code=400)
    return success_response(data=res_data, msg=msg)