-- 第三批：新增阅读位置表，不修改已有学习或完读记录。
CREATE TABLE IF NOT EXISTS reading_progress (
    user_id BIGINT UNSIGNED NOT NULL,
    story_id BIGINT UNSIGNED NOT NULL,
    progress DECIMAL(5,2) NOT NULL DEFAULT 0 COMMENT '阅读百分比，0到100，不代表手动完读',
    position INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '去除word标签后的正文字符偏移',
    version INT UNSIGNED NOT NULL DEFAULT 1 COMMENT '跨设备更新版本，防止旧进度覆盖新进度',
    last_read_at DATETIME NOT NULL,
    PRIMARY KEY (user_id, story_id),
    INDEX idx_last_read (user_id, last_read_at),
    CONSTRAINT fk_reading_progress_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_reading_progress_story FOREIGN KEY (story_id) REFERENCES stories(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
