\set ON_ERROR_STOP on

BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SET CONSTRAINTS ALL DEFERRED;

CREATE TEMP TABLE dianlian_seed_runtime
(
    local_username          VARCHAR(200) NOT NULL,
    platform_username       VARCHAR(200) NOT NULL
) ON COMMIT DROP;

INSERT INTO dianlian_seed_runtime (local_username, platform_username)
VALUES (LOWER(:'dianlian_local_username'), LOWER(:'dianlian_local_platform_username'));

DO $verify_seed$
DECLARE
    actual_count BIGINT;
    actual_capabilities TEXT[];
    account_available BIGINT;
    account_reserved BIGINT;
    lot_available BIGINT;
    lot_reserved BIGINT;
    grant_debit BIGINT;
    grant_credit BIGINT;
BEGIN
    SELECT COUNT(*) INTO actual_count
      FROM dianlian_business.user_login_identifier li
      JOIN dianlian_business.user_account ua ON ua.user_id = li.user_id
      JOIN dianlian_business.password_credential pc ON pc.user_id = ua.user_id
      CROSS JOIN dianlian_seed_runtime runtime
     WHERE li.user_id = '10000000-0000-4000-8000-000000000011'
       AND li.identifier_type = 'USERNAME'
       AND li.normalized_identifier = runtime.local_username
       AND li.status = 'ACTIVE'
       AND pc.password_algorithm = 'BCRYPT'
       AND pc.password_hash ~ '^\$2[aby]\$[0-9]{2}\$[./A-Za-z0-9]{53}$'
       AND ua.status = 'ACTIVE'
       AND pc.locked_until IS NULL;
    IF actual_count <> 1 THEN
        RAISE EXCEPTION 'local enterprise login credential is not valid';
    END IF;

    SELECT COUNT(*) INTO actual_count
      FROM dianlian_business.user_login_identifier li
      JOIN dianlian_business.user_account ua ON ua.user_id = li.user_id
      JOIN dianlian_business.password_credential pc ON pc.user_id = ua.user_id
      CROSS JOIN dianlian_seed_runtime runtime
     WHERE li.user_id = '10000000-0000-4000-8000-000000000010'
       AND li.identifier_type = 'USERNAME'
       AND li.normalized_identifier = runtime.platform_username
       AND li.status = 'ACTIVE'
       AND pc.password_algorithm = 'BCRYPT'
       AND pc.password_hash ~ '^\$2[aby]\$[0-9]{2}\$[./A-Za-z0-9]{53}$'
       AND ua.status = 'ACTIVE'
       AND pc.locked_until IS NULL;
    IF actual_count <> 1 THEN
        RAISE EXCEPTION 'local platform login credential is not valid';
    END IF;

    SELECT COUNT(DISTINCT p.permission_code) INTO actual_count
      FROM dianlian_business.role_grant rg
      JOIN dianlian_business.iam_role r
        ON r.role_code = rg.role_code AND r.status = 'ACTIVE'
      JOIN dianlian_business.role_permission rp ON rp.role_code = r.role_code
      JOIN dianlian_business.iam_permission p
        ON p.permission_code = rp.permission_code AND p.status = 'ACTIVE'
     WHERE rg.subject_user_id = '10000000-0000-4000-8000-000000000011'
       AND rg.tenant_id = '10000000-0000-4000-8000-000000000001'
       AND rg.revoked_at IS NULL
       AND (rg.expires_at IS NULL OR rg.expires_at > CURRENT_TIMESTAMP)
       AND p.permission_code IN (
           'enterprise.employee.hire',
           'enterprise.employee.read',
           'enterprise.employee.configure',
           'enterprise.employee.activate',
           'enterprise.employee.execute',
           'enterprise.employee.model.configure',
           'conversation.read',
           'conversation.create',
           'conversation.message.send',
           'conversation.agent.invoke',
           'task.create',
           'task.read',
           'enterprise.knowledge.read',
           'enterprise.knowledge.manage',
           'memory.candidate.propose',
           'memory.recall',
           'memory.self.manage',
           'memory.group.manage',
           'enterprise.memory.govern'
       );
    IF actual_count <> 19 THEN
        RAISE EXCEPTION 'local enterprise actor does not have the required employee, conversation, task and context permissions';
    END IF;

    SELECT COUNT(*) INTO actual_count
      FROM dianlian_business.role_grant rg
      JOIN dianlian_business.role_permission rp ON rp.role_code = rg.role_code
     WHERE rg.subject_user_id = '10000000-0000-4000-8000-000000000010'
       AND rg.tenant_id IS NULL
       AND rg.scope_type = 'PLATFORM'
       AND rg.revoked_at IS NULL
       AND rp.permission_code IN (
           'platform.employee.template.read',
           'platform.employee.template.publish',
           'platform.model.read',
           'platform.model.manage',
           'platform.knowledge.read',
           'platform.knowledge.manage'
       );
    IF actual_count <> 6 THEN
        RAISE EXCEPTION 'local platform actor does not have template, model and knowledge management permissions';
    END IF;

    SELECT COUNT(*), ARRAY_AGG(v.capability_code::TEXT ORDER BY v.capability_code)
      INTO actual_count, actual_capabilities
      FROM dianlian_business.enterprise_agent a
      JOIN dianlian_business.agent_version v
        ON v.agent_version_id = a.agent_version_id
     JOIN dianlian_business.agent_template t
        ON t.agent_template_id = a.agent_template_id
     WHERE a.tenant_id = '10000000-0000-4000-8000-000000000001'
       AND a.enterprise_agent_id IN (
           '10000000-0000-4000-8000-000000000121',
           '10000000-0000-4000-8000-000000000122',
           '10000000-0000-4000-8000-000000000123'
       )
       AND a.status = 'ACTIVE'
       AND v.status = 'PUBLISHED'
       AND t.status = 'ACTIVE';
    IF actual_count <> 3 OR actual_capabilities <> ARRAY[
        'CONTRACT_REVIEW', 'GRAPHIC_DESIGN', 'QUOTATION'
    ]::TEXT[] THEN
        RAISE EXCEPTION 'Office executable employee query did not return the three Golden Slice capabilities';
    END IF;

    SELECT COUNT(*) INTO actual_count
      FROM (VALUES
          ('10000000-0000-4000-8000-000000000121'::UUID,
           '10000000-0000-4000-8000-000000000111'::UUID, 'GRAPHIC_DESIGN'::TEXT, 600000000::BIGINT),
          ('10000000-0000-4000-8000-000000000122'::UUID,
           '10000000-0000-4000-8000-000000000112'::UUID, 'CONTRACT_REVIEW'::TEXT, 450000000::BIGINT),
          ('10000000-0000-4000-8000-000000000123'::UUID,
           '10000000-0000-4000-8000-000000000113'::UUID, 'QUOTATION'::TEXT, 350000000::BIGINT)
      ) expected(enterprise_agent_id, agent_version_id, capability_code, point_estimate)
      JOIN dianlian_business.enterprise_agent a
        ON a.enterprise_agent_id = expected.enterprise_agent_id
       AND a.agent_version_id = expected.agent_version_id
       AND a.status = 'ACTIVE'
      JOIN dianlian_business.agent_version v
        ON v.agent_version_id = expected.agent_version_id
       AND v.capability_code = expected.capability_code
       AND v.point_estimate = expected.point_estimate
       AND v.status = 'PUBLISHED';
    IF actual_count <> 3 THEN
        RAISE EXCEPTION 'employee/version binding or micro_credit point estimate is invalid';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM dianlian_business.enterprise_agent a
          LEFT JOIN dianlian_business.enterprise_agent_configuration_version configuration
            ON configuration.tenant_id = a.tenant_id
           AND configuration.enterprise_agent_id = a.enterprise_agent_id
           AND configuration.configuration_version_id = a.active_configuration_version_id
         WHERE a.tenant_id = '10000000-0000-4000-8000-000000000001'
           AND a.status = 'ACTIVE'
           AND (
               a.active_configuration_version_id IS NULL
               OR a.activated_by IS NULL
               OR a.activated_at IS NULL
               OR configuration.configuration_version_id IS NULL
               OR configuration.status <> 'ACTIVE'
               OR configuration.activation_result_state_version <> a.state_version
           )
    ) THEN
        RAISE EXCEPTION 'an ACTIVE enterprise employee is not bound to an ACTIVE configuration';
    END IF;

    SELECT COUNT(*) INTO actual_count
      FROM (VALUES
          ('10000000-0000-4000-8000-000000000121'::UUID,
           '10000000-0000-4000-8000-000000000131'::UUID,
           '小绘'::TEXT,
           '遵循当前企业已确认的品牌规范与素材授权范围；生成方案前先确认用途、尺寸和交付格式，最终成果需人工确认。'::TEXT),
          ('10000000-0000-4000-8000-000000000122'::UUID,
           '10000000-0000-4000-8000-000000000132'::UUID,
           '小法'::TEXT,
           '仅依据当前企业已授权的合同文本、条款库和审查规则给出风险意见；不替代律师判断，最终意见需人工确认。'::TEXT),
          ('10000000-0000-4000-8000-000000000123'::UUID,
           '10000000-0000-4000-8000-000000000133'::UUID,
           '小价'::TEXT,
           '优先使用当前企业已授权的项目资料、成本规则和历史案例；列明依据与假设，最终报价需人工确认。'::TEXT)
      ) expected(enterprise_agent_id, configuration_version_id, display_name, enterprise_instructions)
      JOIN dianlian_business.enterprise_agent agent
        ON agent.enterprise_agent_id = expected.enterprise_agent_id
       AND agent.tenant_id = '10000000-0000-4000-8000-000000000001'
       AND agent.status = 'ACTIVE'
       AND agent.state_version = 2
       AND agent.active_configuration_version_id = expected.configuration_version_id
       AND agent.activated_by = '10000000-0000-4000-8000-000000000011'
       AND agent.activated_at IS NOT NULL
      JOIN dianlian_business.enterprise_agent_configuration_version configuration
        ON configuration.configuration_version_id = expected.configuration_version_id
       AND configuration.tenant_id = agent.tenant_id
       AND configuration.enterprise_agent_id = agent.enterprise_agent_id
       AND configuration.revision = 1
       AND configuration.display_name_snapshot = expected.display_name
       AND configuration.enterprise_instructions = expected.enterprise_instructions
       AND BTRIM(configuration.profile) <> ''
       AND configuration.model_policy_mode = 'PLATFORM_DEFAULT'
       AND configuration.knowledge_scope_mode = 'NONE'
       AND configuration.visibility_scope = 'TENANT'
       AND configuration.status = 'ACTIVE'
       AND configuration.create_result_state_version = 1
       AND configuration.activation_result_state_version = 2
       AND configuration.created_by = '10000000-0000-4000-8000-000000000011'
       AND configuration.activated_by = agent.activated_by
       AND configuration.activated_at = agent.activated_at
       AND BTRIM(configuration.create_request_hash) <> ''
       AND BTRIM(configuration.create_idempotency_key) <> ''
       AND BTRIM(configuration.activation_request_hash) <> ''
       AND BTRIM(configuration.activation_idempotency_key) <> '';
    IF actual_count <> 3 THEN
        RAISE EXCEPTION 'Golden Slice employee configuration, enterprise instructions, or modes are invalid';
    END IF;

    SELECT COUNT(*) INTO actual_count
      FROM dianlian_business.enterprise_agent_configuration_version configuration
     WHERE configuration.tenant_id = '10000000-0000-4000-8000-000000000001'
       AND configuration.enterprise_agent_id IN (
           '10000000-0000-4000-8000-000000000121',
           '10000000-0000-4000-8000-000000000122',
           '10000000-0000-4000-8000-000000000123'
       );
    IF actual_count <> 3 THEN
        RAISE EXCEPTION 'Golden Slice seed must keep exactly one configuration version per employee';
    END IF;

    SELECT COUNT(*) INTO actual_count
      FROM dianlian_business.enterprise_agent_state_event event
     WHERE event.tenant_id = '10000000-0000-4000-8000-000000000001'
       AND event.enterprise_agent_id IN (
           '10000000-0000-4000-8000-000000000121',
           '10000000-0000-4000-8000-000000000122',
           '10000000-0000-4000-8000-000000000123'
       );
    IF actual_count <> 9 THEN
        RAISE EXCEPTION 'Golden Slice employee state-event audit must contain exactly nine rows';
    END IF;

    IF EXISTS (
        SELECT event.enterprise_agent_id
          FROM dianlian_business.enterprise_agent_state_event event
         WHERE event.tenant_id = '10000000-0000-4000-8000-000000000001'
           AND event.enterprise_agent_id IN (
               '10000000-0000-4000-8000-000000000121',
               '10000000-0000-4000-8000-000000000122',
               '10000000-0000-4000-8000-000000000123'
           )
         GROUP BY event.enterprise_agent_id
        HAVING COUNT(*) <> 3
            OR COUNT(DISTINCT event.state_version) <> 3
            OR MIN(event.state_version) <> 0
            OR MAX(event.state_version) <> 2
            OR COUNT(*) FILTER (WHERE event.event_type = 'HIRED'
                                  AND event.from_status IS NULL
                                  AND event.to_status = 'DRAFT'
                                  AND event.configuration_version_id IS NULL) <> 1
            OR COUNT(*) FILTER (WHERE event.event_type = 'CONFIGURATION_CREATED'
                                  AND event.from_status = 'DRAFT'
                                  AND event.to_status = 'DRAFT'
                                  AND event.configuration_version_id IS NOT NULL) <> 1
            OR COUNT(*) FILTER (WHERE event.event_type = 'ACTIVATED'
                                  AND event.from_status = 'DRAFT'
                                  AND event.to_status = 'ACTIVE'
                                  AND event.configuration_version_id IS NOT NULL) <> 1
    ) THEN
        RAISE EXCEPTION 'Golden Slice employee state-event sequence is invalid';
    END IF;

    SELECT COUNT(*) INTO actual_count
      FROM dianlian_business.agent_version v
     WHERE v.agent_version_id IN (
         '10000000-0000-4000-8000-000000000111',
         '10000000-0000-4000-8000-000000000112',
         '10000000-0000-4000-8000-000000000113'
     )
       AND v.input_schema ?& ARRAY['schemaId', 'version', 'schema']
       AND JSONB_TYPEOF(v.input_schema -> 'schema') = 'object'
       AND v.execution_template ?& ARRAY['templateCode', 'version', 'steps']
       AND JSONB_TYPEOF(v.execution_template -> 'steps') = 'array'
       AND JSONB_ARRAY_LENGTH(v.execution_template -> 'steps') > 0
       AND v.point_estimate > 0
       AND (
           v.visibility_mode = 'ALL'
           OR v.visible_tenant_ids @> '["10000000-0000-4000-8000-000000000001"]'::jsonb
       );
    IF actual_count <> 3 THEN
        RAISE EXCEPTION 'employee execution-profile JSON or enterprise visibility is invalid';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM dianlian_business.agent_version v
          CROSS JOIN LATERAL JSONB_ARRAY_ELEMENTS(v.execution_template -> 'steps') step
         WHERE v.agent_version_id IN (
             '10000000-0000-4000-8000-000000000111',
             '10000000-0000-4000-8000-000000000112',
             '10000000-0000-4000-8000-000000000113'
         )
           AND (
               NOT step ?& ARRAY['stepKey', 'title', 'executorType', 'dependsOn', 'humanCheckpoint']
               OR JSONB_TYPEOF(step -> 'dependsOn') <> 'array'
               OR step ->> 'executorType' NOT IN (
                   'MODEL', 'RETRIEVAL', 'RULE_ENGINE', 'TOOL', 'HUMAN_CHECKPOINT', 'SUBTASK'
               )
           )
    ) THEN
        RAISE EXCEPTION 'employee execution-template step shape is invalid';
    END IF;

    SELECT available_amount_snapshot, reserved_amount_snapshot
      INTO account_available, account_reserved
      FROM dianlian_business.point_account
     WHERE account_id = '10000000-0000-4000-8000-000000000201'
       AND tenant_id = '10000000-0000-4000-8000-000000000001'
       AND account_type = 'MAIN'
       AND unit_code = 'POINT'
       AND status = 'ACTIVE';
    IF account_available IS NULL OR account_available < 600000000 THEN
        RAISE EXCEPTION 'local point account cannot reserve the highest employee point estimate';
    END IF;

    SELECT COALESCE(SUM(available_amount_snapshot), 0),
           COALESCE(SUM(reserved_amount_snapshot), 0)
      INTO lot_available, lot_reserved
      FROM dianlian_business.point_lot
     WHERE account_id = '10000000-0000-4000-8000-000000000201'
       AND status IN ('ACTIVE', 'EXHAUSTED')
       AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP);
    IF account_available <> lot_available OR account_reserved <> lot_reserved THEN
        RAISE EXCEPTION 'point account snapshots do not reconcile with reservable lots';
    END IF;

    IF EXISTS (
        SELECT transaction.transaction_id
          FROM dianlian_business.point_ledger_transaction transaction
          LEFT JOIN dianlian_business.point_ledger_entry entry
            ON entry.transaction_id = transaction.transaction_id
         GROUP BY transaction.transaction_id
        HAVING COUNT(entry.entry_id) < 2
            OR COALESCE(SUM(CASE WHEN entry.direction = 'DEBIT' THEN entry.amount ELSE -entry.amount END), 0) <> 0
    ) THEN
        RAISE EXCEPTION 'at least one point ledger transaction is not balanced';
    END IF;

    SELECT COUNT(*),
           COALESCE(SUM(amount) FILTER (WHERE direction = 'DEBIT'), 0),
           COALESCE(SUM(amount) FILTER (WHERE direction = 'CREDIT'), 0)
      INTO actual_count, grant_debit, grant_credit
      FROM dianlian_business.point_ledger_entry
     WHERE transaction_id = '10000000-0000-4000-8000-000000000220';
    IF actual_count <> 2 OR grant_debit <> 100000000000 OR grant_credit <> 100000000000 THEN
        RAISE EXCEPTION 'local initial grant ledger is incomplete';
    END IF;
