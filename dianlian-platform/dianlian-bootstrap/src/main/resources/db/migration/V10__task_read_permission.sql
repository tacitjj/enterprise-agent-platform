INSERT INTO dianlian_business.iam_permission (permission_code, display_name, status)
VALUES ('task.read', '查看任务及任务动态', 'ACTIVE')
ON CONFLICT (permission_code) DO NOTHING;
