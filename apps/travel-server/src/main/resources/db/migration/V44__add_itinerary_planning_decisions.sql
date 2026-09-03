-- ③ 决策解释上屏:每行程版本持久化规划引擎的决策说明(evaluation.decisions)。
--
-- 与 itinerary_feasibility_report 对齐:一个不可变行程版本至多一条决策记录,
-- 内容为决策解释 JSON 数组(jsonb array)。旧版本/用户手工编辑版本取消关联,
-- 因此不会写入此行(前端按版本读 null -> 不展示任何说明,避免伪造)。
CREATE TABLE business.itinerary_planning_decision (
    itinerary_version_id UUID PRIMARY KEY
        REFERENCES business.itinerary_version(id) ON DELETE CASCADE,
    decisions_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE business.itinerary_planning_decision
    ADD CONSTRAINT ck_ipd_decisions_json_array
    CHECK (jsonb_typeof(decisions_json) = 'array');