END
$verify_seed$;

-- State-transition audit is append-only even for direct database access.
DO $verify_state_event_append_only$
DECLARE
    update_rejected BOOLEAN := FALSE;
    delete_rejected BOOLEAN := FALSE;
    error_message TEXT;
    actual_count BIGINT;
BEGIN
    BEGIN
        UPDATE dianlian_business.enterprise_agent_state_event
           SET request_hash = 'local-smoke:illegal-event-update'
         WHERE event_id = '10000000-0000-4000-8000-000000000141';
    EXCEPTION
        WHEN raise_exception THEN
            GET STACKED DIAGNOSTICS error_message = MESSAGE_TEXT;
            update_rejected := error_message = 'enterprise agent state events are append-only';
    END;

    BEGIN
        DELETE FROM dianlian_business.enterprise_agent_state_event
         WHERE event_id = '10000000-0000-4000-8000-000000000141';
    EXCEPTION
        WHEN raise_exception THEN
            GET STACKED DIAGNOSTICS error_message = MESSAGE_TEXT;
            delete_rejected := error_message = 'enterprise agent state events are append-only';
    END;

    SELECT COUNT(*) INTO actual_count
      FROM dianlian_business.enterprise_agent_state_event
     WHERE event_id = '10000000-0000-4000-8000-000000000141'
       AND request_hash = 'local-seed:hire:graphic-design:1.0.0';
    IF NOT update_rejected OR NOT delete_rejected OR actual_count <> 1 THEN
        RAISE EXCEPTION 'enterprise employee state-event append-only protection failed';
    END IF;
