-- 每文档治理：声明其支持的断言类别（factual attribute / recommendation / preference）。
-- 仅 OFFICIAL 可支撑事实类断言（营业时间/票价/预约规则）；COMMUNITY/CURATED
-- 只能支撑推荐类信号。reliability_level 参与可信度排序（guide_fact_bonus）。
ALTER TABLE agent.knowledge_document
    ADD COLUMN IF NOT EXISTS claim_type TEXT NOT NULL DEFAULT 'RECOMMENDATION';

CREATE INDEX IF NOT EXISTS knowledge_document_claim_type_idx
    ON agent.knowledge_document (claim_type);