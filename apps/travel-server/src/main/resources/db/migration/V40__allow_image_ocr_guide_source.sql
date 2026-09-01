ALTER TABLE business.guide_import
    DROP CONSTRAINT IF EXISTS guide_import_source_type_check;

ALTER TABLE business.guide_import
    ADD CONSTRAINT guide_import_source_type_check
    CHECK (
        source_type IN (
            'PUBLIC_GUIDE_URL',
            'PASTED_TEXT',
            'TEXT_FILE',
            'XIAOHONGSHU_SHARED_TEXT',
            'IMAGE_OCR',
            'CITY_INTELLIGENCE',
            'OFFICIAL_TOURISM',
            'OFFICIAL_ATTRACTION'
        )
    );
