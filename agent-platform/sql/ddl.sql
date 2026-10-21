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

CREATE TABLE IF NOT EXISTS ap_agent_app (
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
    UNIQUE KEY uk_ap_agent_app_uuid (uuid),
    UNIQUE KEY uk_ap_agent_app_app_uuid (app_uuid),
    KEY idx_ap_agent_app_tenant (tenant_code)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT 'Agent 应用配置（草稿，JSON document）';

CREATE TABLE IF NOT EXISTS ap_agent_app_version (
    id          BIGINT      NOT NULL AUTO_INCREMENT,
    uuid        VARCHAR(64) NOT NULL,
    agent_uuid  VARCHAR(64) NOT NULL,
    version     INT         NOT NULL,
    definition  JSON        NOT NULL,
    note        VARCHAR(512) NOT NULL DEFAULT '',
    created_by  VARCHAR(64) NOT NULL DEFAULT '',
    created_at  DATETIME    NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_ap_agent_app_version_uuid (uuid),
    UNIQUE KEY uk_ap_agent_app_version (agent_uuid, version)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT 'Agent 应用发布版本（不可变快照）';

CREATE TABLE IF NOT EXISTS ap_conversation (
    id              BIGINT       NOT NULL AUTO_INCREMENT,
    uuid            VARCHAR(64)  NOT NULL,
    tenant_code     VARCHAR(64)  NOT NULL,
    app_uuid        VARCHAR(64)  NOT NULL,
    conversation_id VARCHAR(64)  NOT NULL,
    user_id         VARCHAR(64)  NOT NULL DEFAULT '',
    user_name       VARCHAR(128) NOT NULL DEFAULT '',
    name            VARCHAR(255) NOT NULL DEFAULT '',
    summary         TEXT         NULL,
    summary_upto_id BIGINT       NOT NULL DEFAULT 0,
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
    metadata_type        VARCHAR(32)  NOT NULL DEFAULT 'json',
    metadata             LONGBLOB     NOT NULL,
    created_at           DATETIME     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_ap_checkpoint (thread_id, checkpoint_ns, checkpoint_id),
    KEY idx_ap_checkpoint_thread (thread_id),
    KEY idx_ap_checkpoint_thread_ns (thread_id, checkpoint_ns, id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT 'LangGraph checkpoint（自研 MySQL checkpointer）';

CREATE TABLE IF NOT EXISTS ap_checkpoint_write (
    id            BIGINT       NOT NULL AUTO_INCREMENT,
    thread_id     VARCHAR(128) NOT NULL,
    checkpoint_ns VARCHAR(128) NOT NULL DEFAULT '',
    checkpoint_id VARCHAR(128) NOT NULL,
    task_id       VARCHAR(128) NOT NULL,
    task_path     VARCHAR(128) NOT NULL DEFAULT '',
    idx           INT          NOT NULL,
    channel       VARCHAR(128) NOT NULL,
    type          VARCHAR(32)  NOT NULL,
    value         LONGBLOB     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_ap_checkpoint_write (thread_id, checkpoint_ns, checkpoint_id, task_id, idx),
    KEY idx_ap_checkpoint_write_thread (thread_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT 'LangGraph checkpoint 待写通道';

CREATE TABLE IF NOT EXISTS ap_dataset (
    id              BIGINT       NOT NULL AUTO_INCREMENT,
    uuid            VARCHAR(64)  NOT NULL,
    tenant_code     VARCHAR(64)  NOT NULL DEFAULT '',
    name            VARCHAR(128) NOT NULL DEFAULT '',
    description     TEXT         NULL,
    embedding_model VARCHAR(64)  NOT NULL DEFAULT '',
    index_method    VARCHAR(16)  NOT NULL DEFAULT 'high_quality',
    chunk_config    JSON         NULL,
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
    chunk_config JSON        NULL,
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

CREATE TABLE IF NOT EXISTS ap_mcp_server (
    id          BIGINT       NOT NULL AUTO_INCREMENT,
    uuid        VARCHAR(64)  NOT NULL,
    tenant_code VARCHAR(64)  NOT NULL DEFAULT '',
    name        VARCHAR(64)  NOT NULL,
    kind        VARCHAR(16)  NOT NULL DEFAULT 'mcp',
    url         VARCHAR(512) NOT NULL DEFAULT '',
    headers     JSON         NULL,
    is_deleted  INT          NOT NULL DEFAULT 0,
    created_at  DATETIME     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_ap_mcp_server_uuid (uuid),
    KEY idx_ap_mcp_server_name (tenant_code, name)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT 'MCP Server 注册表';

CREATE TABLE IF NOT EXISTS ap_admin_role (
    id          BIGINT       NOT NULL AUTO_INCREMENT,
    code        VARCHAR(64)  NOT NULL,
    name        VARCHAR(128) NOT NULL DEFAULT '',
    permissions JSON         NULL,
    is_builtin  INT          NOT NULL DEFAULT 0,
    created_at  DATETIME     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_ap_admin_role_code (code)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '中台管理端角色';

CREATE TABLE IF NOT EXISTS ap_admin_user (
    id            BIGINT       NOT NULL AUTO_INCREMENT,
    uuid          VARCHAR(64)  NOT NULL,
    username      VARCHAR(64)  NOT NULL,
    password_hash VARCHAR(128) NOT NULL,
    salt          VARCHAR(64)  NOT NULL,
    display_name  VARCHAR(128) NOT NULL DEFAULT '',
    role_code     VARCHAR(64)  NOT NULL DEFAULT 'viewer',
    tenant_code   VARCHAR(64)  NOT NULL DEFAULT '',
    is_active     INT          NOT NULL DEFAULT 1,
    last_login_at DATETIME     NULL,
    created_at    DATETIME     NOT NULL,
    updated_at    DATETIME     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_ap_admin_user_uuid (uuid),
    UNIQUE KEY uk_ap_admin_user_username (username),
    KEY idx_ap_admin_user_role (role_code),
    KEY idx_ap_admin_user_tenant (tenant_code)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '中台管理端账号';

CREATE TABLE IF NOT EXISTS ap_metric_event (
    id          BIGINT       NOT NULL AUTO_INCREMENT,
    tenant_code VARCHAR(64)  NOT NULL DEFAULT '',
    app_uuid    VARCHAR(64)  NOT NULL DEFAULT '',
    kind        VARCHAR(32)  NOT NULL DEFAULT 'error',
    detail      VARCHAR(512) NOT NULL DEFAULT '',
    created_at  DATETIME     NOT NULL,
    PRIMARY KEY (id),
    KEY idx_ap_metric_event_scope (tenant_code, app_uuid, kind, created_at)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '中台指标事件（错误率等，监控看板汇总用）';

CREATE TABLE IF NOT EXISTS ap_tool (
    id                    BIGINT       NOT NULL AUTO_INCREMENT,
    uuid                  VARCHAR(64)  NOT NULL,
    tenant_code           VARCHAR(64)  NOT NULL DEFAULT '',
    name                  VARCHAR(128) NOT NULL,
    label                 VARCHAR(128) NOT NULL DEFAULT '',
    description           TEXT         NULL,
    category              VARCHAR(32)  NOT NULL DEFAULT '',
    server                VARCHAR(64)  NOT NULL DEFAULT '',
    kind                  VARCHAR(16)  NOT NULL DEFAULT 'http',
    http_method           VARCHAR(8)   NOT NULL DEFAULT 'POST',
    http_path             VARCHAR(512) NOT NULL DEFAULT '',
    params                JSON         NULL,
    retry_attempts        INT          NULL,
    retry_backoff_seconds FLOAT        NULL,
    fallback              JSON         NULL,
    is_builtin            INT          NOT NULL DEFAULT 0,
    is_deleted            INT          NOT NULL DEFAULT 0,
    created_at            DATETIME     NOT NULL,
    updated_at            DATETIME     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_ap_tool_uuid (uuid),
    UNIQUE KEY uk_ap_tool_name (name),
    KEY idx_ap_tool_tenant (tenant_code)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '生产级工具声明（参数 schema + 端点 + 重试/兜底）';

CREATE TABLE IF NOT EXISTS ap_prompt_template (
    id            BIGINT       NOT NULL AUTO_INCREMENT,
    uuid          VARCHAR(64)  NOT NULL,
    tenant_code   VARCHAR(64)  NOT NULL DEFAULT '',
    code          VARCHAR(64)  NOT NULL,
    label         VARCHAR(128) NOT NULL DEFAULT '',
    system_prompt TEXT         NULL,
    examples      JSON         NULL,
    cot_hint      TEXT         NULL,
    is_builtin    INT          NOT NULL DEFAULT 0,
    is_deleted    INT          NOT NULL DEFAULT 0,
    created_at    DATETIME     NOT NULL,
    updated_at    DATETIME     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_ap_prompt_template_uuid (uuid),
    UNIQUE KEY uk_ap_prompt_template_code (code),
    KEY idx_ap_prompt_template_tenant (tenant_code)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '少样本提示词模板';

CREATE TABLE IF NOT EXISTS ap_agent (
    id                BIGINT       NOT NULL AUTO_INCREMENT,
    uuid              VARCHAR(64)  NOT NULL,
    tenant_code       VARCHAR(64)  NOT NULL DEFAULT '',
    code              VARCHAR(64)  NOT NULL,
    label             VARCHAR(128) NOT NULL DEFAULT '',
    role              VARCHAR(32)  NOT NULL DEFAULT 'custom',
    mode              VARCHAR(32)  NOT NULL DEFAULT 'react',
    provider          VARCHAR(64)  NOT NULL DEFAULT '',
    system_prompt     TEXT         NULL,
    prompt_template   VARCHAR(64)  NOT NULL DEFAULT '',
    cot               INT          NOT NULL DEFAULT 0,
    tools             JSON         NULL,
    retriever         JSON         NULL,
    pipeline          JSON         NULL,
    max_steps         INT          NOT NULL DEFAULT 6,
    reflection_rounds INT          NOT NULL DEFAULT 2,
    temperature       FLOAT        NOT NULL DEFAULT 0.3,
    max_tokens        INT          NULL,
    is_builtin        INT          NOT NULL DEFAULT 0,
    is_deleted        INT          NOT NULL DEFAULT 0,
    created_at        DATETIME     NOT NULL,
    updated_at        DATETIME     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_ap_agent_uuid (uuid),
    UNIQUE KEY uk_ap_agent_code (code),
    KEY idx_ap_agent_tenant (tenant_code)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '智能体定义（角色 / 工作模式 / 工具 / 提示词）';

CREATE TABLE IF NOT EXISTS ap_run (
    id                BIGINT       NOT NULL AUTO_INCREMENT,
    uuid              VARCHAR(64)  NOT NULL,
    tenant_code       VARCHAR(64)  NOT NULL DEFAULT '',
    app_uuid          VARCHAR(64)  NOT NULL DEFAULT '',
    thread_id         VARCHAR(128) NOT NULL,
    status            VARCHAR(16)  NOT NULL DEFAULT 'running',
    graph_definition  JSON         NULL,
    subgraph_snapshot JSON         NULL,
    interrupt_payload JSON         NULL,
    created_by        VARCHAR(64)  NOT NULL DEFAULT '',
    resolved_by       VARCHAR(64)  NOT NULL DEFAULT '',
    resolved_at       DATETIME     NULL,
    created_at        DATETIME     NOT NULL,
    updated_at        DATETIME     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_ap_run_uuid (uuid),
    UNIQUE KEY uk_ap_run_thread (thread_id),
    KEY idx_ap_run_status (status),
    KEY idx_ap_run_app (app_uuid)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '管理端图运行记录（HITL 中断/恢复）';

CREATE TABLE IF NOT EXISTS ap_agent_trace (
    id          BIGINT       NOT NULL AUTO_INCREMENT,
    uuid        VARCHAR(64)  NOT NULL,
    tenant_code VARCHAR(64)  NOT NULL DEFAULT '',
    app_uuid    VARCHAR(64)  NOT NULL DEFAULT '',
    thread_id   VARCHAR(128) NOT NULL DEFAULT '',
    query       TEXT         NULL,
    tool_calls  JSON         NULL,
    tool_events JSON         NULL,
    answer      TEXT         NULL,
    status      VARCHAR(16)  NOT NULL DEFAULT 'completed',
    duration_ms INT          NOT NULL DEFAULT 0,
    token_chars INT          NOT NULL DEFAULT 0,
    created_at  DATETIME     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_ap_agent_trace_uuid (uuid),
    KEY idx_ap_agent_trace_tenant (tenant_code),
    KEY idx_ap_agent_trace_app (app_uuid),
    KEY idx_ap_agent_trace_thread (thread_id),
    KEY idx_ap_agent_trace_status (status)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT 'Agent 生产运行轨迹';

CREATE TABLE IF NOT EXISTS ap_tool_audit (
    id           BIGINT       NOT NULL AUTO_INCREMENT,
    uuid         VARCHAR(64)  NOT NULL,
    tenant_code  VARCHAR(64)  NOT NULL DEFAULT '',
    tool_name    VARCHAR(128) NOT NULL,
    server       VARCHAR(64)  NOT NULL DEFAULT '',
    args         JSON         NULL,
    status       VARCHAR(16)  NOT NULL DEFAULT 'ok',
    error        TEXT         NULL,
    duration_ms  INT          NOT NULL DEFAULT 0,
    created_at   DATETIME     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_ap_tool_audit_uuid (uuid),
    KEY idx_ap_tool_audit_tenant (tenant_code),
    KEY idx_ap_tool_audit_name (tool_name),
    KEY idx_ap_tool_audit_status (status)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '工具调用审计';

CREATE TABLE IF NOT EXISTS ap_hitl_outbox (
    id            BIGINT       NOT NULL AUTO_INCREMENT,
    uuid          VARCHAR(64)  NOT NULL,
    event         VARCHAR(32)  NOT NULL,
    payload       JSON         NULL,
    status        VARCHAR(16)  NOT NULL DEFAULT 'pending',
    attempts      INT          NOT NULL DEFAULT 0,
    next_retry_at DATETIME     NULL,
    last_error    TEXT         NULL,
    created_at    DATETIME     NOT NULL,
    updated_at    DATETIME     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_ap_hitl_outbox_uuid (uuid),
    KEY idx_ap_hitl_outbox_status (status, next_retry_at),
    KEY idx_ap_hitl_outbox_event (event)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT 'HITL 外部通知 outbox';

CREATE TABLE IF NOT EXISTS ap_hitl_action (
    id           BIGINT       NOT NULL AUTO_INCREMENT,
    uuid         VARCHAR(64)  NOT NULL,
    tenant_code  VARCHAR(64)  NOT NULL DEFAULT '',
    kind         VARCHAR(16)  NOT NULL,
    thread_id    VARCHAR(128) NOT NULL,
    interrupt_id VARCHAR(128) NOT NULL,
    decision     VARCHAR(16)  NOT NULL,
    status       VARCHAR(16)  NOT NULL DEFAULT 'claimed',
    created_at   DATETIME     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_ap_hitl_action_uuid (uuid),
    UNIQUE KEY uk_ap_hitl_action_interrupt (kind, thread_id, interrupt_id),
    KEY idx_ap_hitl_action_thread (thread_id),
    KEY idx_ap_hitl_action_tenant (tenant_code)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT 'HITL 外部审批回调幂等记录';

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
