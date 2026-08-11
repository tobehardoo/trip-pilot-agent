package io.github.tobehardoo.trippilot.itinerary;

import java.util.Optional;
import java.util.UUID;

import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface ItineraryFeasibilityReportMapper {

    @Insert("""
            INSERT INTO business.itinerary_feasibility_report(
                itinerary_version_id, report_id, schema_version,
                validator_version, itinerary_fingerprint, status,
                validated_at, report_json
            ) VALUES (
                #{itineraryVersionId}, #{reportId}, #{schemaVersion},
                #{validatorVersion}, #{itineraryFingerprint}, #{status},
                #{validatedAt}, CAST(#{reportJson} AS jsonb)
            )
            """)
    int insert(ItineraryFeasibilityReportRecord record);

    @Select("""
            SELECT itinerary_version_id, report_id, schema_version,
                   validator_version, itinerary_fingerprint, status,
                   validated_at, report_json::text AS report_json
            FROM business.itinerary_feasibility_report
            WHERE itinerary_version_id = #{itineraryVersionId}
            """)
    Optional<ItineraryFeasibilityReportRecord> findByItineraryVersionId(
            @Param("itineraryVersionId") UUID itineraryVersionId);
}
