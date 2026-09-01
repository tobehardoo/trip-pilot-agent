ALTER TABLE business.guide_import
    ADD COLUMN source_type VARCHAR(40) NOT NULL DEFAULT 'PUBLIC_GUIDE_URL'
        CHECK (
            source_type IN (
                'PUBLIC_GUIDE_URL',
                'PASTED_TEXT',
                'TEXT_FILE',
                'XIAOHONGSHU_SHARED_TEXT',
                'CITY_INTELLIGENCE'
            )
        );

ALTER TABLE business.guide_fact
    DROP CONSTRAINT guide_fact_category_check;

ALTER TABLE business.guide_fact
    ADD CONSTRAINT guide_fact_category_check CHECK (
        category IN (
            'ATTRACTION', 'DINING', 'TRANSPORT', 'TIMING',
            'COST', 'QUEUE', 'RESERVATION', 'LOCATION',
            'WEATHER', 'TIP'
        )
    );
