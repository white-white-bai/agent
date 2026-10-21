-- HITL 外部审批回调幂等表：同一 (kind, thread_id, interrupt_id) 只允许一个决策。
-- 新建库直接执行 ddl.sql；老库执行本脚本，可重复执行。

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS ap_hitl_action (
    id           BIGINT       NOT NULL AUTO_INCREMENT,
    uuid         VARCHAR(64)  NOT NULL,
    kind         VARCHAR(16)  NOT NULL,
    thread_id    VARCHAR(128) NOT NULL,
    interrupt_id VARCHAR(128) NOT NULL,
    decision     VARCHAR(16)  NOT NULL,
    status       VARCHAR(16)  NOT NULL DEFAULT 'claimed',
    created_at   DATETIME     NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_ap_hitl_action_uuid (uuid),
    UNIQUE KEY uk_ap_hitl_action_interrupt (kind, thread_id, interrupt_id),
    KEY idx_ap_hitl_action_thread (thread_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT 'HITL 外部审批回调幂等记录';
