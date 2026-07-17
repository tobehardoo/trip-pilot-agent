ALTER TABLE business.activity
    ADD COLUMN provider_poi_id VARCHAR(100),
    ADD COLUMN longitude NUMERIC(10, 7),
    ADD COLUMN latitude NUMERIC(10, 7),
    ADD COLUMN address VARCHAR(300),
    ADD CONSTRAINT ck_activity_coordinates_pair CHECK (
        (longitude IS NULL AND latitude IS NULL)
        OR (longitude IS NOT NULL AND latitude IS NOT NULL)
    ),
    ADD CONSTRAINT ck_activity_longitude CHECK (
        longitude IS NULL OR longitude BETWEEN -180 AND 180
    ),
    ADD CONSTRAINT ck_activity_latitude CHECK (
        latitude IS NULL OR latitude BETWEEN -90 AND 90
    ),
    ADD CONSTRAINT ck_activity_provider_metadata CHECK (
        (
            source = 'DEMO'
            AND provider_poi_id IS NULL
            AND longitude IS NULL
            AND latitude IS NULL
            AND address IS NULL
        )
        OR (
            source = 'AMAP'
            AND provider_poi_id IS NOT NULL
            AND BTRIM(provider_poi_id) <> ''
            AND longitude IS NOT NULL
            AND latitude IS NOT NULL
            AND address IS NOT NULL
            AND BTRIM(address) <> ''
        )
    );