END
$verify_state_event_append_only$;

-- Exercise the real configuration lifecycle SQL used by EmployeeApplicationService.
-- These rows are isolated to this transaction and disappear with the final ROLLBACK.
INSERT INTO dianlian_business.enterprise_agent
    (enterprise_agent_id, tenant_id, agent_template_id, agent_version_id,
     employee_code, display_name, status, request_hash, hire_idempotency_key,
     hired_by, hired_at, created_at, updated_at)
VALUES
    ('90000000-0000-4000-8000-000000000020',
     '10000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000103',
     '10000000-0000-4000-8000-000000000113',
     'DL-SMOKE-LIFECYCLE', '配置生命周期验证员工', 'DRAFT',
     'local-smoke:hire:lifecycle', 'local-smoke:hire:lifecycle',
     '10000000-0000-4000-8000-000000000011',
     '2026-01-02T00:00:00Z', '2026-01-02T00:00:00Z', '2026-01-02T00:00:00Z');

INSERT INTO dianlian_business.enterprise_agent_state_event
    (event_id, tenant_id, enterprise_agent_id, state_version, event_type,
     from_status, to_status, configuration_version_id, request_hash,
     idempotency_key, actor_id, occurred_at)
VALUES
    ('90000000-0000-4000-8000-000000000021',
     '10000000-0000-4000-8000-000000000001',
     '90000000-0000-4000-8000-000000000020', 0, 'HIRED',
     NULL, 'DRAFT', NULL, 'local-smoke:hire:lifecycle',
     'local-smoke:hire:lifecycle',
     '10000000-0000-4000-8000-000000000011', '2026-01-02T00:00:00Z');

