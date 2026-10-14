-- 记忆摘要增量迁移：ap_conversation 增 summary / summary_upto_id
-- 与 src/agent_platform/domain/models.py 的 Conversation 对应；可重复执行（存在即跳过）。
-- 新建库直接执行 ddl.sql 即可，无需本脚本。

SET NAMES utf8mb4;

DROP PROCEDURE IF EXISTS ap_add_conversation_summary;
DELIMITER $$
CREATE PROCEDURE ap_add_conversation_summary()
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ap_conversation' AND COLUMN_NAME = 'summary'
    ) THEN
        ALTER TABLE ap_conversation
            ADD COLUMN summary TEXT NULL AFTER name,
            ADD COLUMN summary_upto_id BIGINT NOT NULL DEFAULT 0 AFTER summary;
    END IF;
END$$
DELIMITER ;

CALL ap_add_conversation_summary();
DROP PROCEDURE ap_add_conversation_summary;
