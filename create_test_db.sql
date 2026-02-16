SELECT 'CREATE DATABASE runbook_test'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'runbook_test')\\gexec
