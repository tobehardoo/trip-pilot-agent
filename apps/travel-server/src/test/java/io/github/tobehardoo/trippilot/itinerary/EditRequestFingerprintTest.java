package io.github.tobehardoo.trippilot.itinerary;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class EditRequestFingerprintTest {

    private final ObjectMapper objectMapper = new ObjectMapper();
    private final EditRequestFingerprint fingerprint = new EditRequestFingerprint(objectMapper);

    @Test
    void ignoresJsonObjectFieldOrderButRetainsTheMeaningOfEachBusinessField() throws Exception {
        UUID versionId = UUID.randomUUID();
        UUID activityId = UUID.randomUUID();
        String first = """
                {"baseVersionId":"%s","operation":"LOCK_ACTIVITY","activityId":"%s"}
                """.formatted(versionId, activityId);
        String reordered = """
                {"activityId":"%s","operation":"LOCK_ACTIVITY","baseVersionId":"%s"}
                """.formatted(activityId, versionId);
        String changed = """
                {"baseVersionId":"%s","operation":"UNLOCK_ACTIVITY","activityId":"%s"}
                """.formatted(versionId, activityId);

        assertThat(fingerprint.forEdit(objectMapper.readTree(first)))
                .isEqualTo(fingerprint.forEdit(objectMapper.readTree(reordered)))
                .isNotEqualTo(fingerprint.forEdit(objectMapper.readTree(changed)));
    }

    @Test
    void distinguishesAbsentNullAndEmptyBusinessValues() throws Exception {
        UUID versionId = UUID.randomUUID();
        String absent = """
                {"baseVersionId":"%s","operation":"LOCK_ACTIVITY"}
                """.formatted(versionId);
        String nullValue = """
                {"baseVersionId":"%s","operation":"LOCK_ACTIVITY","activityId":null}
                """.formatted(versionId);
        String emptyValue = """
                {"baseVersionId":"%s","operation":"LOCK_ACTIVITY","activityId":""}
                """.formatted(versionId);

        assertThat(fingerprint.forEdit(objectMapper.readTree(absent)))
                .isNotEqualTo(fingerprint.forEdit(objectMapper.readTree(nullValue)))
                .isNotEqualTo(fingerprint.forEdit(objectMapper.readTree(emptyValue)));
    }

    @Test
    void preservesTheOrderOfBatchEdits() throws Exception {
        UUID versionId = UUID.randomUUID();
        UUID firstActivity = UUID.randomUUID();
        UUID secondActivity = UUID.randomUUID();
        String forward = """
                {"baseVersionId":"%s","edits":[
                  {"baseVersionId":"%s","operation":"LOCK_ACTIVITY","activityId":"%s"},
                  {"baseVersionId":"%s","operation":"UNLOCK_ACTIVITY","activityId":"%s"}
                ]}
                """.formatted(versionId, versionId, firstActivity, versionId, secondActivity);
        String reversed = """
                {"baseVersionId":"%s","edits":[
                  {"baseVersionId":"%s","operation":"UNLOCK_ACTIVITY","activityId":"%s"},
                  {"baseVersionId":"%s","operation":"LOCK_ACTIVITY","activityId":"%s"}
                ]}
                """.formatted(versionId, versionId, secondActivity, versionId, firstActivity);

        assertThat(fingerprint.forBatch(objectMapper.readTree(forward)))
                .isNotEqualTo(fingerprint.forBatch(objectMapper.readTree(reversed)));
    }

    @Test
    void distinguishesAbsentNullAndEmptyBatchEditLists() throws Exception {
        UUID versionId = UUID.randomUUID();
        String absent = """
                {"baseVersionId":"%s"}
                """.formatted(versionId);
        String nullValue = """
                {"baseVersionId":"%s","edits":null}
                """.formatted(versionId);
        String emptyArray = """
                {"baseVersionId":"%s","edits":[]}
                """.formatted(versionId);

        assertThat(fingerprint.forBatch(objectMapper.readTree(absent)))
                .isNotEqualTo(fingerprint.forBatch(objectMapper.readTree(nullValue)))
                .isNotEqualTo(fingerprint.forBatch(objectMapper.readTree(emptyArray)));
    }
}
