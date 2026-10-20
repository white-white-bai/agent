-- 老库补 checkpoint HITL 所需列/索引；可重复执行。
-- 对应 src/agent_platform/domain/models.py 的 Checkpoint / CheckpointWrite。
-- 新建库直接执行 ddl.sql 即可，无需本脚本。
SET NAMES utf8mb4;

DROP PROCEDURE IF EXISTS ap_migrate_checkpoint_hitl;
DELIMITER $$
CREATE PROCEDURE ap_migrate_checkpoint_hitl()
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ap_checkpoint' AND COLUMN_NAME = 'metadata_type'
    ) THEN
        ALTER TABLE ap_checkpoint
            ADD COLUMN metadata_type VARCHAR(32) NOT NULL DEFAULT 'json' AFTER checkpoint;
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.TABLES
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ap_checkpoint') THEN
        ALTER TABLE ap_checkpoint MODIFY COLUMN checkpoint LONGBLOB NOT NULL;
        ALTER TABLE ap_checkpoint MODIFY COLUMN metadata LONGBLOB NOT NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ap_checkpoint'
          AND INDEX_NAME = 'idx_ap_checkpoint_thread_ns'
    ) THEN
        ALTER TABLE ap_checkpoint ADD KEY idx_ap_checkpoint_thread_ns (thread_id, checkpoint_ns, id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ap_checkpoint_write' AND COLUMN_NAME = 'task_path'
    ) THEN
        ALTER TABLE ap_checkpoint_write
            ADD COLUMN task_path VARCHAR(128) NOT NULL DEFAULT '' AFTER task_id;
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.TABLES
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ap_checkpoint_write') THEN
        ALTER TABLE ap_checkpoint_write MODIFY COLUMN value LONGBLOB NOT NULL;
    END IF;
END$$
DELIMITER ;

CALL ap_migrate_checkpoint_hitl();
DROP PROCEDURE ap_migrate_checkpoint_hitl;
