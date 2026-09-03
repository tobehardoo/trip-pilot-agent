package io.github.tobehardoo.trippilot.itinerary;

import java.util.Optional;
import java.util.UUID;

import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

/**
 * Persisted planning-decision explanations for an itinerary version (③ 决策解释上屏).
 *
 * The decisions are the remapped {@code evaluation.decisions} (a JSON array) of the
 * planning completion that produced the version, captured at create/replan/candidate
 * time.  User-edit and rollback versions carry no decision row, which the read model
 * surfaces as an absent (empty) explanation — never a fabricated one.
 */
@Mapper
public interface ItineraryPlanningDecisionMapper {

    @Insert("""
            INSERT INTO business.itinerary_planning_decision(
                itinerary_version_id, decisions_json
            ) VALUES (
                #{itineraryVersionId}, CAST(#{decisionsJson} AS jsonb)
            )
            """)
    int insert(
            @Param("itineraryVersionId") UUID itineraryVersionId,
            @Param("decisionsJson") String decisionsJson
    );

    @Select("""
            SELECT decisions_json::text AS decisions_json
            FROM business.itinerary_planning_decision
            WHERE itinerary_version_id = #{itineraryVersionId}
            """)
    Optional<String> findDecisionsJson(@Param("itineraryVersionId") UUID itineraryVersionId);
}