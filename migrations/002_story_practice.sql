-- 第二批：仅新增阅读练习题组表，不改动第一批表和历史学习数据。
CREATE TABLE IF NOT EXISTS story_practice_sessions (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    story_id BIGINT UNSIGNED NOT NULL,
    book_id VARCHAR(32) NOT NULL,
    study_date DATE NOT NULL,
    status ENUM('active', 'completed') NOT NULL DEFAULT 'active',
    state JSON NOT NULL COMMENT '服务端题目快照、正确答案及提交回执',
    created_at DATETIME NOT NULL,
    completed_at DATETIME DEFAULT NULL,
    INDEX idx_story_practice_active (user_id, story_id, book_id, study_date, status),
    CONSTRAINT fk_story_practice_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_story_practice_story FOREIGN KEY (story_id) REFERENCES stories(id) ON DELETE CASCADE,
    CONSTRAINT fk_story_practice_book FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
