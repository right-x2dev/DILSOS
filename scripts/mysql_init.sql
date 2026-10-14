-- One-time local MySQL 8 setup for DILSOS (run as root in MySQL Workbench / mysql shell):
--   mysql -u root -p < scripts/mysql_init.sql
-- Creates an application database + least-privilege app user, and a separate test schema.
-- Development-only password; change it for any shared environment and update backend/.env.

CREATE DATABASE IF NOT EXISTS dilsos CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE DATABASE IF NOT EXISTS dilsos_test CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE USER IF NOT EXISTS 'dilsos'@'localhost' IDENTIFIED BY 'dilsos_dev_pw';
-- Least privilege: DML + DDL needed by Alembic migrations on the app schemas only.
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, INDEX, REFERENCES
  ON dilsos.* TO 'dilsos'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, INDEX, REFERENCES
  ON dilsos_test.* TO 'dilsos'@'localhost';
FLUSH PRIVILEGES;
