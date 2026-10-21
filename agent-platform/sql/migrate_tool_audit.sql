-- 工具调用审计（默认关闭，AP_TOOL_AUDIT_ENABLED=true 时写入）。
-- 新建库直接执行 ddl.sql；老库执行本脚本，可重复执行。

SET NAMES utf8mb4;

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
