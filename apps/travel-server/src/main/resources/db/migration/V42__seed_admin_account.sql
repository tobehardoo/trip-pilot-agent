-- Seeded administrator account for local/demo environments.
-- Login: admin@admin.com  Password: Admin123456  (documented in README 演示账号)
-- The password hash matches SecurityConfig's BCryptPasswordEncoder.
-- Seeded here (instead of registered) so a fresh database always has a
-- working demo account; rotation is expected before any public deployment.
INSERT INTO business.user_account (id, email, password_hash, display_name)
VALUES (gen_random_uuid(),
        'admin@admin.com',
        '$2a$10$/eu43icNPNLc9mKh7zRSheQbFVEGUL3FmqxuOWkYRFPvpYS35oT8i',
        '管理员')
ON CONFLICT (email) DO NOTHING;
