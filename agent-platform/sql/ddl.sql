-- agent 中台 DDL（MySQL 8，复用现有实例，中台独立 schema）
-- 与 src/agent_platform/domain/models.py 对应；仓库无 DDL 目录，脚本随任务交付，由人工执行。
-- 注意：生产库若已在目标 schema 下，可用 CREATE TABLE IF NOT EXISTS 幂等执行。

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS ap_tenant (
    id          BIGINT       NOT NULL AUTO_INCREMENT,
    code        VARCHAR(64)  NOT NULL,
    name        VARCHAR(128) NOT NULL DEFAULT '',
    created_at  DATETIME     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_ap_tenant_code (code)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '租户（区域/appCode）';

CREATE TABLE IF NOT EXISTS ap_app (
    id                  BIGINT       NOT NULL AUTO_INCREMENT,
    uuid                VARCHAR(64)  NOT NULL,
    tenant_code         VARCHAR(64)  NOT NULL,
    app_id              VARCHAR(64)  NOT NULL,
    api_key             VARCHAR(128) NOT NULL,
    app_name            VARCHAR(128) NOT NULL DEFAULT '',
    app_type            VARCHAR(32)  NOT NULL DEFAULT 'chat',
    icon                VARCHAR(512) NOT NULL DEFAULT '',
    opening_statement   TEXT         NULL,
    suggested_questions JSON         NULL,
    app_info            JSON         NULL,
    is_deleted          INT          NOT NULL DEFAULT 0,
    created_at          DATETIME     NOT NULL,
    updated_at          DATETIME     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_ap_app_uuid (uuid),
    UNIQUE KEY uk_ap_app_app_id (app_id),
    KEY idx_ap_app_tenant (tenant_code)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '应用（agent）注册表';

CREATE TABLE IF NOT EXISTS ap_graph (
    id                   BIGINT      NOT NULL AUTO_INCREMENT,
    uuid                 VARCHAR(64) NOT NULL,
    tenant_code          VARCHAR(64) NOT NULL,
    app_uuid             VARCHAR(64) NOT NULL,
    status               VARCHAR(16) NOT NULL DEFAULT 'draft',
    published_version_id BIGINT      NULL,
    draft                JSON        NULL,
    created_at           DATETIME    NOT NULL,
    updated_at           DATETIME    NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_ap_graph_uuid (uuid),
    UNIQUE KEY uk_ap_graph_app_uuid (app_uuid),
    KEY idx_ap_graph_tenant (tenant_code)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '图定义（草稿，JSON document）';

CREATE TABLE IF NOT EXISTS ap_graph_version (
    id          BIGINT      NOT NULL AUTO_INCREMENT,
    uuid        VARCHAR(64) NOT NULL,
    graph_uuid  VARCHAR(64) NOT NULL,
    version     INT         NOT NULL,
    definition  JSON        NOT NULL,
    note        VARCHAR(512) NOT NULL DEFAULT '',
    created_by  VARCHAR(64) NOT NULL DEFAULT '',
    created_at  DATETIME    NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_ap_graph_version_uuid (uuid),
    UNIQUE KEY uk_ap_graph_version (graph_uuid, version)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '图发布版本（不可变快照）';

CREATE TABLE IF NOT EXISTS ap_conversation (
    id              BIGINT       NOT NULL AUTO_INCREMENT,
    uuid            VARCHAR(64)  NOT NULL,
    tenant_code     VARCHAR(64)  NOT NULL,
    app_uuid        VARCHAR(64)  NOT NULL,
    conversation_id VARCHAR(64)  NOT NULL,
    user_id         VARCHAR(64)  NOT NULL DEFAULT '',
    user_name       VARCHAR(128) NOT NULL DEFAULT '',
    name            VARCHAR(255) NOT NULL DEFAULT '',
    created_at      DATETIME     NOT NULL,
    updated_at      DATETIME     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_ap_conversation_uuid (uuid),
    UNIQUE KEY uk_ap_conversation_id (conversation_id),
    KEY idx_ap_conversation_app (app_uuid)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '会话';

CREATE TABLE IF NOT EXISTS ap_message (
    id               BIGINT       NOT NULL AUTO_INCREMENT,
    uuid             VARCHAR(64)  NOT NULL,
    conversation_uuid VARCHAR(64) NOT NULL,
    message_id       VARCHAR(64)  NOT NULL,
    parent_message_id VARCHAR(64) NOT NULL DEFAULT '',
    role             VARCHAR(16)  NOT NULL DEFAULT 'user',
    query            TEXT         NULL,
    answer           TEXT         NULL,
    answer_metadata  JSON         NULL,
    feedback         VARCHAR(16)  NULL,
    tokens           INT          NOT NULL DEFAULT 0,
    cost_seconds     DOUBLE       NOT NULL DEFAULT 0,
    created_at       DATETIME     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_ap_message_uuid (uuid),
    KEY idx_ap_message_conversation (conversation_uuid),
    KEY idx_ap_message_id (message_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '会话消息';

CREATE TABLE IF NOT EXISTS ap_sensitive_word (
    id          BIGINT       NOT NULL AUTO_INCREMENT,
    tenant_code VARCHAR(64)  NOT NULL DEFAULT '',
    word        VARCHAR(128) NOT NULL,
    created_at  DATETIME     NOT NULL,
    PRIMARY KEY (id),
    KEY idx_ap_sensitive_word (word),
    KEY idx_ap_sensitive_tenant (tenant_code)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '敏感词（中台自建护栏配置）';

CREATE TABLE IF NOT EXISTS ap_checkpoint (
    id                   BIGINT       NOT NULL AUTO_INCREMENT,
    thread_id            VARCHAR(128) NOT NULL,
    checkpoint_ns        VARCHAR(128) NOT NULL DEFAULT '',
    checkpoint_id        VARCHAR(128) NOT NULL,
    parent_checkpoint_id VARCHAR(128) NULL,
    type                 VARCHAR(32)  NOT NULL,
    checkpoint           LONGBLOB     NOT NULL,
    metadata             LONGBLOB     NOT NULL,
    created_at           DATETIME     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_ap_checkpoint (thread_id, checkpoint_ns, checkpoint_id),
    KEY idx_ap_checkpoint_thread (thread_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT 'LangGraph checkpoint（自研 MySQL checkpointer）';

CREATE TABLE IF NOT EXISTS ap_checkpoint_write (
    id            BIGINT       NOT NULL AUTO_INCREMENT,
    thread_id     VARCHAR(128) NOT NULL,
    checkpoint_ns VARCHAR(128) NOT NULL DEFAULT '',
    checkpoint_id VARCHAR(128) NOT NULL,
    task_id       VARCHAR(128) NOT NULL,
    idx           INT          NOT NULL,
    channel       VARCHAR(128) NOT NULL,
    type          VARCHAR(32)  NOT NULL,
    value         LONGBLOB     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_ap_checkpoint_write (thread_id, checkpoint_ns, checkpoint_id, task_id, idx),
    KEY idx_ap_checkpoint_write_thread (thread_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT 'LangGraph checkpoint 待写通道';
