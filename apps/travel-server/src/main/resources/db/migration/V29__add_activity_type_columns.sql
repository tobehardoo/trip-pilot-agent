ALTER TABLE business.activity ADD COLUMN IF NOT EXISTS type_code VARCHAR(20);
ALTER TABLE business.activity ADD COLUMN IF NOT EXISTS type_name VARCHAR(50);
