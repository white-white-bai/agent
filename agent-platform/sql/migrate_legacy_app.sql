-- agent 中台迁移脚本：存量 ai_monitor_app / xb_ai_monitor_app → ap_tenant / ap_app（MySQL 8，人工执行）
-- 前置：先执行 sql/ddl.sql；app_id / api_key 沿用现有值，可重复执行（INSERT IGNORE 幂等）。
-- 区域口径：存量表按区域分表，故每张表对应一个 tenant_code，执行前按实际映射调整下方变量。

SET NAMES utf8mb4;

SET @tenant_code = 'changzhou';
SET @tenant_name = '常州';

INSERT IGNORE INTO ap_tenant (code, name, created_at)
VALUES (@tenant_code, @tenant_name, NOW());

INSERT IGNORE INTO ap_app (
    uuid, tenant_code, app_id, api_key, app_name, app_type, icon,
    opening_statement, suggested_questions, app_info, is_deleted, created_at, updated_at
)
SELECT
    REPLACE(UUID(), '-', ''),
    @tenant_code,
    src.app_id,
    IFNULL(src.api_key, ''),
    IFNULL(src.app_name, ''),
    IFNULL(NULLIF(src.app_type, ''), IFNULL(NULLIF(src.dify_app_type, ''), 'chat')),
    IFNULL(src.agent_picurl, ''),
    NULL,
    NULL,
    src.app_info,
    IFNULL(src.is_deleted, 0),
    IFNULL(src.create_time, NOW()),
    IFNULL(src.update_time, NOW())
FROM ai_monitor_app AS src
WHERE src.app_id IS NOT NULL AND src.app_id <> '';

SET @tenant_code = 'xinbei';
SET @tenant_name = '新北';

INSERT IGNORE INTO ap_tenant (code, name, created_at)
VALUES (@tenant_code, @tenant_name, NOW());

INSERT IGNORE INTO ap_app (
    uuid, tenant_code, app_id, api_key, app_name, app_type, icon,
    opening_statement, suggested_questions, app_info, is_deleted, created_at, updated_at
)
SELECT
    REPLACE(UUID(), '-', ''),
    @tenant_code,
    src.app_id,
    IFNULL(src.api_key, ''),
    IFNULL(src.app_name, ''),
    IFNULL(NULLIF(src.app_type, ''), IFNULL(NULLIF(src.dify_app_type, ''), 'chat')),
    IFNULL(src.agent_picurl, ''),
    NULL,
    NULL,
    src.app_info,
    IFNULL(src.is_deleted, 0),
    IFNULL(src.create_time, NOW()),
    IFNULL(src.update_time, NOW())
FROM xb_ai_monitor_app AS src
WHERE src.app_id IS NOT NULL AND src.app_id <> '';

SELECT tenant_code, COUNT(*) AS app_count, SUM(is_deleted = 0) AS active_count
FROM ap_app
GROUP BY tenant_code
ORDER BY tenant_code;
