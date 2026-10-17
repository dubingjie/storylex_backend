from flask import Blueprint, request, g
from services.ai_draft_service import AIDraftService
from utils.auth_helper import login_required
from utils.response import success_response, error_response

ai_bp = Blueprint('ai', __name__, url_prefix='/api/ai')


def result_response(result):
    success, msg, data = result
    return success_response(data=data, msg=msg) if success else error_response(msg=msg, code=400)


def generate_request():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response(msg='请求体必须为JSON对象', code=400)
    return result_response(AIDraftService.generate(
        g.user_id, data.get('word_ids'), data.get('request_id'),
        data.get('story_type', data.get('theme', '都市小说')), data.get('title')))


@ai_bp.route('/generate-story', methods=['POST'])
@login_required
def generate_story_preview():
    return generate_request()


@ai_bp.route('/drafts/<draft_id>', methods=['GET', 'PUT'])
@login_required
def story_draft(draft_id):
    if request.method == 'GET':
        return result_response(AIDraftService.get(g.user_id, draft_id))
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response(msg='请求体必须为JSON对象', code=400)
    return result_response(AIDraftService.edit(g.user_id, draft_id, data.get('title'),
                                             data.get('processed_content'), data.get('version')))


@ai_bp.route('/drafts/<draft_id>/save', methods=['POST'])
@login_required
def save_story_draft(draft_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response(msg='请求体必须为JSON对象', code=400)
    return result_response(AIDraftService.save(g.user_id, draft_id, data.get('request_id'), data.get('version')))


@ai_bp.route('/import-txt', methods=['POST'])
@login_required
def import_txt_preview():
    from services.txt_import_service import TxtImportService, MAX_FILE_BYTES
    # 在解析multipart之前设置总请求限制，文件内容再独立限制200KB。
    request.max_content_length = 300 * 1024
    if len(request.files.getlist('file')) != 1:
        return error_response(msg='请上传一个名为file的TXT文件', code=400)
    upload = request.files['file']
    try:
        max_replacements = int(request.form.get('max_replacements', '20'))
        min_gap = int(request.form.get('min_gap', '30'))
    except ValueError:
        return error_response(msg='max_replacements、min_gap必须为整数', code=400)
    return result_response(TxtImportService.preview(
        g.user_id, upload.stream.read(MAX_FILE_BYTES + 1), upload.filename,
        request.form.get('target_book_id'), request.form.get('request_id'),
        request.form.get('title') or None, max_replacements, min_gap))
