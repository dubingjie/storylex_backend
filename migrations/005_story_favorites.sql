-- 第六批：文章收藏独立于单词收藏和阅读记录。
CREATE TABLE IF NOT EXISTS user_favorite_stories (
    user_id BIGINT UNSIGNED NOT NULL,
    story_id BIGINT UNSIGNED NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (user_id, story_id),
    INDEX idx_favorite_story (story_id),
    CONSTRAINT fk_favorite_story_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_favorite_story_story FOREIGN KEY (story_id) REFERENCES stories(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
