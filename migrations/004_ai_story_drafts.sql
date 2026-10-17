-- 第四批：AI草稿独立于正式文库，request_id按用户唯一防止重复生成。
CREATE TABLE IF NOT EXISTS ai_story_drafts (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    book_id VARCHAR(32) NOT NULL,
    request_id VARCHAR(64) NOT NULL,
    status ENUM('generating', 'ready', 'failed', 'saved') NOT NULL DEFAULT 'generating',
    version INT UNSIGNED NOT NULL DEFAULT 0,
    state JSON NOT NULL COMMENT '输入快照、标题、正文、生成错误或保存回执',
    story_id BIGINT UNSIGNED DEFAULT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    UNIQUE KEY uq_ai_generation_request (user_id, request_id),
    INDEX idx_ai_draft_user (user_id, updated_at),
    CONSTRAINT fk_ai_draft_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_ai_draft_book FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
    CONSTRAINT fk_ai_draft_story FOREIGN KEY (story_id) REFERENCES stories(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
