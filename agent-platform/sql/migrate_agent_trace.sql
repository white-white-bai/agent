-- Agent 生产运行轨迹（AP_AGENT_TRACE_ENABLED=true 时写入）。
-- 新建库直接执行 ddl.sql；老库执行本脚本，可重复执行。

SET NAMES utf8mb4;

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
