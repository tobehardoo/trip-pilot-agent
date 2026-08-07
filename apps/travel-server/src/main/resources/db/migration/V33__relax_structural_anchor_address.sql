-- V33: allow structural AMap anchors (arrival/departure/hotel/meal) to carry a
-- provider id + coordinate pair without a street address.
--
-- AMap omits street addresses for many stations and airports, and the address
-- is a display-only field. The anchor contract is the provider id + coordinate
-- pair, so the address must be optional for structural kinds. Non-structural
-- activities keep the strict full-metadata requirement (candidates without an
-- address are already rejected upstream).

ALTER TABLE business.activity
    DROP CONSTRAINT ck_activity_provider_metadata;

ALTER TABLE business.activity
    ADD CONSTRAINT ck_activity_provider_metadata CHECK (
        (
            source = 'DEMO'
            AND provider_poi_id IS NULL AND longitude IS NULL
            AND latitude IS NULL AND address IS NULL
        )
        OR (
            source = 'AMAP'
            AND kind IN ('MEAL', 'ACCOMMODATION', 'ARRIVAL', 'DEPARTURE')
            AND (
                (
                    provider_poi_id IS NULL AND longitude IS NULL
                    AND latitude IS NULL AND address IS NULL
                )
                OR (
                    provider_poi_id IS NOT NULL AND BTRIM(provider_poi_id) <> ''
                    AND longitude IS NOT NULL AND latitude IS NOT NULL
                )
            )
        )
        OR (
            source = 'AMAP'
            AND (kind IS NULL OR kind NOT IN ('MEAL', 'ACCOMMODATION', 'ARRIVAL', 'DEPARTURE'))
            AND provider_poi_id IS NOT NULL AND BTRIM(provider_poi_id) <> ''
            AND longitude IS NOT NULL AND latitude IS NOT NULL
            AND address IS NOT NULL AND BTRIM(address) <> ''
        )
    );
