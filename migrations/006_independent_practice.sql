-- 第七批：自主练习与正式学习、正式复习完全独立。
CREATE TABLE IF NOT EXISTS independent_practice_sessions (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    source ENUM('favorites', 'learn') NOT NULL,
    request_id VARCHAR(64) NOT NULL,
    book_id VARCHAR(32) NOT NULL,
    status ENUM('active', 'completed') NOT NULL DEFAULT 'active',
    state JSON NOT NULL COMMENT '私有题目快照、正确答案、提交回执',
    created_at DATETIME NOT NULL,
    completed_at DATETIME DEFAULT NULL,
    UNIQUE KEY uq_independent_practice_request (user_id, source, request_id),
    CONSTRAINT fk_independent_practice_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_independent_practice_book FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
