from flask import Blueprint, request, g
from services.story_service import StoryService
from utils.response import success_response, error_response
from utils.auth_helper import login_required

stories_bp = Blueprint('stories', __name__, url_prefix='/api/stories')

@stories_bp.route('/list', methods=['GET'])
@login_required
def get_story_list():
    """5.1 分页获取文章列表"""
    try:
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 10))
    except ValueError:
        return error_response(msg='page、page_size必须为整数', code=400)
    source_type = request.args.get("source_type", None)

    success, msg, data = StoryService.get_story_list(
        user_id=g.user_id,
        page=page,
        page_size=page_size,
        source_type=source_type,
        category=request.args.get('category', 'all'),
        keyword=request.args.get('keyword'),
        scope=request.args.get('scope', 'all')
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
    req_data = request.get_json(silent=True)
    if not isinstance(req_data, dict):
        return error_response(msg="请求体必须为JSON对象", code=400)
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
    """旧路径兼容：生成预览草稿，不再直接写入文库。"""
    from routes.ai import generate_request
    return generate_request()

@stories_bp.route('/<int:story_id>/vocabulary', methods=['GET'])
@login_required
def get_story_vocabulary(story_id):
    success, msg, data = StoryService.get_story_vocabulary(g.user_id, story_id)
    return success_response(data=data, msg=msg) if success else error_response(msg=msg, code=400)


@stories_bp.route('/<int:story_id>/practice', methods=['GET'])
@login_required
def get_story_practice(story_id):
    success, msg, data = StoryService.get_story_practice(g.user_id, story_id)
    return success_response(data=data, msg=msg) if success else error_response(msg=msg, code=400)


@stories_bp.route('/<int:story_id>/practice/submit', methods=['POST'])
@login_required
def submit_story_practice(story_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response(msg='请求体必须为 JSON 对象', code=400)
    success, msg, result = StoryService.submit_story_practice(
        g.user_id, story_id, data.get('session_id'), data.get('request_id'), data.get('answers'))
    return success_response(data=result, msg=msg) if success else error_response(msg=msg, code=400)


@stories_bp.route('/<int:story_id>/progress', methods=['GET', 'PUT'])
@login_required
def story_reading_progress(story_id):
    from services.page_service import PageService
    if request.method == 'GET':
        result = PageService.get_progress(g.user_id, story_id)
    else:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return error_response(msg='请求体必须为 JSON 对象', code=400)
        result = PageService.save_progress(g.user_id, story_id, data.get('progress'), data.get('position'), data.get('version'))
    success, msg, data = result
    return success_response(data=data, msg=msg) if success else error_response(msg=msg, code=400)


@stories_bp.route('/<int:story_id>/favorite', methods=['PUT'])
@login_required
def set_story_favorite(story_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response(msg='请求体必须为JSON对象', code=400)
    success, msg, result = StoryService.set_story_favorite(g.user_id, story_id, data.get('is_favorited'))
    return success_response(data=result, msg=msg) if success else error_response(msg=msg, code=400)
