-- 知识库两轴元数据：三级地区(region 省/市/区) + 板块(content_type)。
-- 文档级收地区，块级打板块，检索按 地区×板块 预过滤。

ALTER TABLE agent.knowledge_document
    ADD COLUMN IF NOT EXISTS region_province TEXT,
    ADD COLUMN IF NOT EXISTS region_city TEXT,
    ADD COLUMN IF NOT EXISTS region_district TEXT,
    ADD COLUMN IF NOT EXISTS content_type TEXT;

ALTER TABLE agent.knowledge_chunk
    ADD COLUMN IF NOT EXISTS content_type TEXT;

-- 文档地区索引（检索按 region 快速过滤）
CREATE INDEX IF NOT EXISTS knowledge_document_region_idx
    ON agent.knowledge_document (region_province, region_city, region_district);
CREATE INDEX IF NOT EXISTS knowledge_document_content_type_idx
    ON agent.knowledge_document (content_type);