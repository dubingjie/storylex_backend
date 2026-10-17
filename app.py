from flask import Flask
from flask_cors import CORS
from werkzeug.exceptions import HTTPException
from config import Config
from utils.response import success_response, error_response
from db import get_db

# 导入业务路由蓝图
from routes.ai import ai_bp
from routes.auth import auth_bp
from routes.words import words_bp
from routes.user import user_bp
from routes.stories import stories_bp  # 新增导入

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.json.ensure_ascii = False

    CORS(app, resources={r"/api/*": {"origins": "*"}})

    @app.errorhandler(404)
    def handle_not_found(e):
        return error_response(msg="请求的资源接口不存在", code=404)

    @app.errorhandler(Exception)
    def handle_exception(e):
        if isinstance(e, HTTPException):
            return error_response(msg=e.description, code=e.code)
        return error_response(msg=f"服务端异常: {str(e)}", code=500)

    # 注册蓝图
    app.register_blueprint(ai_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(words_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(stories_bp)  # 新增注册

    @app.route('/api/health', methods=['GET'])
    def health_check():
        with get_db() as cursor:
            cursor.execute("SELECT COUNT(*) AS total_words FROM words;")
            row = cursor.fetchone()
        return success_response({
            "service_status": "healthy",
            "db_words_count": row['total_words']
        }, msg="服务与数据库通信正常")

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=Config.PORT, debug=Config.DEBUG)