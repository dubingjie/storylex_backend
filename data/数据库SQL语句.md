```sql
CREATE TABLE `books` (
    `id` VARCHAR(32) NOT NULL COMMENT '词书唯一标识符 (如 CET6luan_1, KaoYan_2)',
    `title` VARCHAR(100) NOT NULL COMMENT '词书名称',
    `description` VARCHAR(255) DEFAULT NULL COMMENT '词书简介说明',
    `word_count` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '词书包含的总词数',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='词书信息表';




CREATE TABLE `words` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '单词全局唯一ID',
    `word` VARCHAR(64) NOT NULL COMMENT '英文单词原型(存入前严格转小写)',
    `us_phone` VARCHAR(64) DEFAULT NULL COMMENT '美式音标',
    `uk_phone` VARCHAR(64) DEFAULT NULL COMMENT '英式音标',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '录入时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_word` (`word`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='全局基础单词字典表';




CREATE TABLE `book_words` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '自增主键',
    `book_id` VARCHAR(32) NOT NULL COMMENT '所属词书ID',
    `word_id` BIGINT UNSIGNED NOT NULL COMMENT '关联基础单词ID',
    `word_rank` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '在当前词书中的排位序号',
    `book_trans` JSON DEFAULT NULL COMMENT '当前词书专属释义数组',
    `book_sentences` JSON DEFAULT NULL COMMENT '当前词书专属例句数组',
    `book_phrases` JSON DEFAULT NULL COMMENT '当前词书考点短语数组',
    `book_rem_method` VARCHAR(255) DEFAULT NULL COMMENT '当前词书助记法/记忆法',
    `book_synos` JSON DEFAULT NULL COMMENT '当前词书同近义词数组',
    `book_rel_words` JSON DEFAULT NULL COMMENT '当前词书同根词数组',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '绑定时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_book_word` (`book_id`, `word_id`),
    INDEX `idx_book_rank` (`book_id`, `word_rank`),
    CONSTRAINT `fk_bw_book` FOREIGN KEY (`book_id`) REFERENCES `books` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_bw_word` FOREIGN KEY (`word_id`) REFERENCES `words` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='词书-单词映射与专属考点表';





CREATE TABLE IF NOT EXISTS `users` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '用户ID',
    `username` VARCHAR(50) NOT NULL COMMENT '登录账号',
    `password_hash` VARCHAR(255) NOT NULL COMMENT '哈希密码',
    `avatar_url` VARCHAR(255) DEFAULT NULL COMMENT '用户头像链接',
    `current_book_id` VARCHAR(32) NOT NULL DEFAULT 'CET6luan_1' COMMENT '当前选择的主修词书',
    `daily_new_target` INT UNSIGNED NOT NULL DEFAULT 10 COMMENT '每日新学目标词数',
    `daily_review_target` INT UNSIGNED NOT NULL DEFAULT 10 COMMENT '每日复习目标词数',
    `last_login_at` DATETIME DEFAULT NULL COMMENT '最近一次登录时间',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '注册时间',
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '修改时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_username` (`username`),
    CONSTRAINT `fk_users_book` FOREIGN KEY (`current_book_id`) REFERENCES `books` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户基础与偏好表';




CREATE TABLE IF NOT EXISTS `user_word_records` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `user_id` BIGINT UNSIGNED NOT NULL COMMENT '所属用户ID',
    `word_id` BIGINT UNSIGNED NOT NULL COMMENT '全局客观单词ID',
    `status` ENUM('learning', 'reviewing', 'mastered') NOT NULL DEFAULT 'learning' COMMENT '学习状态: learning/reviewing/mastered',
    `stage` TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '艾宾浩斯阶段 (0~7)',
    `proficiency` INT NOT NULL DEFAULT 0 COMMENT '熟练度分值',
    `wrong_count` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '累计答错/看答案次数',
    `review_count` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '累计复习总次数',
    `last_reviewed_at` DATETIME DEFAULT NULL COMMENT '上一次做题时间',
    `next_review_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '下次复习到期时间',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '首次加入学习时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_user_word` (`user_id`, `word_id`),
    INDEX `idx_user_schedule` (`user_id`, `status`, `next_review_at`),
    CONSTRAINT `fk_uwr_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_uwr_word` FOREIGN KEY (`word_id`) REFERENCES `words` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户单词学习与复习状态表';




CREATE TABLE IF NOT EXISTS `stories` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '文章ID',
    `title` VARCHAR(150) NOT NULL COMMENT '文章标题',
    `source_type` ENUM('builtin', 'imported', 'ai_generated') NOT NULL DEFAULT 'builtin' COMMENT '来源: 内置/导入/AI生成',
    `user_id` BIGINT UNSIGNED DEFAULT NULL COMMENT '创建用户ID (系统内置为 NULL)',
    `target_book_id` VARCHAR(32) NOT NULL DEFAULT 'CET6luan_1' COMMENT '目标词书难度',
    `original_content` MEDIUMTEXT NOT NULL COMMENT '纯中文原文',
    `processed_content` MEDIUMTEXT DEFAULT NULL COMMENT '中英混排带标签正文',
    `word_count` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '中文总字数',
    `embedded_word_count` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '内嵌英文生词总数',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    PRIMARY KEY (`id`),
    INDEX `idx_source_user` (`source_type`, `user_id`),
    CONSTRAINT `fk_stories_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_stories_book` FOREIGN KEY (`target_book_id`) REFERENCES `books` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='爽文小说文章库表';





CREATE TABLE IF NOT EXISTS `story_words` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `story_id` BIGINT UNSIGNED NOT NULL COMMENT '文章ID',
    `word_id` BIGINT UNSIGNED NOT NULL COMMENT '单词全局ID',
    `word_order` INT UNSIGNED NOT NULL DEFAULT 1 COMMENT '在正文中出现的先后顺序',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '关联时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_story_word` (`story_id`, `word_id`),
    INDEX `idx_story_order` (`story_id`, `word_order`),
    CONSTRAINT `fk_sw_story` FOREIGN KEY (`story_id`) REFERENCES `stories` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_sw_word` FOREIGN KEY (`word_id`) REFERENCES `words` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='文章与内嵌生词关联表';





CREATE TABLE IF NOT EXISTS `user_favorite_words` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `user_id` BIGINT UNSIGNED NOT NULL COMMENT '用户ID',
    `word_id` BIGINT UNSIGNED NOT NULL COMMENT '被收藏单词ID',
    `source_type` ENUM('flashcard', 'story') NOT NULL DEFAULT 'flashcard' COMMENT '收藏来源: flashcard(背词卡片)/story(语境阅读)',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '收藏时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_user_fav_word` (`user_id`, `word_id`),
    INDEX `idx_user_source` (`user_id`, `source_type`),
    CONSTRAINT `fk_ufw_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_ufw_word` FOREIGN KEY (`word_id`) REFERENCES `words` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户生词收藏表';





CREATE TABLE IF NOT EXISTS `user_study_stats` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `user_id` BIGINT UNSIGNED NOT NULL COMMENT '用户ID',
    `study_date` DATE NOT NULL COMMENT '统计归档自然日 (如 2026-10-11)',
    `new_learned_count` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '今日新学单词数 (首页左侧任务)',
    `reviewed_count` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '今日复习单词数 (首页右侧任务)',
    `read_story_count` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '今日完成阅读文章数',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_user_date` (`user_id`, `study_date`),
    CONSTRAINT `fk_uss_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='每日学习统计与打卡表';






CREATE TABLE IF NOT EXISTS `user_story_records` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    `user_id` BIGINT UNSIGNED NOT NULL COMMENT '所属用户ID',
    `story_id` BIGINT UNSIGNED NOT NULL COMMENT '关联文章ID',
    `is_completed` TINYINT(1) UNSIGNED NOT NULL DEFAULT 0 COMMENT '是否阅读完成 (0: 未读完, 1: 已读完)',
    `last_practice_score` INT DEFAULT NULL COMMENT '最近一次配套测试得分 (未做练习前为 NULL)',
    `completed_at` DATETIME DEFAULT NULL COMMENT '首次阅读完读打卡时间',
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '记录最后更新时间',
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_user_story` (`user_id`, `story_id`),
    INDEX `idx_user_complete` (`user_id`, `is_completed`),
    CONSTRAINT `fk_usr_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_usr_story` FOREIGN KEY (`story_id`) REFERENCES `stories` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户文章阅读打卡与练习测试记录表';



CREATE TABLE IF NOT EXISTS `user_story_records` (
    `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `user_id` BIGINT UNSIGNED NOT NULL COMMENT '用户ID',
    `story_id` BIGINT UNSIGNED NOT NULL COMMENT '文章ID',
    `is_completed` TINYINT(1) UNSIGNED NOT NULL DEFAULT 0 COMMENT '是否已读完(0否, 1是)',
    `last_practice_score` INT DEFAULT NULL COMMENT '最近一次练习得分',
    `completed_at` DATETIME DEFAULT NULL COMMENT '首次读完时间',
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY `uq_user_story` (`user_id`, `story_id`),
    INDEX `idx_user_complete` (`user_id`, `is_completed`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户文章阅读与练习记录表';
```

