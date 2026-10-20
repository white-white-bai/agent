-- 老库新增用户级长期记忆表；可重复执行。
-- 对应 src/agent_platform/domain/models.py 的 UserMemory / UserMemoryState。
-- 新建库直接执行 ddl.sql 即可，无需本脚本。
SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS ap_user_memory (
    id                     BIGINT       NOT NULL AUTO_INCREMENT,
    uuid                   VARCHAR(64)  NOT NULL,
    tenant_code            VARCHAR(64)  NOT NULL DEFAULT '',
    app_uuid               VARCHAR(64)  NOT NULL DEFAULT '',
    user_key               VARCHAR(128) NOT NULL,
    user_name              VARCHAR(128) NOT NULL DEFAULT '',
    kind                   VARCHAR(16)  NOT NULL DEFAULT 'fact',
    content                LONGTEXT     NULL,
    embedding              JSON         NULL,
    embedding_model        VARCHAR(64)  NOT NULL DEFAULT '',
    importance             FLOAT        NOT NULL DEFAULT 0.5,
    source_conversation_id VARCHAR(64)  NOT NULL DEFAULT '',
    source_message_id      VARCHAR(64)  NOT NULL DEFAULT '',
    content_hash           VARCHAR(64)  NOT NULL DEFAULT '',
    enabled                INT          NOT NULL DEFAULT 1,
    hit_count              INT          NOT NULL DEFAULT 0,
    last_hit_at            DATETIME     NULL,
    expires_at             DATETIME     NULL,
    is_deleted             INT          NOT NULL DEFAULT 0,
    created_at             DATETIME     NOT NULL,
    updated_at             DATETIME     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_ap_user_memory_uuid (uuid),
    UNIQUE KEY uk_ap_user_memory_dedup (tenant_code, user_key, app_uuid, content_hash),
    KEY idx_ap_user_memory_scope (tenant_code, user_key, app_uuid, is_deleted)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT '用户级长期记忆';

CREATE TABLE IF NOT EXISTS ap_user_memory_state (
    id              BIGINT       NOT NULL AUTO_INCREMENT,
    uuid            VARCHAR(64)  NOT NULL,
    tenant_code     VARCHAR(64)  NOT NULL DEFAULT '',
    app_uuid        VARCHAR(64)  NOT NULL DEFAULT '',
    user_key        VARCHAR(128) NOT NULL,
    last_message_id BIGINT       NOT NULL DEFAULT 0,
    last_run_at     DATETIME     NULL,
    created_at      DATETIME     NOT NULL,
    updated_at      DATETIME     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_ap_user_memory_state_uuid (uuid),
    UNIQUE KEY uk_ap_user_memory_state (tenant_code, user_key, app_uuid)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT '用户记忆抽取水位线';
