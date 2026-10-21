-- HITL 外部审批回调幂等表：同一 (kind, thread_id, interrupt_id) 只允许一个决策。
-- 新建库直接执行 ddl.sql；老库执行本脚本，可重复执行。

SET NAMES utf8mb4;

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

DROP PROCEDURE IF EXISTS ap_add_hitl_action_tenant;
DELIMITER $$
CREATE PROCEDURE ap_add_hitl_action_tenant()
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ap_hitl_action' AND COLUMN_NAME = 'tenant_code'
    ) THEN
        ALTER TABLE ap_hitl_action
            ADD COLUMN tenant_code VARCHAR(64) NOT NULL DEFAULT '' AFTER uuid,
            ADD KEY idx_ap_hitl_action_tenant (tenant_code);
    END IF;
END$$
DELIMITER ;
CALL ap_add_hitl_action_tenant();
DROP PROCEDURE ap_add_hitl_action_tenant;
