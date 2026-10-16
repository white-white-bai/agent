-- 知识库两层模型迁移：旧 ap_document（一行 = 一分段，含 title/content/embedding）
--   → ap_dataset（知识库）+ 新 ap_document（文档元数据）+ ap_document_segment（分段）。
--
-- 与 src/agent_platform/domain/models.py 的 Dataset / Document / DocumentSegment 对应。
-- 可重复执行：仅当 ap_document 仍是旧结构（有 title 列、无 name 列）时执行一次。
-- 新建库直接执行 ddl.sql 即可，无需本脚本。

SET NAMES utf8mb4;

DROP PROCEDURE IF EXISTS ap_migrate_knowledge_segments;
DELIMITER $$
CREATE PROCEDURE ap_migrate_knowledge_segments()
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ap_document' AND COLUMN_NAME = 'title'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ap_document' AND COLUMN_NAME = 'name'
    ) THEN
        -- 1. 旧表让位，避免新旧行混淆
        DROP TABLE IF EXISTS ap_document_legacy;
        RENAME TABLE ap_document TO ap_document_legacy;

        -- 2. 建新表（若 create_all 已建则保留）
        CREATE TABLE IF NOT EXISTS ap_dataset (
            id              BIGINT       NOT NULL AUTO_INCREMENT,
            uuid            VARCHAR(64)  NOT NULL,
            tenant_code     VARCHAR(64)  NOT NULL DEFAULT '',
            name            VARCHAR(128) NOT NULL DEFAULT '',
            description     TEXT         NULL,
            embedding_model VARCHAR(64)  NOT NULL DEFAULT '',
            retrieval       JSON         NULL,
            is_deleted      INT          NOT NULL DEFAULT 0,
            created_at      DATETIME     NOT NULL,
            updated_at      DATETIME     NOT NULL,
            PRIMARY KEY (id),
            UNIQUE KEY uk_ap_dataset_uuid (uuid),
            KEY idx_ap_dataset_tenant (tenant_code)
        ) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT '知识库（数据集）';

        CREATE TABLE IF NOT EXISTS ap_document (
            id          BIGINT       NOT NULL AUTO_INCREMENT,
            uuid        VARCHAR(64)  NOT NULL,
            tenant_code VARCHAR(64)  NOT NULL DEFAULT '',
            dataset_id  VARCHAR(64)  NOT NULL DEFAULT '',
            name        VARCHAR(255) NOT NULL DEFAULT '',
            content     LONGTEXT     NULL,
            file_type   VARCHAR(32)  NOT NULL DEFAULT '',
            file_size   INT          NOT NULL DEFAULT 0,
            char_count  INT          NOT NULL DEFAULT 0,
            chunk_count INT          NOT NULL DEFAULT 0,
            status      VARCHAR(16)  NOT NULL DEFAULT 'ready',
            error       VARCHAR(512) NOT NULL DEFAULT '',
            metadata    JSON         NULL,
            created_by  VARCHAR(64)  NOT NULL DEFAULT '',
            is_deleted  INT          NOT NULL DEFAULT 0,
            created_at  DATETIME     NOT NULL,
            updated_at  DATETIME     NOT NULL,
            PRIMARY KEY (id),
            UNIQUE KEY uk_ap_document_uuid (uuid),
            KEY idx_ap_document_dataset (tenant_code, dataset_id)
        ) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT '知识库文档元数据';

        CREATE TABLE IF NOT EXISTS ap_document_segment (
            id            BIGINT       NOT NULL AUTO_INCREMENT,
            uuid          VARCHAR(64)  NOT NULL,
            tenant_code   VARCHAR(64)  NOT NULL DEFAULT '',
            dataset_id    VARCHAR(64)  NOT NULL DEFAULT '',
            document_uuid VARCHAR(64)  NOT NULL,
            position      INT          NOT NULL DEFAULT 0,
            content       TEXT         NULL,
            embedding     JSON         NULL,
            enabled       INT          NOT NULL DEFAULT 1,
            hit_count     INT          NOT NULL DEFAULT 0,
            created_at    DATETIME     NOT NULL,
            PRIMARY KEY (id),
            UNIQUE KEY uk_ap_document_segment_uuid (uuid),
            KEY idx_ap_document_segment_doc (document_uuid),
            KEY idx_ap_document_segment_dataset (tenant_code, dataset_id)
        ) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT '知识库文档分段';

        -- 3. 为出现过的非空 dataset_id 补建知识库行（uuid = dataset_id，供图节点选择器使用）
        INSERT IGNORE INTO ap_dataset
            (uuid, tenant_code, name, description, embedding_model, retrieval, is_deleted, created_at, updated_at)
        SELECT DISTINCT dataset_id, tenant_code, dataset_id, '', '', JSON_OBJECT(), 0, NOW(), NOW()
        FROM ap_document_legacy
        WHERE dataset_id <> '';

        -- 4. 每个 (租户, 数据集, 标题) 归为一个文档
        INSERT INTO ap_document
            (uuid, tenant_code, dataset_id, name, content, file_type, file_size, char_count,
             chunk_count, status, error, metadata, created_by, is_deleted, created_at, updated_at)
        SELECT MD5(CONCAT_WS('|', tenant_code, dataset_id, title)),
               tenant_code, dataset_id, title, '', 'legacy', 0, 0,
               COUNT(*), 'ready', '', JSON_OBJECT('source', 'migrated'), '', 0, MIN(created_at), NOW()
        FROM ap_document_legacy
        GROUP BY tenant_code, dataset_id, title;

        -- 5. 旧行整体搬成分段（position 取原 metadata.chunk）
        INSERT INTO ap_document_segment
            (uuid, tenant_code, dataset_id, document_uuid, position, content, embedding, enabled, hit_count, created_at)
        SELECT legacy.uuid,
               legacy.tenant_code, legacy.dataset_id,
               MD5(CONCAT_WS('|', legacy.tenant_code, legacy.dataset_id, legacy.title)),
               COALESCE(CAST(JSON_EXTRACT(legacy.metadata, '$.chunk') AS UNSIGNED), 0),
               legacy.content, legacy.embedding, 1, 0, legacy.created_at
        FROM ap_document_legacy AS legacy;

        DROP TABLE ap_document_legacy;
    END IF;
END$$
DELIMITER ;

CALL ap_migrate_knowledge_segments();
DROP PROCEDURE ap_migrate_knowledge_segments;
