package io.github.tobehardoo.trippilot.infrastructure.mq;

import java.nio.charset.StandardCharsets;
import java.util.UUID;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import io.github.tobehardoo.trippilot.support.PlanningCompletedEventFixture;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class PlanningReviewRequiredEventParserTest {

    private final ObjectMapper objectMapper = new ObjectMapper().findAndRegisterModules();
    private final PlanningReviewRequiredEventParser parser =
            new PlanningReviewRequiredEventParser(objectMapper);

    @Test
    void parsesSharedReviewFixtureAndPreservesReport() {
        PlanningReviewRequiredEvent event = parser.parse(bytes(
                PlanningCompletedEventFixture.sharedReviewV1Fixture(
                        "review-v1-unverified-demo.json"
                )
        ));

        assertThat(event.schemaVersion()).isEqualTo(1);
        assertThat(event.payload().status()).isEqualTo("WAITING_USER");
        io.github.tobehardoo.trippilot.feasibility.FeasibilityReport report =
                event.payload().feasibilityReport();
        assertThat(report.status())
                .isEqualTo(io.github.tobehardoo.trippilot.feasibility.FeasibilityStatus.UNVERIFIED);
        assertThat(report.schemaVersion()).isEqualTo(1);
        assertThat(report.itineraryFingerprint())
                .isEqualTo("dce5e94d5981b3ffec3a0aff9dcfc29245d874552e863f4b432a47985bc7d025");
        assertThat(report.ruleResults()).hasSize(11);
        assertThat(event.payload().itinerary().days().get(0).transitLegs()).hasSize(1);
    }

    @Test
    void rejectsMissingFeasibilityReport() throws Exception {
        ObjectNode event = sharedReviewEvent();
        ((ObjectNode) event.at("/payload")).remove("feasibilityReport");

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("feasibilityReport field types do not match");
    }

    @Test
    void rejectsEvaluationInReviewPayload() throws Exception {
        ObjectNode event = sharedReviewEvent();
        ((ObjectNode) event.at("/payload")).putObject("evaluation");

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("evaluation is not allowed");
    }

    @Test
    void rejectsVerifiedReportStatus() throws Exception {
        ObjectNode event = sharedReviewEvent();
        ((ObjectNode) event.at("/payload/feasibilityReport")).put("status", "VERIFIED");

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("feasibilityReport is invalid: status must be UNVERIFIED");
    }

    @Test
    void acceptsNeedsRepairReportStatus() throws Exception {
        PlanningReviewRequiredEvent parsed = parser.parse(bytes(
                PlanningCompletedEventFixture.sharedReviewV1Fixture(
                        "review-v1-needs-repair-demo.json"
                )
        ));

        io.github.tobehardoo.trippilot.feasibility.FeasibilityReport report =
                parsed.payload().feasibilityReport();
        assertThat(report.status())
                .isEqualTo(io.github.tobehardoo.trippilot.feasibility.FeasibilityStatus.NEEDS_REPAIR);
        assertThat(report.ruleResults()).anyMatch(
                r -> r.outcome() == io.github.tobehardoo.trippilot.feasibility.RuleOutcome.FAIL);
        assertThat(report.repairAttempts()).isNotEmpty();
        assertThat(report.repairAttempts().get(0).attemptIndex()).isEqualTo(1);
    }

    @Test
    void rejectsMismatchedItineraryFingerprint() throws Exception {
        ObjectNode event = sharedReviewEvent();
        ((ObjectNode) event.at("/payload/feasibilityReport"))
                .put("itineraryFingerprint", "0".repeat(64));

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("itineraryFingerprint does not match the itinerary");
    }

    @Test
    void rejectsNonWaitingUserStatus() throws Exception {
        ObjectNode event = sharedReviewEvent();
        ((ObjectNode) event.at("/payload")).put("status", "REVIEWING");

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("status must be WAITING_USER");
    }

    @Test
    void rejectsSchemaVersionNotOne() throws Exception {
        ObjectNode event = sharedReviewEvent();
        event.put("schemaVersion", 2);

        assertThatThrownBy(() -> parser.parse(objectMapper.writeValueAsBytes(event)))
                .isInstanceOf(PlanningEventContractException.class)
                .hasMessageContaining("unsupported eventType or schemaVersion");
    }

    private ObjectNode sharedReviewEvent() throws Exception {
        return (ObjectNode) objectMapper.readTree(
                PlanningCompletedEventFixture.sharedReviewV1Fixture(
                        "review-v1-unverified-demo.json"
                )
        );
    }

    private byte[] bytes(String value) {
        return value.getBytes(StandardCharsets.UTF_8);
    }
}
