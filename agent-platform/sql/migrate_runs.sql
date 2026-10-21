-- 老库新增管理端运行记录表；可重复执行。
-- 对应 src/agent_platform/domain/models.py 的 Run。
-- 新建库直接执行 ddl.sql 即可，无需本脚本。
SET NAMES utf8mb4;

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

DROP PROCEDURE IF EXISTS ap_add_run_subgraph_snapshot;
DELIMITER $$
CREATE PROCEDURE ap_add_run_subgraph_snapshot()
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ap_run' AND COLUMN_NAME = 'subgraph_snapshot'
    ) THEN
        ALTER TABLE ap_run ADD COLUMN subgraph_snapshot JSON NULL AFTER graph_definition;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ap_run' AND COLUMN_NAME = 'resolved_by'
    ) THEN
        ALTER TABLE ap_run ADD COLUMN resolved_by VARCHAR(64) NOT NULL DEFAULT '' AFTER created_by;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ap_run' AND COLUMN_NAME = 'resolved_at'
    ) THEN
        ALTER TABLE ap_run ADD COLUMN resolved_at DATETIME NULL AFTER resolved_by;
    END IF;
END$$
DELIMITER ;
CALL ap_add_run_subgraph_snapshot();
DROP PROCEDURE ap_add_run_subgraph_snapshot;
