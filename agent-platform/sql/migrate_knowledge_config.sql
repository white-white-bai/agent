-- 知识库级处理设置增量迁移：
--   ap_dataset 增 index_method（高质量/经济）与 chunk_config（分段/清洗默认配置）；
--   ap_document 增 chunk_config（每文档覆盖）。
-- 与 src/agent_platform/domain/models.py 的 Dataset / Document 对应；可重复执行（列存在即跳过）。
-- 新建库直接执行 ddl.sql 即可，无需本脚本。

SET NAMES utf8mb4;

DROP PROCEDURE IF EXISTS ap_migrate_knowledge_config;
DELIMITER $$
CREATE PROCEDURE ap_migrate_knowledge_config()
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ap_dataset' AND COLUMN_NAME = 'index_method'
    ) THEN
        ALTER TABLE ap_dataset
            ADD COLUMN index_method VARCHAR(16) NOT NULL DEFAULT 'high_quality' AFTER embedding_model;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ap_dataset' AND COLUMN_NAME = 'chunk_config'
    ) THEN
        ALTER TABLE ap_dataset
            ADD COLUMN chunk_config JSON NULL AFTER index_method;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ap_document' AND COLUMN_NAME = 'chunk_config'
    ) THEN
        ALTER TABLE ap_document
            ADD COLUMN chunk_config JSON NULL AFTER error;
    END IF;
END$$
DELIMITER ;

CALL ap_migrate_knowledge_config();
DROP PROCEDURE ap_migrate_knowledge_config;