INSERT INTO dianlian_business.enterprise_agent_configuration_version
    (configuration_version_id, tenant_id, enterprise_agent_id, revision,
     display_name_snapshot, profile, enterprise_instructions,
     model_policy_mode, knowledge_scope_mode, visibility_scope, status,
     create_request_hash, create_idempotency_key, created_by, created_at,
     create_result_state_version, updated_at)
VALUES
    ('90000000-0000-4000-8000-000000000022',
     '10000000-0000-4000-8000-000000000001',
     '90000000-0000-4000-8000-000000000020', 1,
     '配置生命周期验证员工', '验证配置创建与激活状态机。',
     '仅用于本地事务内生命周期验证。',
     'PLATFORM_DEFAULT', 'NONE', 'TENANT', 'DRAFT',
     'local-smoke:configure:lifecycle', 'local-smoke:configure:lifecycle',
     '10000000-0000-4000-8000-000000000011',
     '2026-01-02T00:01:00Z', 1, '2026-01-02T00:01:00Z');

UPDATE dianlian_business.enterprise_agent
   SET state_version = state_version + 1,
       updated_at = '2026-01-02T00:01:00Z'
 WHERE tenant_id = '10000000-0000-4000-8000-000000000001'
   AND enterprise_agent_id = '90000000-0000-4000-8000-000000000020'
   AND status = 'DRAFT'
   AND state_version = 0;

INSERT INTO dianlian_business.enterprise_agent_state_event
    (event_id, tenant_id, enterprise_agent_id, state_version, event_type,
     from_status, to_status, configuration_version_id, request_hash,
     idempotency_key, actor_id, occurred_at)
VALUES
    ('90000000-0000-4000-8000-000000000023',
     '10000000-0000-4000-8000-000000000001',
     '90000000-0000-4000-8000-000000000020', 1, 'CONFIGURATION_CREATED',
     'DRAFT', 'DRAFT', '90000000-0000-4000-8000-000000000022',
     'local-smoke:configure:lifecycle', 'local-smoke:configure:lifecycle',
     '10000000-0000-4000-8000-000000000011', '2026-01-02T00:01:00Z');

UPDATE dianlian_business.enterprise_agent_configuration_version
   SET status = 'ACTIVE',
       activation_request_hash = 'local-smoke:activate:lifecycle',
       activation_idempotency_key = 'local-smoke:activate:lifecycle',
       activated_by = '10000000-0000-4000-8000-000000000011',
       activated_at = '2026-01-02T00:02:00Z',
       activation_result_state_version = 2,
       updated_at = '2026-01-02T00:02:00Z'
 WHERE tenant_id = '10000000-0000-4000-8000-000000000001'
   AND enterprise_agent_id = '90000000-0000-4000-8000-000000000020'
   AND configuration_version_id = '90000000-0000-4000-8000-000000000022'
   AND status = 'DRAFT'
   AND activation_idempotency_key IS NULL;

UPDATE dianlian_business.enterprise_agent
   SET display_name = '配置生命周期验证员工',
       status = 'ACTIVE',
       state_version = state_version + 1,
       active_configuration_version_id = '90000000-0000-4000-8000-000000000022',
       activated_by = '10000000-0000-4000-8000-000000000011',
       activated_at = '2026-01-02T00:02:00Z',
       updated_at = '2026-01-02T00:02:00Z'
 WHERE tenant_id = '10000000-0000-4000-8000-000000000001'
   AND enterprise_agent_id = '90000000-0000-4000-8000-000000000020'
   AND status = 'DRAFT'
   AND state_version = 1
   AND active_configuration_version_id IS NULL;

INSERT INTO dianlian_business.enterprise_agent_state_event
    (event_id, tenant_id, enterprise_agent_id, state_version, event_type,
     from_status, to_status, configuration_version_id, request_hash,
     idempotency_key, actor_id, occurred_at)
VALUES
    ('90000000-0000-4000-8000-000000000024',
     '10000000-0000-4000-8000-000000000001',
     '90000000-0000-4000-8000-000000000020', 2, 'ACTIVATED',
     'DRAFT', 'ACTIVE', '90000000-0000-4000-8000-000000000022',
     'local-smoke:activate:lifecycle', 'local-smoke:activate:lifecycle',
     '10000000-0000-4000-8000-000000000011', '2026-01-02T00:02:00Z');

DO $verify_configuration_lifecycle$
DECLARE
    actual_count BIGINT;
    actual_events TEXT[];
BEGIN
    SELECT COUNT(*) INTO actual_count
      FROM dianlian_business.enterprise_agent agent
      JOIN dianlian_business.enterprise_agent_configuration_version configuration
        ON configuration.tenant_id = agent.tenant_id
       AND configuration.enterprise_agent_id = agent.enterprise_agent_id
       AND configuration.configuration_version_id = agent.active_configuration_version_id
     WHERE agent.tenant_id = '10000000-0000-4000-8000-000000000001'
       AND agent.enterprise_agent_id = '90000000-0000-4000-8000-000000000020'
       AND agent.status = 'ACTIVE'
       AND agent.state_version = 2
       AND agent.activated_by = '10000000-0000-4000-8000-000000000011'
       AND agent.activated_at = '2026-01-02T00:02:00Z'
       AND configuration.status = 'ACTIVE'
       AND configuration.create_result_state_version = 1
       AND configuration.activation_result_state_version = 2
       AND configuration.activated_by = agent.activated_by
       AND configuration.activated_at = agent.activated_at;
    IF actual_count <> 1 THEN
        RAISE EXCEPTION 'DRAFT to configured to ACTIVE lifecycle invariant failed';
    END IF;

    SELECT ARRAY_AGG(event.event_type::TEXT ORDER BY event.state_version)
      INTO actual_events
      FROM dianlian_business.enterprise_agent_state_event event
     WHERE event.tenant_id = '10000000-0000-4000-8000-000000000001'
       AND event.enterprise_agent_id = '90000000-0000-4000-8000-000000000020';
    IF actual_events <> ARRAY['HIRED', 'CONFIGURATION_CREATED', 'ACTIVATED']::TEXT[] THEN
        RAISE EXCEPTION 'configuration lifecycle state-event sequence failed';
    END IF;
