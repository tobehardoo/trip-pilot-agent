CREATE TABLE business.city_source_registry (
    id UUID PRIMARY KEY,
    city_code VARCHAR(32) NOT NULL,
    city_name VARCHAR(120) NOT NULL,
    source_name VARCHAR(200) NOT NULL,
    source_url VARCHAR(2048) NOT NULL,
    source_type VARCHAR(40) NOT NULL
        CHECK (source_type IN ('OFFICIAL_TOURISM', 'OFFICIAL_ATTRACTION')),
    reliability_level VARCHAR(20) NOT NULL
        CHECK (reliability_level IN ('AUTHORITATIVE', 'TRUSTED', 'COMMUNITY')),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    parser_strategy VARCHAR(80) NOT NULL,
    refresh_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
    review_status VARCHAR(20) NOT NULL DEFAULT 'PENDING'
        CHECK (review_status IN ('PENDING', 'APPROVED', 'REJECTED')),
    review_note VARCHAR(1000),
    reviewed_by UUID,
    reviewed_at TIMESTAMPTZ,
    version INTEGER NOT NULL DEFAULT 0 CHECK (version >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT city_source_registry_city_url_unique UNIQUE (city_code, source_url),
    CONSTRAINT city_source_registry_review_audit_check CHECK (
        (review_status = 'PENDING' AND reviewed_at IS NULL)
        OR (review_status <> 'PENDING' AND reviewed_at IS NOT NULL)
    )
);

CREATE INDEX city_source_registry_active_city_idx
    ON business.city_source_registry(city_code, review_status, enabled);

INSERT INTO business.city_source_registry(
    id, city_code, city_name, source_name, source_url, source_type,
    reliability_level, enabled, parser_strategy, refresh_policy,
    review_status, review_note, reviewed_at
) VALUES
    (
        '5ac741ee-0e31-4e26-9000-000000000001',
        'CN-GD-GZ', '广州', '广州市文化广电旅游局',
        'https://wglj.gz.gov.cn/', 'OFFICIAL_TOURISM',
        'AUTHORITATIVE', TRUE, 'OFFICIAL_PORTAL',
        '{"mode":"SCHEDULED","interval":"PT6H","staleGrace":"P1D"}',
        'APPROVED', 'V1.3 pilot source verified against the official government portal',
        CURRENT_TIMESTAMP
    ),
    (
        '5ac741ee-0e31-4e26-9000-000000000002',
        'CN-GD-GZ', '广州', '广州博物馆',
        'https://www.guangzhoumuseum.cn/website_cn/Web/Visit/VisitGuide.aspx',
        'OFFICIAL_ATTRACTION', 'AUTHORITATIVE', TRUE, 'ATTRACTION_VISIT_PAGE',
        '{"mode":"SCHEDULED","interval":"PT3H","staleGrace":"PT12H"}',
        'APPROVED', 'V1.3 pilot source verified against the museum visit guide',
        CURRENT_TIMESTAMP
    ),
    (
        '5ac741ee-0e31-4e26-9000-000000000003',
        'CN-BJ', '北京', '北京市文化和旅游局',
        'https://whlyj.beijing.gov.cn/', 'OFFICIAL_TOURISM',
        'AUTHORITATIVE', TRUE, 'OFFICIAL_PORTAL',
        '{"mode":"SCHEDULED","interval":"PT6H","staleGrace":"P1D"}',
        'APPROVED', 'V1.3 pilot source verified against the official government portal',
        CURRENT_TIMESTAMP
    ),
    (
        '5ac741ee-0e31-4e26-9000-000000000004',
        'CN-BJ', '北京', '故宫博物院参观导览',
        'https://www.dpm.org.cn/Visit.html', 'OFFICIAL_ATTRACTION',
        'AUTHORITATIVE', TRUE, 'ATTRACTION_VISIT_PAGE',
        '{"mode":"SCHEDULED","interval":"PT3H","staleGrace":"PT12H"}',
        'APPROVED', 'V1.3 pilot source verified against the museum visit guide',
        CURRENT_TIMESTAMP
    ),
    (
        '5ac741ee-0e31-4e26-9000-000000000005',
        'CN-SH', '上海', '上海市文化和旅游局',
        'https://whlyj.sh.gov.cn/', 'OFFICIAL_TOURISM',
        'AUTHORITATIVE', TRUE, 'OFFICIAL_PORTAL',
        '{"mode":"SCHEDULED","interval":"PT6H","staleGrace":"P1D"}',
        'APPROVED', 'V1.3 pilot source verified against the official government portal',
        CURRENT_TIMESTAMP
    ),
    (
        '5ac741ee-0e31-4e26-9000-000000000006',
        'CN-SH', '上海', '上海博物馆东馆参观信息',
        'https://www.shanghaimuseum.net/mu/frontend/pg/m/service/visit-east',
        'OFFICIAL_ATTRACTION', 'AUTHORITATIVE', TRUE, 'ATTRACTION_VISIT_PAGE',
        '{"mode":"SCHEDULED","interval":"PT3H","staleGrace":"PT12H"}',
        'APPROVED', 'V1.3 pilot source verified against the museum visit guide',
        CURRENT_TIMESTAMP
    );
