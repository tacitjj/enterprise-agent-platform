\set ON_ERROR_STOP on

BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SET CONSTRAINTS ALL DEFERRED;

INSERT INTO dianlian_business.tenant
    (tenant_id, display_name, status, permission_version, created_at, updated_at)
VALUES
    ('10000000-0000-4000-8000-000000000001', '点联本地样板企业', 'ACTIVE', 1,
     '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
ON CONFLICT (tenant_id) DO UPDATE
SET display_name = EXCLUDED.display_name,
    status = 'ACTIVE',
    updated_at = CURRENT_TIMESTAMP;

INSERT INTO dianlian_business.user_account
    (user_id, display_name, avatar_url, status, permission_version, created_at, updated_at)
VALUES
    ('10000000-0000-4000-8000-000000000010', '点联平台运营员', NULL, 'ACTIVE', 1,
     '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'),
    ('10000000-0000-4000-8000-000000000011', '点联企业体验员', NULL, 'ACTIVE', 1,
     '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
ON CONFLICT (user_id) DO UPDATE
SET display_name = EXCLUDED.display_name,
    status = 'ACTIVE',
    updated_at = CURRENT_TIMESTAMP;

INSERT INTO dianlian_business.tenant_member
    (member_id, tenant_id, user_id, status, permission_version, joined_at, expires_at, ended_at, updated_at)
VALUES
    ('10000000-0000-4000-8000-000000000020',
     '10000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000011',
     'ACTIVE', 1, '2026-01-01T00:00:00Z', NULL, NULL, CURRENT_TIMESTAMP)
ON CONFLICT (member_id) DO UPDATE
SET status = 'ACTIVE',
    expires_at = NULL,
    ended_at = NULL,
    updated_at = CURRENT_TIMESTAMP;

INSERT INTO dianlian_business.iam_role (role_code, display_name, status)
VALUES
    ('LOCAL_PLATFORM_OPERATOR', '本地平台运营员', 'ACTIVE'),
    ('LOCAL_ENTERPRISE_OPERATOR', '本地企业操作员', 'ACTIVE')
ON CONFLICT (role_code) DO UPDATE
SET display_name = EXCLUDED.display_name,
    status = 'ACTIVE',
    updated_at = CURRENT_TIMESTAMP;

INSERT INTO dianlian_business.role_permission (role_code, permission_code)
VALUES
    ('LOCAL_PLATFORM_OPERATOR', 'platform.employee.template.read'),
    ('LOCAL_PLATFORM_OPERATOR', 'platform.employee.template.publish'),
    ('LOCAL_PLATFORM_OPERATOR', 'platform.model.read'),
    ('LOCAL_PLATFORM_OPERATOR', 'platform.model.manage'),
    ('LOCAL_PLATFORM_OPERATOR', 'platform.knowledge.read'),
    ('LOCAL_PLATFORM_OPERATOR', 'platform.knowledge.manage'),
    ('LOCAL_ENTERPRISE_OPERATOR', 'enterprise.employee.hire'),
    ('LOCAL_ENTERPRISE_OPERATOR', 'enterprise.employee.read'),
    ('LOCAL_ENTERPRISE_OPERATOR', 'enterprise.employee.configure'),
    ('LOCAL_ENTERPRISE_OPERATOR', 'enterprise.employee.activate'),
    ('LOCAL_ENTERPRISE_OPERATOR', 'enterprise.employee.execute'),
    ('LOCAL_ENTERPRISE_OPERATOR', 'enterprise.employee.model.configure'),
    ('LOCAL_ENTERPRISE_OPERATOR', 'conversation.read'),
    ('LOCAL_ENTERPRISE_OPERATOR', 'conversation.create'),
    ('LOCAL_ENTERPRISE_OPERATOR', 'conversation.message.send'),
    ('LOCAL_ENTERPRISE_OPERATOR', 'conversation.agent.invoke'),
    ('LOCAL_ENTERPRISE_OPERATOR', 'task.create'),
    ('LOCAL_ENTERPRISE_OPERATOR', 'task.read'),
    ('LOCAL_ENTERPRISE_OPERATOR', 'enterprise.knowledge.read'),
    ('LOCAL_ENTERPRISE_OPERATOR', 'enterprise.knowledge.manage'),
    ('LOCAL_ENTERPRISE_OPERATOR', 'memory.candidate.propose'),
    ('LOCAL_ENTERPRISE_OPERATOR', 'memory.recall'),
    ('LOCAL_ENTERPRISE_OPERATOR', 'memory.self.manage'),
    ('LOCAL_ENTERPRISE_OPERATOR', 'memory.group.manage'),
    ('LOCAL_ENTERPRISE_OPERATOR', 'enterprise.memory.govern')
ON CONFLICT (role_code, permission_code) DO NOTHING;

INSERT INTO dianlian_business.role_grant
    (grant_id, subject_user_id, tenant_id, tenant_member_id, role_code, scope_type,
     scope_id, granted_at, expires_at, revoked_at, updated_at)
VALUES
    ('10000000-0000-4000-8000-000000000030',
     '10000000-0000-4000-8000-000000000010',
     NULL, NULL, 'LOCAL_PLATFORM_OPERATOR', 'PLATFORM',
     '10000000-0000-4000-8000-000000000000',
     '2026-01-01T00:00:00Z', NULL, NULL, CURRENT_TIMESTAMP),
    ('10000000-0000-4000-8000-000000000031',
     '10000000-0000-4000-8000-000000000011',
     '10000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000020',
     'LOCAL_ENTERPRISE_OPERATOR', 'TENANT',
     '10000000-0000-4000-8000-000000000001',
     '2026-01-01T00:00:00Z', NULL, NULL, CURRENT_TIMESTAMP)
ON CONFLICT (grant_id) DO UPDATE
SET expires_at = NULL,
    revoked_at = NULL,
    updated_at = CURRENT_TIMESTAMP;

INSERT INTO dianlian_business.user_login_identifier
    (login_identifier_id, user_id, identifier_type, normalized_identifier, status,
     verified_at, created_at, updated_at)
VALUES
    ('10000000-0000-4000-8000-000000000040',
     '10000000-0000-4000-8000-000000000010',
     'USERNAME', LOWER(:'dianlian_local_platform_username'), 'ACTIVE',
     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('10000000-0000-4000-8000-000000000041',
     '10000000-0000-4000-8000-000000000011',
     'USERNAME', LOWER(:'dianlian_local_username'), 'ACTIVE',
     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT (login_identifier_id) DO UPDATE
SET user_id = EXCLUDED.user_id,
    identifier_type = EXCLUDED.identifier_type,
    normalized_identifier = EXCLUDED.normalized_identifier,
    status = 'ACTIVE',
    updated_at = CURRENT_TIMESTAMP;

INSERT INTO dianlian_business.password_credential
    (user_id, password_hash, password_algorithm, failed_attempt_count, locked_until,
     password_changed_at, version, created_at, updated_at)
VALUES
    ('10000000-0000-4000-8000-000000000010',
     :'dianlian_local_platform_password_hash', 'BCRYPT', 0, NULL,
     CURRENT_TIMESTAMP, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('10000000-0000-4000-8000-000000000011',
     :'dianlian_local_password_hash', 'BCRYPT', 0, NULL,
     CURRENT_TIMESTAMP, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT (user_id) DO UPDATE
SET password_hash = EXCLUDED.password_hash,
    password_algorithm = 'BCRYPT',
    failed_attempt_count = 0,
    locked_until = NULL,
    password_changed_at = CASE
        WHEN dianlian_business.password_credential.password_hash IS DISTINCT FROM EXCLUDED.password_hash
          OR dianlian_business.password_credential.password_algorithm IS DISTINCT FROM EXCLUDED.password_algorithm
        THEN CURRENT_TIMESTAMP
        ELSE dianlian_business.password_credential.password_changed_at
    END,
    version = dianlian_business.password_credential.version + CASE
        WHEN dianlian_business.password_credential.password_hash IS DISTINCT FROM EXCLUDED.password_hash
          OR dianlian_business.password_credential.password_algorithm IS DISTINCT FROM EXCLUDED.password_algorithm
        THEN 1
        ELSE 0
    END,
    updated_at = CURRENT_TIMESTAMP
WHERE dianlian_business.password_credential.password_hash IS DISTINCT FROM EXCLUDED.password_hash
   OR dianlian_business.password_credential.password_algorithm IS DISTINCT FROM EXCLUDED.password_algorithm
   OR dianlian_business.password_credential.failed_attempt_count <> 0
   OR dianlian_business.password_credential.locked_until IS NOT NULL;

INSERT INTO dianlian_business.agent_template
    (agent_template_id, owner_scope, template_code, status, created_by, created_at, updated_at)
VALUES
    ('10000000-0000-4000-8000-000000000101', 'PLATFORM', 'graphic-design-specialist', 'ACTIVE',
     '10000000-0000-4000-8000-000000000010', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'),
    ('10000000-0000-4000-8000-000000000102', 'PLATFORM', 'contract-review-specialist', 'ACTIVE',
     '10000000-0000-4000-8000-000000000010', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'),
    ('10000000-0000-4000-8000-000000000103', 'PLATFORM', 'quotation-specialist', 'ACTIVE',
     '10000000-0000-4000-8000-000000000010', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
ON CONFLICT (agent_template_id) DO UPDATE
SET status = 'ACTIVE',
    updated_at = CURRENT_TIMESTAMP;

INSERT INTO dianlian_business.agent_version
    (agent_version_id, owner_scope, agent_template_id, template_name, template_description,
     version_label, capability_code, input_schema, execution_template, point_estimate,
     status, visibility_mode, visible_tenant_ids, request_hash, publish_idempotency_key,
     published_by, published_at, created_at, updated_at)
VALUES
    (
        '10000000-0000-4000-8000-000000000111', 'PLATFORM',
        '10000000-0000-4000-8000-000000000101',
        '平面设计专员', '根据文字需求与参考素材生成平面视觉方案，并在交付前设置人工确认。',
        '1.0.0', 'GRAPHIC_DESIGN',
        '{"schemaId":"graphic_design.request","version":"1.0.0","schema":{"type":"object","properties":{"brief":{"type":"string","minLength":1,"maxLength":5000},"referenceImageUrls":{"type":"array","items":{"type":"string"}},"outputFormat":{"type":"string","enum":["PNG","JPG","PDF"]}},"required":["brief"],"additionalProperties":false}}'::jsonb,
        '{"templateCode":"graphic-design.v1","version":"1.0.0","steps":[{"stepKey":"understand","title":"理解设计需求","executorType":"MODEL","dependsOn":[],"inputSchemaRef":"graphic_design.request","outputSchemaRef":"graphic_design.brief","humanCheckpoint":false},{"stepKey":"generate","title":"生成视觉草案","executorType":"TOOL","dependsOn":["understand"],"inputSchemaRef":"graphic_design.brief","outputSchemaRef":"graphic_design.draft","humanCheckpoint":false},{"stepKey":"review","title":"确认交付版本","executorType":"HUMAN_CHECKPOINT","dependsOn":["generate"],"inputSchemaRef":"graphic_design.draft","outputSchemaRef":"graphic_design.approved","humanCheckpoint":true}]}'::jsonb,
        600000000, 'PUBLISHED', 'ALLOWLIST',
        '["10000000-0000-4000-8000-000000000001"]'::jsonb,
        'local-seed:graphic-design:1.0.0', 'local-seed:publish:graphic-design:1.0.0',
        '10000000-0000-4000-8000-000000000010',
        '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'
    ),
    (
        '10000000-0000-4000-8000-000000000112', 'PLATFORM',
        '10000000-0000-4000-8000-000000000102',
        '法务合同审核专员', '识别合同条款、风险与缺失信息，输出带依据的审查意见并交由人员确认。',
        '1.0.0', 'CONTRACT_REVIEW',
        '{"schemaId":"contract_review.request","version":"1.0.0","schema":{"type":"object","properties":{"contractText":{"type":"string","minLength":1,"maxLength":200000},"reviewFocus":{"type":"array","items":{"type":"string"}}},"required":["contractText"],"additionalProperties":false}}'::jsonb,
        '{"templateCode":"contract-review.v1","version":"1.0.0","steps":[{"stepKey":"extract","title":"提取合同结构","executorType":"TOOL","dependsOn":[],"inputSchemaRef":"contract_review.request","outputSchemaRef":"contract_review.structure","humanCheckpoint":false},{"stepKey":"analyze","title":"分析条款风险","executorType":"RETRIEVAL","dependsOn":["extract"],"inputSchemaRef":"contract_review.structure","outputSchemaRef":"contract_review.findings","humanCheckpoint":false},{"stepKey":"review","title":"确认审查意见","executorType":"HUMAN_CHECKPOINT","dependsOn":["analyze"],"inputSchemaRef":"contract_review.findings","outputSchemaRef":"contract_review.approved","humanCheckpoint":true}]}'::jsonb,
        450000000, 'PUBLISHED', 'ALLOWLIST',
        '["10000000-0000-4000-8000-000000000001"]'::jsonb,
        'local-seed:contract-review:1.0.0', 'local-seed:publish:contract-review:1.0.0',
        '10000000-0000-4000-8000-000000000010',
        '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'
    ),
    (
        '10000000-0000-4000-8000-000000000113', 'PLATFORM',
        '10000000-0000-4000-8000-000000000103',
        '报价专员', '依据需求、知识依据与确定性计算规则生成可复核的报价成果。',
        '1.0.0', 'QUOTATION',
        '{"schemaId":"quotation.request","version":"1.0.0","schema":{"type":"object","properties":{"requirements":{"type":"string","minLength":1,"maxLength":10000},"currency":{"type":"string","enum":["CNY","USD"]}},"required":["requirements"],"additionalProperties":false}}'::jsonb,
        '{"templateCode":"quotation.v1","version":"1.0.0","steps":[{"stepKey":"understand","title":"理解报价需求","executorType":"MODEL","dependsOn":[],"inputSchemaRef":"quotation.request","outputSchemaRef":"quotation.normalized","humanCheckpoint":false},{"stepKey":"calculate","title":"计算报价方案","executorType":"RULE_ENGINE","dependsOn":["understand"],"inputSchemaRef":"quotation.normalized","outputSchemaRef":"quotation.draft","humanCheckpoint":false},{"stepKey":"review","title":"确认报价结果","executorType":"HUMAN_CHECKPOINT","dependsOn":["calculate"],"inputSchemaRef":"quotation.draft","outputSchemaRef":"quotation.approved","humanCheckpoint":true}]}'::jsonb,
        350000000, 'PUBLISHED', 'ALLOWLIST',
        '["10000000-0000-4000-8000-000000000001"]'::jsonb,
        'local-seed:quotation:1.0.0', 'local-seed:publish:quotation:1.0.0',
        '10000000-0000-4000-8000-000000000010',
        '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'
    )
ON CONFLICT (agent_version_id) DO NOTHING;

INSERT INTO dianlian_business.enterprise_agent
    (enterprise_agent_id, tenant_id, agent_template_id, agent_version_id,
     employee_code, display_name, status, request_hash, hire_idempotency_key,
     hired_by, hired_at, created_at, updated_at)
VALUES
    ('10000000-0000-4000-8000-000000000121',
     '10000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000101',
     '10000000-0000-4000-8000-000000000111',
     'DL-GRAPHIC-001', '小绘', 'DRAFT',
     'local-seed:hire:graphic-design:1.0.0', 'local-seed:hire:graphic-design:1.0.0',
     '10000000-0000-4000-8000-000000000011',
     '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'),
    ('10000000-0000-4000-8000-000000000122',
     '10000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000102',
     '10000000-0000-4000-8000-000000000112',
     'DL-LEGAL-001', '小法', 'DRAFT',
     'local-seed:hire:contract-review:1.0.0', 'local-seed:hire:contract-review:1.0.0',
     '10000000-0000-4000-8000-000000000011',
     '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'),
    ('10000000-0000-4000-8000-000000000123',
     '10000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000103',
     '10000000-0000-4000-8000-000000000113',
     'DL-QUOTE-001', '小价', 'DRAFT',
     'local-seed:hire:quotation:1.0.0', 'local-seed:hire:quotation:1.0.0',
     '10000000-0000-4000-8000-000000000011',
     '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
ON CONFLICT (enterprise_agent_id) DO NOTHING;

INSERT INTO dianlian_business.enterprise_agent_configuration_version
    (configuration_version_id, tenant_id, enterprise_agent_id, revision,
     display_name_snapshot, profile, enterprise_instructions,
     model_policy_mode, knowledge_scope_mode, visibility_scope, status,
     create_request_hash, create_idempotency_key, created_by, created_at,
     create_result_state_version, updated_at)
VALUES
    ('10000000-0000-4000-8000-000000000131',
     '10000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000121', 1,
     '小绘', '根据文字需求与参考素材生成平面视觉方案，并在交付前设置人工确认。',
     '遵循当前企业已确认的品牌规范与素材授权范围；生成方案前先确认用途、尺寸和交付格式，最终成果需人工确认。',
     'PLATFORM_DEFAULT', 'NONE', 'TENANT', 'DRAFT',
     'local-seed:configure:graphic-design:1.0.0',
     'local-seed:configure:graphic-design:1.0.0',
     '10000000-0000-4000-8000-000000000011',
     '2026-01-01T00:00:00Z', 1, '2026-01-01T00:00:00Z'),
    ('10000000-0000-4000-8000-000000000132',
     '10000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000122', 1,
     '小法', '识别合同条款、风险与缺失信息，输出带依据的审查意见并交由人员确认。',
     '仅依据当前企业已授权的合同文本、条款库和审查规则给出风险意见；不替代律师判断，最终意见需人工确认。',
     'PLATFORM_DEFAULT', 'NONE', 'TENANT', 'DRAFT',
     'local-seed:configure:contract-review:1.0.0',
     'local-seed:configure:contract-review:1.0.0',
     '10000000-0000-4000-8000-000000000011',
     '2026-01-01T00:00:00Z', 1, '2026-01-01T00:00:00Z'),
    ('10000000-0000-4000-8000-000000000133',
     '10000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000123', 1,
     '小价', '依据需求、知识依据与确定性计算规则生成可复核的报价成果。',
     '优先使用当前企业已授权的项目资料、成本规则和历史案例；列明依据与假设，最终报价需人工确认。',
     'PLATFORM_DEFAULT', 'NONE', 'TENANT', 'DRAFT',
     'local-seed:configure:quotation:1.0.0',
     'local-seed:configure:quotation:1.0.0',
     '10000000-0000-4000-8000-000000000011',
     '2026-01-01T00:00:00Z', 1, '2026-01-01T00:00:00Z')
ON CONFLICT DO NOTHING;

-- Configuration creation is a first-class employee mutation and advances the ETag once.
UPDATE dianlian_business.enterprise_agent agent
   SET state_version = 1,
       updated_at = '2026-01-01T00:00:00Z'
  FROM (VALUES
      ('10000000-0000-4000-8000-000000000121'::UUID,
       '10000000-0000-4000-8000-000000000131'::UUID),
      ('10000000-0000-4000-8000-000000000122'::UUID,
       '10000000-0000-4000-8000-000000000132'::UUID),
      ('10000000-0000-4000-8000-000000000123'::UUID,
       '10000000-0000-4000-8000-000000000133'::UUID)
  ) expected(enterprise_agent_id, configuration_version_id)
 WHERE agent.enterprise_agent_id = expected.enterprise_agent_id
   AND agent.tenant_id = '10000000-0000-4000-8000-000000000001'
   AND agent.status = 'DRAFT'
   AND agent.state_version = 0
   AND agent.active_configuration_version_id IS NULL
   AND EXISTS (
       SELECT 1
         FROM dianlian_business.enterprise_agent_configuration_version configuration
        WHERE configuration.configuration_version_id = expected.configuration_version_id
          AND configuration.tenant_id = agent.tenant_id
          AND configuration.enterprise_agent_id = agent.enterprise_agent_id
          AND configuration.status = 'DRAFT'
          AND configuration.create_result_state_version = 1
   );

UPDATE dianlian_business.enterprise_agent_configuration_version configuration
   SET status = 'ACTIVE',
       activation_request_hash = CASE configuration.configuration_version_id
           WHEN '10000000-0000-4000-8000-000000000131'::UUID
               THEN 'local-seed:activate:graphic-design:1.0.0'
           WHEN '10000000-0000-4000-8000-000000000132'::UUID
               THEN 'local-seed:activate:contract-review:1.0.0'
           ELSE 'local-seed:activate:quotation:1.0.0'
       END,
       activation_idempotency_key = CASE configuration.configuration_version_id
           WHEN '10000000-0000-4000-8000-000000000131'::UUID
               THEN 'local-seed:activate:graphic-design:1.0.0'
           WHEN '10000000-0000-4000-8000-000000000132'::UUID
               THEN 'local-seed:activate:contract-review:1.0.0'
           ELSE 'local-seed:activate:quotation:1.0.0'
       END,
       activated_by = '10000000-0000-4000-8000-000000000011',
       activated_at = '2026-01-01T00:00:00Z',
       activation_result_state_version = 2,
       updated_at = '2026-01-01T00:00:00Z'
 WHERE configuration.configuration_version_id IN (
       '10000000-0000-4000-8000-000000000131',
       '10000000-0000-4000-8000-000000000132',
       '10000000-0000-4000-8000-000000000133'
   )
   AND configuration.tenant_id = '10000000-0000-4000-8000-000000000001'
   AND configuration.status = 'DRAFT'
   AND EXISTS (
       SELECT 1
         FROM dianlian_business.enterprise_agent agent
        WHERE agent.tenant_id = configuration.tenant_id
          AND agent.enterprise_agent_id = configuration.enterprise_agent_id
          AND agent.status = 'DRAFT'
          AND agent.state_version = 1
          AND agent.active_configuration_version_id IS NULL
   );

-- Activation binds one immutable configuration and advances the ETag a second time.
UPDATE dianlian_business.enterprise_agent agent
   SET status = 'ACTIVE',
       active_configuration_version_id = expected.configuration_version_id,
       activated_by = '10000000-0000-4000-8000-000000000011',
       activated_at = '2026-01-01T00:00:00Z',
       state_version = 2,
       updated_at = '2026-01-01T00:00:00Z'
  FROM (VALUES
      ('10000000-0000-4000-8000-000000000121'::UUID,
       '10000000-0000-4000-8000-000000000131'::UUID),
      ('10000000-0000-4000-8000-000000000122'::UUID,
       '10000000-0000-4000-8000-000000000132'::UUID),
      ('10000000-0000-4000-8000-000000000123'::UUID,
       '10000000-0000-4000-8000-000000000133'::UUID)
  ) expected(enterprise_agent_id, configuration_version_id)
 WHERE agent.enterprise_agent_id = expected.enterprise_agent_id
   AND agent.tenant_id = '10000000-0000-4000-8000-000000000001'
   AND agent.status = 'DRAFT'
   AND agent.state_version = 1
   AND agent.active_configuration_version_id IS NULL
   AND EXISTS (
       SELECT 1
         FROM dianlian_business.enterprise_agent_configuration_version configuration
        WHERE configuration.configuration_version_id = expected.configuration_version_id
          AND configuration.tenant_id = agent.tenant_id
          AND configuration.enterprise_agent_id = agent.enterprise_agent_id
          AND configuration.status = 'ACTIVE'
          AND configuration.activation_result_state_version = 2
   );

INSERT INTO dianlian_business.enterprise_agent_state_event
    (event_id, tenant_id, enterprise_agent_id, state_version, event_type,
     from_status, to_status, configuration_version_id, request_hash,
     idempotency_key, actor_id, occurred_at)
VALUES
    ('10000000-0000-4000-8000-000000000141',
     '10000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000121', 0, 'HIRED',
     NULL, 'DRAFT', NULL,
     'local-seed:hire:graphic-design:1.0.0',
     'local-seed:hire:graphic-design:1.0.0',
     '10000000-0000-4000-8000-000000000011', '2026-01-01T00:00:00Z'),
    ('10000000-0000-4000-8000-000000000142',
     '10000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000121', 1, 'CONFIGURATION_CREATED',
     'DRAFT', 'DRAFT', '10000000-0000-4000-8000-000000000131',
     'local-seed:configure:graphic-design:1.0.0',
     'local-seed:configure:graphic-design:1.0.0',
     '10000000-0000-4000-8000-000000000011', '2026-01-01T00:00:00Z'),
    ('10000000-0000-4000-8000-000000000143',
     '10000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000121', 2, 'ACTIVATED',
     'DRAFT', 'ACTIVE', '10000000-0000-4000-8000-000000000131',
     'local-seed:activate:graphic-design:1.0.0',
     'local-seed:activate:graphic-design:1.0.0',
     '10000000-0000-4000-8000-000000000011', '2026-01-01T00:00:00Z'),
    ('10000000-0000-4000-8000-000000000144',
     '10000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000122', 0, 'HIRED',
     NULL, 'DRAFT', NULL,
     'local-seed:hire:contract-review:1.0.0',
     'local-seed:hire:contract-review:1.0.0',
     '10000000-0000-4000-8000-000000000011', '2026-01-01T00:00:00Z'),
    ('10000000-0000-4000-8000-000000000145',
     '10000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000122', 1, 'CONFIGURATION_CREATED',
     'DRAFT', 'DRAFT', '10000000-0000-4000-8000-000000000132',
     'local-seed:configure:contract-review:1.0.0',
     'local-seed:configure:contract-review:1.0.0',
     '10000000-0000-4000-8000-000000000011', '2026-01-01T00:00:00Z'),
    ('10000000-0000-4000-8000-000000000146',
     '10000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000122', 2, 'ACTIVATED',
     'DRAFT', 'ACTIVE', '10000000-0000-4000-8000-000000000132',
     'local-seed:activate:contract-review:1.0.0',
     'local-seed:activate:contract-review:1.0.0',
     '10000000-0000-4000-8000-000000000011', '2026-01-01T00:00:00Z'),
    ('10000000-0000-4000-8000-000000000147',
     '10000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000123', 0, 'HIRED',
     NULL, 'DRAFT', NULL,
     'local-seed:hire:quotation:1.0.0',
     'local-seed:hire:quotation:1.0.0',
     '10000000-0000-4000-8000-000000000011', '2026-01-01T00:00:00Z'),
    ('10000000-0000-4000-8000-000000000148',
     '10000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000123', 1, 'CONFIGURATION_CREATED',
     'DRAFT', 'DRAFT', '10000000-0000-4000-8000-000000000133',
     'local-seed:configure:quotation:1.0.0',
     'local-seed:configure:quotation:1.0.0',
     '10000000-0000-4000-8000-000000000011', '2026-01-01T00:00:00Z'),
    ('10000000-0000-4000-8000-000000000149',
     '10000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000123', 2, 'ACTIVATED',
     'DRAFT', 'ACTIVE', '10000000-0000-4000-8000-000000000133',
     'local-seed:activate:quotation:1.0.0',
     'local-seed:activate:quotation:1.0.0',
     '10000000-0000-4000-8000-000000000011', '2026-01-01T00:00:00Z')
ON CONFLICT DO NOTHING;

INSERT INTO dianlian_business.point_account
    (account_id, tenant_id, ledger_scope_id, account_type, unit_code, status,
     available_amount_snapshot, reserved_amount_snapshot, gross_captured_amount_snapshot,
     returned_amount_snapshot, net_consumed_amount_snapshot, version, created_at, updated_at)
VALUES
    ('10000000-0000-4000-8000-000000000201',
     '10000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000202',
     'MAIN', 'POINT', 'ACTIVE', 100000000000, 0, 0, 0, 0, 0,
     '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
ON CONFLICT (account_id) DO NOTHING;

INSERT INTO dianlian_business.point_lot
    (lot_id, tenant_id, account_id, source_type, source_id, total_amount,
     available_amount_snapshot, reserved_amount_snapshot, expires_at, priority,
     status, created_at, updated_at)
VALUES
    ('10000000-0000-4000-8000-000000000203',
     '10000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000201',
     'GRANT', 'local-golden-slice-v1', 100000000000, 100000000000, 0, NULL, 100,
     'ACTIVE', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
ON CONFLICT (lot_id) DO NOTHING;

INSERT INTO dianlian_business.point_ledger_account
    (ledger_account_id, tenant_id, ledger_scope_id, owner_type, owner_id,
     bucket_code, unit_code, status, created_at)
VALUES
    ('10000000-0000-4000-8000-000000000211',
     '10000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000202', 'TENANT',
     '10000000-0000-4000-8000-000000000001', 'AVAILABLE', 'POINT', 'ACTIVE',
     '2026-01-01T00:00:00Z'),
    ('10000000-0000-4000-8000-000000000212',
     '10000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000202', 'TENANT',
     '10000000-0000-4000-8000-000000000001', 'RESERVED', 'POINT', 'ACTIVE',
     '2026-01-01T00:00:00Z'),
    ('10000000-0000-4000-8000-000000000213',
     '10000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000202', 'TENANT',
     '10000000-0000-4000-8000-000000000001', 'ISSUANCE', 'POINT', 'ACTIVE',
     '2026-01-01T00:00:00Z'),
    ('10000000-0000-4000-8000-000000000214',
     '10000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000202', 'TENANT',
     '10000000-0000-4000-8000-000000000001', 'CONSUMED', 'POINT', 'ACTIVE',
     '2026-01-01T00:00:00Z'),
    ('10000000-0000-4000-8000-000000000215',
     '10000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000202', 'TENANT',
     '10000000-0000-4000-8000-000000000001', 'EXPIRATION', 'POINT', 'ACTIVE',
     '2026-01-01T00:00:00Z')
ON CONFLICT (ledger_account_id) DO NOTHING;

INSERT INTO dianlian_business.point_ledger_transaction
    (transaction_id, tenant_id, ledger_scope_id, transaction_type, idempotency_key,
     business_type, business_id, original_transaction_id, reason_code, operator_id,
     status, created_at, posted_at)
VALUES
    ('10000000-0000-4000-8000-000000000220',
     '10000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000202',
     'GRANT', 'local-seed:grant:golden-slice-v1', 'LOCAL_SEED',
     '10000000-0000-4000-8000-000000000203', NULL,
     'LOCAL_DEVELOPMENT_GRANT', '10000000-0000-4000-8000-000000000010',
     'POSTED', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
ON CONFLICT (transaction_id) DO NOTHING;

INSERT INTO dianlian_business.point_ledger_entry
    (entry_id, tenant_id, ledger_scope_id, transaction_id, ledger_account_id,
     unit_code, direction, amount, point_lot_id, sequence_no, created_at)
VALUES
    ('10000000-0000-4000-8000-000000000221',
     '10000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000202',
     '10000000-0000-4000-8000-000000000220',
     '10000000-0000-4000-8000-000000000211',
     'POINT', 'DEBIT', 100000000000, '10000000-0000-4000-8000-000000000203', 1,
     '2026-01-01T00:00:00Z'),
    ('10000000-0000-4000-8000-000000000222',
     '10000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000202',
     '10000000-0000-4000-8000-000000000220',
     '10000000-0000-4000-8000-000000000213',
     'POINT', 'CREDIT', 100000000000, '10000000-0000-4000-8000-000000000203', 2,
     '2026-01-01T00:00:00Z')
ON CONFLICT (entry_id) DO NOTHING;

SET CONSTRAINTS ALL IMMEDIATE;
COMMIT;
