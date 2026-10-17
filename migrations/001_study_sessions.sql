-- 在后端实际使用的数据库执行。仅新增表，不修改历史学习数据。
-- 示例：mysql -u <user> -p storylex_db < migrations/001_study_sessions.sql
CREATE TABLE IF NOT EXISTS study_groups (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    book_id VARCHAR(32) NOT NULL,
    task_type ENUM('learn', 'review') NOT NULL,
    study_date DATE NOT NULL,
    status ENUM('active', 'completed') NOT NULL DEFAULT 'active',
    state JSON NOT NULL COMMENT '题目快照、正确答案、通过状态、请求回执及结算结果，仅服务端读取',
    created_at DATETIME NOT NULL,
    completed_at DATETIME DEFAULT NULL,
    INDEX idx_active_group (user_id, book_id, task_type, study_date, status),
    CONSTRAINT fk_study_group_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_study_group_book FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS daily_review_words (
    user_id BIGINT UNSIGNED NOT NULL,
    word_id BIGINT UNSIGNED NOT NULL,
    study_date DATE NOT NULL,
    PRIMARY KEY (user_id, study_date, word_id),
    CONSTRAINT fk_daily_review_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_daily_review_word FOREIGN KEY (word_id) REFERENCES words(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