END
$verify_configuration_lifecycle$;

-- The database lifecycle constraint must reject an ACTIVE employee without a bound configuration.
DO $verify_active_requires_configuration$
DECLARE
    rejected BOOLEAN := FALSE;
BEGIN
    BEGIN
        INSERT INTO dianlian_business.enterprise_agent
            (enterprise_agent_id, tenant_id, agent_template_id, agent_version_id,
             employee_code, display_name, status, request_hash, hire_idempotency_key,
             hired_by, hired_at, created_at, updated_at)
        VALUES
            ('90000000-0000-4000-8000-000000000025',
             '10000000-0000-4000-8000-000000000001',
             '10000000-0000-4000-8000-000000000103',
             '10000000-0000-4000-8000-000000000113',
             'DL-SMOKE-NO-CONFIG', '无配置激活验证员工', 'ACTIVE',
             'local-smoke:hire:no-config', 'local-smoke:hire:no-config',
             '10000000-0000-4000-8000-000000000011',
             '2026-01-02T00:03:00Z', '2026-01-02T00:03:00Z', '2026-01-02T00:03:00Z');
    EXCEPTION
        WHEN check_violation THEN rejected := TRUE;
    END;

    IF NOT rejected THEN
        RAISE EXCEPTION 'ACTIVE enterprise employee without configuration was not rejected';
    END IF;
END
$verify_active_requires_configuration$;

-- Build a separate published version, configure a DRAFT employee, then retire that
-- version. EmployeeApplicationService.requirePublishedBinding must reject activation
-- before either the configuration or employee row is mutated.
INSERT INTO dianlian_business.agent_version
    (agent_version_id, owner_scope, agent_template_id, template_name,
     template_description, version_label, capability_code, input_schema,
     execution_template, point_estimate, status, visibility_mode,
     visible_tenant_ids, request_hash, publish_idempotency_key, published_by,
     published_at, created_at, updated_at)
SELECT
    '90000000-0000-4000-8000-000000000030', owner_scope, agent_template_id,
    template_name, template_description, 'local-smoke-retired', capability_code,
    input_schema, execution_template, point_estimate, 'PUBLISHED', visibility_mode,
    visible_tenant_ids, 'local-smoke:publish:retired-version',
    'local-smoke:publish:retired-version', published_by,
    '2026-01-02T00:04:00Z', '2026-01-02T00:04:00Z', '2026-01-02T00:04:00Z'
  FROM dianlian_business.agent_version
 WHERE agent_version_id = '10000000-0000-4000-8000-000000000113';

INSERT INTO dianlian_business.enterprise_agent
    (enterprise_agent_id, tenant_id, agent_template_id, agent_version_id,
     employee_code, display_name, status, request_hash, hire_idempotency_key,
     hired_by, hired_at, created_at, updated_at)
VALUES
    ('90000000-0000-4000-8000-000000000031',
     '10000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000103',
     '90000000-0000-4000-8000-000000000030',
     'DL-SMOKE-RETIRED', '下架版本激活验证员工', 'DRAFT',
     'local-smoke:hire:retired-version', 'local-smoke:hire:retired-version',
     '10000000-0000-4000-8000-000000000011',
     '2026-01-02T00:05:00Z', '2026-01-02T00:05:00Z', '2026-01-02T00:05:00Z');

INSERT INTO dianlian_business.enterprise_agent_state_event
    (event_id, tenant_id, enterprise_agent_id, state_version, event_type,
     from_status, to_status, configuration_version_id, request_hash,
     idempotency_key, actor_id, occurred_at)
VALUES
    ('90000000-0000-4000-8000-000000000032',
     '10000000-0000-4000-8000-000000000001',
     '90000000-0000-4000-8000-000000000031', 0, 'HIRED',
     NULL, 'DRAFT', NULL, 'local-smoke:hire:retired-version',
     'local-smoke:hire:retired-version',
     '10000000-0000-4000-8000-000000000011', '2026-01-02T00:05:00Z');

INSERT INTO dianlian_business.enterprise_agent_configuration_version
    (configuration_version_id, tenant_id, enterprise_agent_id, revision,
     display_name_snapshot, profile, enterprise_instructions,
     model_policy_mode, knowledge_scope_mode, visibility_scope, status,
     create_request_hash, create_idempotency_key, created_by, created_at,
     create_result_state_version, updated_at)
VALUES
    ('90000000-0000-4000-8000-000000000033',
     '10000000-0000-4000-8000-000000000001',
     '90000000-0000-4000-8000-000000000031', 1,
     '下架版本激活验证员工', '验证已下架版本不可激活。',
     '仅用于本地事务内非发布版本激活验证。',
     'PLATFORM_DEFAULT', 'NONE', 'TENANT', 'DRAFT',
     'local-smoke:configure:retired-version',
     'local-smoke:configure:retired-version',
     '10000000-0000-4000-8000-000000000011',
     '2026-01-02T00:06:00Z', 1, '2026-01-02T00:06:00Z');

UPDATE dianlian_business.enterprise_agent
   SET state_version = state_version + 1,
       updated_at = '2026-01-02T00:06:00Z'
 WHERE tenant_id = '10000000-0000-4000-8000-000000000001'
   AND enterprise_agent_id = '90000000-0000-4000-8000-000000000031'
   AND status = 'DRAFT'
   AND state_version = 0;

INSERT INTO dianlian_business.enterprise_agent_state_event
    (event_id, tenant_id, enterprise_agent_id, state_version, event_type,
     from_status, to_status, configuration_version_id, request_hash,
     idempotency_key, actor_id, occurred_at)
VALUES
    ('90000000-0000-4000-8000-000000000034',
     '10000000-0000-4000-8000-000000000001',
     '90000000-0000-4000-8000-000000000031', 1, 'CONFIGURATION_CREATED',
     'DRAFT', 'DRAFT', '90000000-0000-4000-8000-000000000033',
     'local-smoke:configure:retired-version',
     'local-smoke:configure:retired-version',
     '10000000-0000-4000-8000-000000000011', '2026-01-02T00:06:00Z');

