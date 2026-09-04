-- 用户自建的第三方 API 配置（天气/高德/知识库嵌入/规划等）
-- provider 取值：WEATHER / AMAP / KNOWLEDGE / PLANNER
CREATE TABLE IF NOT EXISTS user_api_config (
    user_id      UUID        NOT NULL,
    provider     TEXT        NOT NULL,
    api_key      TEXT,
    api_base_url TEXT,
    model        TEXT,
    updated_at   TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (user_id, provider)
);