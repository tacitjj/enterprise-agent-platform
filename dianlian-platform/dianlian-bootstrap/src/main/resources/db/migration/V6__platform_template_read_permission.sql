INSERT INTO dianlian_business.iam_permission (permission_code, display_name, status)
VALUES ('platform.employee.template.read', '查看数字员工模板版本', 'ACTIVE')
ON CONFLICT (permission_code) DO NOTHING;