UPDATE dianlian_business.agent_version
   SET status = 'RETIRED',
       updated_at = '2026-01-02T00:07:00Z'
 WHERE agent_version_id = '90000000-0000-4000-8000-000000000030'
   AND status = 'PUBLISHED';

DO $verify_non_published_activation_rejected$
DECLARE
    rejected BOOLEAN := FALSE;
    actual_count BIGINT;
BEGIN
    BEGIN
        IF NOT EXISTS (
            SELECT 1
              FROM dianlian_business.enterprise_agent agent
              JOIN dianlian_business.agent_version version
                ON version.agent_version_id = agent.agent_version_id
              JOIN dianlian_business.agent_template template
                ON template.agent_template_id = version.agent_template_id
             WHERE agent.tenant_id = '10000000-0000-4000-8000-000000000001'
               AND agent.enterprise_agent_id = '90000000-0000-4000-8000-000000000031'
               AND version.status = 'PUBLISHED'
               AND template.status = 'ACTIVE'
               AND (
                   version.visibility_mode = 'ALL'
                   OR version.visible_tenant_ids @>
                      JSONB_BUILD_ARRAY(agent.tenant_id::TEXT)
               )
        ) THEN
            RAISE EXCEPTION USING
                ERRCODE = 'DL001',
                MESSAGE = 'AGENT_VERSION_NOT_PUBLISHED';
        END IF;
    EXCEPTION
        WHEN SQLSTATE 'DL001' THEN rejected := TRUE;
    END;

    IF NOT rejected THEN
        RAISE EXCEPTION 'activation guard accepted a non-published agent version';
    END IF;

    SELECT COUNT(*) INTO actual_count
      FROM dianlian_business.enterprise_agent agent
      JOIN dianlian_business.enterprise_agent_configuration_version configuration
        ON configuration.tenant_id = agent.tenant_id
       AND configuration.enterprise_agent_id = agent.enterprise_agent_id
     WHERE agent.tenant_id = '10000000-0000-4000-8000-000000000001'
       AND agent.enterprise_agent_id = '90000000-0000-4000-8000-000000000031'
       AND agent.status = 'DRAFT'
       AND agent.state_version = 1
       AND agent.active_configuration_version_id IS NULL
       AND agent.activated_by IS NULL
       AND agent.activated_at IS NULL
       AND configuration.configuration_version_id =
           '90000000-0000-4000-8000-000000000033'
       AND configuration.status = 'DRAFT'
       AND configuration.activation_request_hash IS NULL
       AND configuration.activation_idempotency_key IS NULL
       AND configuration.activated_by IS NULL
       AND configuration.activated_at IS NULL
       AND configuration.activation_result_state_version IS NULL;
    IF actual_count <> 1 THEN
        RAISE EXCEPTION 'rejected non-published activation changed employee or configuration state';
    END IF;
END
$verify_non_published_activation_rejected$;

-- Exercise the same financial and task relations as CreateTaskApplicationService,
-- then roll everything back so this smoke remains repeatable and non-destructive.
INSERT INTO dianlian_business.point_reservation
    (reservation_id, tenant_id, account_id, business_type, business_id,
     billing_scope_type, billing_scope_id, amount, captured_amount, released_amount,
     status, idempotency_key, reserve_ledger_transaction_id, created_by, created_at, updated_at)
VALUES
    ('90000000-0000-4000-8000-000000000002',
     '10000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000201',
     'TASK', '90000000-0000-4000-8000-000000000001',
     'TENANT', '10000000-0000-4000-8000-000000000001',
     350000000, 0, 0, 'ACTIVE', 'local-smoke:reserve:quotation',
     '90000000-0000-4000-8000-000000000003',
     '10000000-0000-4000-8000-000000000011', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);

UPDATE dianlian_business.point_account
   SET available_amount_snapshot = available_amount_snapshot - 350000000,
       reserved_amount_snapshot = reserved_amount_snapshot + 350000000,
       version = version + 1,
       updated_at = CURRENT_TIMESTAMP
 WHERE account_id = '10000000-0000-4000-8000-000000000201'
   AND available_amount_snapshot >= 350000000;

UPDATE dianlian_business.point_lot
   SET available_amount_snapshot = available_amount_snapshot - 350000000,
       reserved_amount_snapshot = reserved_amount_snapshot + 350000000,
       status = CASE WHEN available_amount_snapshot - 350000000 = 0 THEN 'EXHAUSTED' ELSE status END,
       updated_at = CURRENT_TIMESTAMP
 WHERE lot_id = '10000000-0000-4000-8000-000000000203'
   AND available_amount_snapshot >= 350000000;

INSERT INTO dianlian_business.point_reservation_allocation
    (tenant_id, reservation_id, lot_id, amount)
VALUES
    ('10000000-0000-4000-8000-000000000001',
     '90000000-0000-4000-8000-000000000002',
     '10000000-0000-4000-8000-000000000203', 350000000);

INSERT INTO dianlian_business.point_ledger_transaction
    (transaction_id, tenant_id, ledger_scope_id, transaction_type, idempotency_key,
     business_type, business_id, reason_code, operator_id, status, created_at, posted_at)
