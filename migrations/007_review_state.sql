-- 第八批：暂停状态独立于learning/reviewing/mastered，原学习记录保持不变。
CREATE TABLE IF NOT EXISTS review_pauses (
    user_id BIGINT UNSIGNED NOT NULL,
    word_id BIGINT UNSIGNED NOT NULL,
    paused_at DATETIME NOT NULL,
    PRIMARY KEY (user_id, word_id),
    CONSTRAINT fk_pause_learning_record FOREIGN KEY (user_id, word_id)
        REFERENCES user_word_records(user_id, word_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS review_state_requests (
    user_id BIGINT UNSIGNED NOT NULL,
    request_id VARCHAR(64) NOT NULL,
    action ENUM('pause', 'resume', 'reset') NOT NULL,
    word_id BIGINT UNSIGNED NOT NULL,
    result JSON NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (user_id, request_id),
    CONSTRAINT fk_review_request_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
