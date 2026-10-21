-- HITL 外部通知 outbox（AP_HITL_OUTBOX_ENABLED=true 时使用）。
-- 新建库直接执行 ddl.sql；老库执行本脚本，可重复执行。

SET NAMES utf8mb4;

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