VALUES
    ('90000000-0000-4000-8000-000000000003',
     '10000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000202',
     'RESERVE', 'local-smoke:reserve:quotation', 'TASK',
     '90000000-0000-4000-8000-000000000001', 'RESERVATION_ADMISSION',
     '10000000-0000-4000-8000-000000000011', 'POSTED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);

INSERT INTO dianlian_business.point_ledger_entry
    (entry_id, tenant_id, ledger_scope_id, transaction_id, ledger_account_id,
     unit_code, direction, amount, point_lot_id, sequence_no, created_at)
VALUES
    ('90000000-0000-4000-8000-000000000004',
     '10000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000202',
     '90000000-0000-4000-8000-000000000003',
     '10000000-0000-4000-8000-000000000211',
     'POINT', 'CREDIT', 350000000, '10000000-0000-4000-8000-000000000203', 1, CURRENT_TIMESTAMP),
    ('90000000-0000-4000-8000-000000000005',
     '10000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000202',
     '90000000-0000-4000-8000-000000000003',
     '10000000-0000-4000-8000-000000000212',
     'POINT', 'DEBIT', 350000000, '10000000-0000-4000-8000-000000000203', 2, CURRENT_TIMESTAMP);

INSERT INTO dianlian_business.idempotency_record
    (tenant_id, actor_id, operation, idempotency_key, request_hash,
     created_at, expires_at)
VALUES
    ('10000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000011',
     'TASK_CREATE', 'local-smoke:create:quotation',
     'local-smoke-request-hash', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP + INTERVAL '24 hours');

INSERT INTO dianlian_business.task_run
    (task_id, tenant_id, task_version, title, goal, status, current_plan_version,
     collaboration_mode, capability_code, primary_agent_id, owner_user_id,
     billing_scope_type, billing_scope_id, max_point_cost, point_reservation_id,
     resume_event_id, created_by, created_at, updated_at)
VALUES
    ('90000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000001', 1,
     '本地报价 Golden Slice', '根据需求形成一份可复核的报价成果', 'QUEUED', 1,
     'SINGLE_TARGET', 'QUOTATION', '10000000-0000-4000-8000-000000000123',
     '10000000-0000-4000-8000-000000000011', 'TENANT',
     '10000000-0000-4000-8000-000000000001', 350000000,
     '90000000-0000-4000-8000-000000000002',
     '90000000-0000-4000-8000-000000000006',
     '10000000-0000-4000-8000-000000000011', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);

-- Keep this envelope aligned with CreateTaskApplicationService.ExecutionProfileSnapshot.
INSERT INTO dianlian_business.execution_plan_version
    (task_id, tenant_id, plan_version, status, execution_profile_snapshot, created_by, created_at)
SELECT
    '90000000-0000-4000-8000-000000000001',
    '10000000-0000-4000-8000-000000000001', 1, 'ACTIVE',
    JSONB_BUILD_OBJECT(
        'schemaVersion', 1,
        'agents', JSONB_BUILD_ARRAY(JSONB_BUILD_OBJECT(
            'enterpriseAgentId', a.enterprise_agent_id,
            'agentTemplateId', a.agent_template_id,
            'agentVersionId', a.agent_version_id,
            'displayName', a.display_name,
            'capabilityCode', v.capability_code,
            'inputSchema', v.input_schema,
            'executionTemplate', v.execution_template,
            'pointEstimate', v.point_estimate,
            'agentStatus', a.status,
            'versionStatus', v.status
        ))
    ),
    '10000000-0000-4000-8000-000000000011', CURRENT_TIMESTAMP
  FROM dianlian_business.enterprise_agent a
  JOIN dianlian_business.agent_version v ON v.agent_version_id = a.agent_version_id
 WHERE a.enterprise_agent_id = '10000000-0000-4000-8000-000000000123';

INSERT INTO dianlian_business.task_step
    (step_id, tenant_id, task_id, plan_version, step_key, title, status,
     executor_type, responsible_type, responsible_id, depends_on, input_contract, output_contract,
     human_checkpoint, blocker_code, step_order, created_at, updated_at)
VALUES
    ('90000000-0000-4000-8000-000000000011',
     '10000000-0000-4000-8000-000000000001',
     '90000000-0000-4000-8000-000000000001', 1,
     'understand', '理解报价需求', 'READY', 'MODEL', 'AGENT',
     '10000000-0000-4000-8000-000000000123', '[]'::jsonb,
     'quotation.request', 'quotation.normalized', FALSE, NULL, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('90000000-0000-4000-8000-000000000012',
     '10000000-0000-4000-8000-000000000001',
     '90000000-0000-4000-8000-000000000001', 1,
     'calculate', '计算报价方案', 'PENDING', 'RULE_ENGINE', 'AGENT',
     '10000000-0000-4000-8000-000000000123',
     '["90000000-0000-4000-8000-000000000011"]'::jsonb,
     'quotation.normalized', 'quotation.draft', FALSE, NULL, 2, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
    ('90000000-0000-4000-8000-000000000013',
     '10000000-0000-4000-8000-000000000001',
     '90000000-0000-4000-8000-000000000001', 1,
     'review', '确认报价结果', 'PENDING', 'HUMAN_CHECKPOINT', 'USER',
     '10000000-0000-4000-8000-000000000011',
     '["90000000-0000-4000-8000-000000000012"]'::jsonb,
     'quotation.draft', 'quotation.approved', TRUE, NULL, 3, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);

INSERT INTO dianlian_business.task_step_execution
    (task_step_id, tenant_id, execution_generation, runtime_run_id, status,
     idempotency_key, request_hash, next_attempt_at, created_at, updated_at)
VALUES
    ('90000000-0000-4000-8000-000000000011',
     '10000000-0000-4000-8000-000000000001', 1,
     '90000000-0000-4000-8000-000000000021', 'PREPARED',
     'task-step:90000000-0000-4000-8000-000000000001:90000000-0000-4000-8000-000000000011:1',
     'local-smoke-request-hash', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);

UPDATE dianlian_business.task_step
   SET active_execution_generation = 1,
       active_runtime_run_id = '90000000-0000-4000-8000-000000000021',
       updated_at = CURRENT_TIMESTAMP
 WHERE tenant_id = '10000000-0000-4000-8000-000000000001'
   AND step_id = '90000000-0000-4000-8000-000000000011'
   AND status = 'READY'
   AND executor_type = 'MODEL';

INSERT INTO dianlian_business.task_participant
    (task_id, tenant_id, user_id, participant_role, status, granted_by, created_at)
VALUES
    ('90000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000011',
     'OWNER', 'ACTIVE', '10000000-0000-4000-8000-000000000011', CURRENT_TIMESTAMP);

INSERT INTO dianlian_business.task_target
    (task_id, tenant_id, enterprise_agent_id, agent_version_id, target_role,
     target_order, capability_code, execution_template_code, execution_template_version,
     estimated_point_cost, created_at)
VALUES
    ('90000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000001',
     '10000000-0000-4000-8000-000000000123',
     '10000000-0000-4000-8000-000000000113',
     'PRIMARY', 1, 'QUOTATION', 'quotation.v1', '1.0.0', 350000000, CURRENT_TIMESTAMP);

INSERT INTO dianlian_business.task_input_snapshot
    (input_snapshot_id, tenant_id, task_id, plan_version, schema_id, schema_version,
     request_hash, input_payload, created_by, created_at)
VALUES
    ('90000000-0000-4000-8000-000000000014',
     '10000000-0000-4000-8000-000000000001',
     '90000000-0000-4000-8000-000000000001', 1,
     'quotation.request', '1.0.0', 'local-smoke-request-hash',
     '{"goal":"根据需求形成一份可复核的报价成果","capabilityInput":{"schemaId":"quotation.request","schemaVersion":"1.0.0","values":{"requirements":"本地 Golden Slice 报价测试"}}}'::jsonb,
     '10000000-0000-4000-8000-000000000011', CURRENT_TIMESTAMP);

INSERT INTO dianlian_business.task_business_trace
    (trace_item_id, tenant_id, task_id, trace_type, responsible_type,
     responsible_id, summary, reference_ids, occurred_at)
VALUES
    ('90000000-0000-4000-8000-000000000015',
     '10000000-0000-4000-8000-000000000001',
     '90000000-0000-4000-8000-000000000001',
     'GOAL_CONFIRMED', 'USER', '10000000-0000-4000-8000-000000000011',
     'Task goal confirmed', '[]'::jsonb, CURRENT_TIMESTAMP),
    ('90000000-0000-4000-8000-000000000016',
     '10000000-0000-4000-8000-000000000001',
     '90000000-0000-4000-8000-000000000001',
     'PLAN_CREATED', 'SYSTEM', '90000000-0000-4000-8000-000000000001',
     'Initial execution plan created from the employee execution profile',
     '["90000000-0000-4000-8000-000000000011","90000000-0000-4000-8000-000000000012","90000000-0000-4000-8000-000000000013"]'::jsonb,
     CURRENT_TIMESTAMP);

INSERT INTO dianlian_business.outbox_event
    (event_id, tenant_id, aggregate_type, aggregate_id, event_type, payload, occurred_at)
VALUES
    ('90000000-0000-4000-8000-000000000006',
     '10000000-0000-4000-8000-000000000001',
     'TASK', '90000000-0000-4000-8000-000000000001', 'task.started',
     '{"taskId":"90000000-0000-4000-8000-000000000001","taskStatus":"QUEUED","allowedActions":["VIEW","ADD_CONTEXT","CORRECT_FACT","CHANGE_CONSTRAINT","STYLE_GUIDANCE","PAUSE","CANCEL"]}'::jsonb,
     CURRENT_TIMESTAMP);

INSERT INTO dianlian_business.task_event
    (event_id, tenant_id, task_id, task_version, event_type, visibility_version,
     trace_id, payload, occurred_at)
VALUES
    ('90000000-0000-4000-8000-000000000006',
     '10000000-0000-4000-8000-000000000001',
     '90000000-0000-4000-8000-000000000001', 1, 'task.started',
     'task-participants:v1', '90000000-0000-4000-8000-000000000006',
     '{"taskId":"90000000-0000-4000-8000-000000000001","taskStatus":"QUEUED","allowedActions":["VIEW","ADD_CONTEXT","CORRECT_FACT","CHANGE_CONSTRAINT","STYLE_GUIDANCE","PAUSE","CANCEL"]}'::jsonb,
     CURRENT_TIMESTAMP);

UPDATE dianlian_business.idempotency_record
   SET resource_type = 'TASK',
       resource_id = '90000000-0000-4000-8000-000000000001',
       response_http_status = 202,
       response_payload = '{"taskId":"90000000-0000-4000-8000-000000000001","taskVersion":1,"status":"QUEUED","acceptedAt":"2026-01-01T00:00:00Z","statusUrl":"/api/v1/tasks/90000000-0000-4000-8000-000000000001","eventsUrl":"/api/v1/tasks/90000000-0000-4000-8000-000000000001/events","resumeEventId":"90000000-0000-4000-8000-000000000006"}'::jsonb,
       completed_at = CURRENT_TIMESTAMP
 WHERE tenant_id = '10000000-0000-4000-8000-000000000001'
   AND actor_id = '10000000-0000-4000-8000-000000000011'
   AND operation = 'TASK_CREATE'
   AND idempotency_key = 'local-smoke:create:quotation';

SET CONSTRAINTS ALL IMMEDIATE;

DO $verify_task$
DECLARE
    actual_count BIGINT;
    estimated_cost BIGINT;
BEGIN
    -- Same visibility predicate used by the Office task query.
    SELECT COUNT(*), COALESCE(SUM(tt.estimated_point_cost), 0)
      INTO actual_count, estimated_cost
      FROM dianlian_business.task_run tr
      JOIN dianlian_business.point_reservation pr
        ON pr.tenant_id = tr.tenant_id
       AND pr.reservation_id = tr.point_reservation_id
      JOIN dianlian_business.task_target tt
        ON tt.tenant_id = tr.tenant_id
       AND tt.task_id = tr.task_id
     WHERE tr.tenant_id = '10000000-0000-4000-8000-000000000001'
       AND tr.task_id = '90000000-0000-4000-8000-000000000001'
       AND EXISTS (
           SELECT 1
             FROM dianlian_business.task_participant participant
            WHERE participant.tenant_id = tr.tenant_id
              AND participant.task_id = tr.task_id
              AND participant.user_id = '10000000-0000-4000-8000-000000000011'
              AND participant.status = 'ACTIVE'
       );
    IF actual_count <> 1 OR estimated_cost <> 350000000 THEN
        RAISE EXCEPTION 'Office/Task visibility query could not read the smoke task';
    END IF;

    SELECT COUNT(*) INTO actual_count
      FROM dianlian_business.task_step
     WHERE tenant_id = '10000000-0000-4000-8000-000000000001'
       AND task_id = '90000000-0000-4000-8000-000000000001'
       AND plan_version = 1;
    IF actual_count <> 3 THEN
        RAISE EXCEPTION 'smoke task execution plan is incomplete';
    END IF;

    SELECT COUNT(*) INTO actual_count
      FROM dianlian_business.task_step_execution execution
      JOIN dianlian_business.task_step step
        ON step.tenant_id = execution.tenant_id
       AND step.step_id = execution.task_step_id
     WHERE execution.tenant_id = '10000000-0000-4000-8000-000000000001'
       AND step.task_id = '90000000-0000-4000-8000-000000000001'
       AND step.executor_type = 'MODEL'
       AND step.active_execution_generation = execution.execution_generation
       AND step.active_runtime_run_id = execution.runtime_run_id
       AND execution.status = 'PREPARED';
    IF actual_count <> 1 THEN
        RAISE EXCEPTION 'smoke task MODEL step has no fenced PREPARED execution';
    END IF;

    SELECT COUNT(*) INTO actual_count
      FROM dianlian_business.task_event
     WHERE tenant_id = '10000000-0000-4000-8000-000000000001'
       AND task_id = '90000000-0000-4000-8000-000000000001'
       AND event_id = '90000000-0000-4000-8000-000000000006'
       AND event_type = 'task.started';
    IF actual_count <> 1 THEN
        RAISE EXCEPTION 'smoke task durable event cursor is missing';
    END IF;

    SELECT COUNT(*) INTO actual_count
      FROM dianlian_business.point_ledger_entry
     WHERE transaction_id = '90000000-0000-4000-8000-000000000003';
    IF actual_count <> 2 THEN
        RAISE EXCEPTION 'smoke task reservation ledger is incomplete';
    END IF;
END
$verify_task$;

SELECT 'golden_slice_smoke_ok' AS result,
       3 AS executable_employee_count,
       1 AS rolled_back_task_count;

ROLLBACK;
