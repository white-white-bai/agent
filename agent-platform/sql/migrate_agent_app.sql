-- Agent 应用增量迁移：新增 ap_agent_app / ap_agent_app_version，ap_tool 增 description
-- 与 src/agent_platform/domain/models.py 的 AgentApp / AgentAppVersion / Tool 对应；可重复执行（存在即跳过）。
-- 新建库直接执行 ddl.sql 即可，无需本脚本。

SET NAMES utf8mb4;

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

-- MySQL 8 不支持 ADD COLUMN IF NOT EXISTS，用 information_schema 守卫
DROP PROCEDURE IF EXISTS ap_add_tool_description;
DELIMITER $$
CREATE PROCEDURE ap_add_tool_description()
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'ap_tool' AND COLUMN_NAME = 'description'
    ) THEN
        ALTER TABLE ap_tool ADD COLUMN description TEXT NULL AFTER label;
    END IF;
END$$
DELIMITER ;

CALL ap_add_tool_description();
DROP PROCEDURE ap_add_tool_description;
