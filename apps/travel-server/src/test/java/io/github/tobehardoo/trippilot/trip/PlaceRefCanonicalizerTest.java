package io.github.tobehardoo.trippilot.trip;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.math.BigDecimal;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.UUID;

import io.github.tobehardoo.trippilot.common.ApiException;
import io.github.tobehardoo.trippilot.place.PlaceSearchDtos.PlaceCandidate;
import io.github.tobehardoo.trippilot.place.PlaceSelectionTokenService;
import io.github.tobehardoo.trippilot.trip.TripRequests.PlaceRefInput;
import org.junit.jupiter.api.Test;

class PlaceRefCanonicalizerTest {

    private static final UUID OWNER = UUID.fromString("10000000-0000-4000-8000-000000000001");
    private static final UUID OTHER = UUID.fromString("20000000-0000-4000-8000-000000000002");
    private static final String DESTINATION = "广州市";
    private static final String OTHER_CITY = "北京市";

    private static final PlaceCandidate CANDIDATE = new PlaceCandidate(
            "AMAP", "B001234567", "陈家祠", "广州市荔湾区中山七路恩龙里34号",
            "广东省", "广州市", "荔湾区", 113.2405, 23.1256, false, null);

    private static PlaceRefInput ref(String token) {
        return new PlaceRefInput(
                "AMAP", "B001234567", "陈家祠", "广州市荔湾区中山七路恩龙里34号",
                "广东省", "广州市", "荔湾区",
                new BigDecimal("113.2405"), new BigDecimal("23.1256"), token);
    }

    private static PlaceSelectionTokenService tokens(Instant now) {
        return new PlaceSelectionTokenService(Clock.fixed(now, ZoneOffset.UTC));
    }

    private static final Instant NOW = Instant.parse("2026-08-01T00:00:00Z");

    @Test
    void canonicalizesRefWithValidTokenIgnoringForgedFields() {
        PlaceSelectionTokenService tokens = tokens(NOW);
        PlaceRefCanonicalizer canonicalizer = new PlaceRefCanonicalizer(tokens);
        String token = tokens.issue(OWNER, CANDIDATE);

        // The client forges a wrong name, address and coordinates; the
        // server must rebuild the ref from the cached candidate.
        PlaceRefInput forged = new PlaceRefInput(
                "AMAP", "B001234567", "伪造名称", "伪造地址", "假省", "假市", "假区",
                new BigDecimal("1.0"), new BigDecimal("2.0"), token);

        List<PlaceRefInput> result = canonicalizer.canonicalize(OWNER, List.of(forged), List.of(), DESTINATION);

        assertThat(result).hasSize(1);
        assertThat(result.get(0).name()).isEqualTo("陈家祠");
        assertThat(result.get(0).address()).isEqualTo("广州市荔湾区中山七路恩龙里34号");
        assertThat(result.get(0).province()).isEqualTo("广东省");
        assertThat(result.get(0).city()).isEqualTo("广州市");
        assertThat(result.get(0).district()).isEqualTo("荔湾区");
        assertThat(result.get(0).longitude()).isEqualByComparingTo("113.2405");
        assertThat(result.get(0).latitude()).isEqualByComparingTo("23.1256");
        assertThat(result.get(0).selectionToken()).isNull();
    }

    @Test
    void rejectsForgedToken() {
        PlaceSelectionTokenService tokens = tokens(NOW);
        PlaceRefCanonicalizer canonicalizer = new PlaceRefCanonicalizer(tokens);

        assertThatThrownBy(() -> canonicalizer.canonicalize(
                OWNER, List.of(ref("forged-token")), List.of(), DESTINATION))
                .isInstanceOf(ApiException.class)
                .satisfies(error -> {
                    ApiException api = (ApiException) error;
                    assertThat(api.code()).isEqualTo("PLACE_REF_TOKEN_INVALID");
                });
    }

    @Test
    void rejectsTokenIssuedToAnotherOwner() {
        PlaceSelectionTokenService tokens = tokens(NOW);
        PlaceRefCanonicalizer canonicalizer = new PlaceRefCanonicalizer(tokens);
        String token = tokens.issue(OTHER, CANDIDATE);

        assertThatThrownBy(() -> canonicalizer.canonicalize(
                OWNER, List.of(ref(token)), List.of(), DESTINATION))
                .isInstanceOf(ApiException.class)
                .satisfies(error -> {
                    ApiException api = (ApiException) error;
                    assertThat(api.code()).isEqualTo("PLACE_REF_TOKEN_INVALID");
                });
    }

    @Test
    void rejectsTokenWhoseCandidateDoesNotMatchTheRefIdentity() {
        PlaceSelectionTokenService tokens = tokens(NOW);
        PlaceRefCanonicalizer canonicalizer = new PlaceRefCanonicalizer(tokens);
        PlaceCandidate otherCandidate = new PlaceCandidate(
                "AMAP", "B999999999", "光孝寺", "addr", "广东省", "广州市", "越秀区",
                113.25, 23.13, false, null);
        String token = tokens.issue(OWNER, otherCandidate);

        assertThatThrownBy(() -> canonicalizer.canonicalize(
                OWNER, List.of(ref(token)), List.of(), DESTINATION))
                .isInstanceOf(ApiException.class)
                .satisfies(error -> {
                    ApiException api = (ApiException) error;
                    assertThat(api.code()).isEqualTo("PLACE_REF_TOKEN_INVALID");
                });
    }

    @Test
    void acceptsUnchangedPersistedRefWithoutToken() {
        PlaceSelectionTokenService tokens = tokens(NOW);
        PlaceRefCanonicalizer canonicalizer = new PlaceRefCanonicalizer(tokens);
        PlaceRefInput persisted = ref(null);

        List<PlaceRefInput> result = canonicalizer.canonicalize(
                OWNER, List.of(persisted), List.of(persisted), DESTINATION);

        assertThat(result).containsExactly(persisted);
    }

    @Test
    void rejectsNewRefWithoutToken() {
        PlaceSelectionTokenService tokens = tokens(NOW);
        PlaceRefCanonicalizer canonicalizer = new PlaceRefCanonicalizer(tokens);

        assertThatThrownBy(() -> canonicalizer.canonicalize(
                OWNER, List.of(ref(null)), List.of(), DESTINATION))
                .isInstanceOf(ApiException.class)
                .satisfies(error -> {
                    ApiException api = (ApiException) error;
                    assertThat(api.code()).isEqualTo("PLACE_REF_TOKEN_REQUIRED");
                });
    }

    @Test
    void rejectsChangedRefWithoutTokenEvenWhenAnotherRefIsPersisted() {
        PlaceSelectionTokenService tokens = tokens(NOW);
        PlaceRefCanonicalizer canonicalizer = new PlaceRefCanonicalizer(tokens);
        PlaceRefInput persisted = ref(null);
        PlaceRefInput changed = new PlaceRefInput(
                "AMAP", "B001234567", "陈家祠改名", "同址", "广东省", "广州市", "荔湾区",
                new BigDecimal("113.2405"), new BigDecimal("23.1256"), null);

        assertThatThrownBy(() -> canonicalizer.canonicalize(
                OWNER, List.of(changed), List.of(persisted), DESTINATION))
                .isInstanceOf(ApiException.class)
                .satisfies(error -> {
                    ApiException api = (ApiException) error;
                    assertThat(api.code()).isEqualTo("PLACE_REF_TOKEN_REQUIRED");
                });
    }

    @Test
    void rejectsTokenWhoseCandidateIsFromAnotherCity() {
        // B14_FIX R3 (D03): a selection token issued by a search in one city
        // must never be redeemed into a trip whose destination is another
        // city, even when every other field matches.
        PlaceSelectionTokenService tokens = tokens(NOW);
        PlaceRefCanonicalizer canonicalizer = new PlaceRefCanonicalizer(tokens);
        PlaceCandidate beijingCandidate = new PlaceCandidate(
                "AMAP", "B001234567", "陈家祠", "广州市荔湾区中山七路恩龙里34号",
                "广东省", "广州市", "荔湾区", 113.2405, 23.1256, false, null);
        String token = tokens.issue(OWNER, beijingCandidate);

        assertThatThrownBy(() -> canonicalizer.canonicalize(
                OWNER, List.of(ref(token)), List.of(), OTHER_CITY))
                .isInstanceOf(ApiException.class)
                .satisfies(error -> {
                    ApiException api = (ApiException) error;
                    assertThat(api.code()).isEqualTo("PLACE_REF_TOKEN_INVALID");
                });
    }

    @Test
    void acceptsTokenWhoseCandidateCityMatchesDestinationWithoutSuffix() {
        // Normalized comparison: destination "广州" (no suffix) must match a
        // candidate whose city is "广州市".
        PlaceSelectionTokenService tokens = tokens(NOW);
        PlaceRefCanonicalizer canonicalizer = new PlaceRefCanonicalizer(tokens);
        String token = tokens.issue(OWNER, CANDIDATE);

        List<PlaceRefInput> result = canonicalizer.canonicalize(
                OWNER, List.of(ref(token)), List.of(), "广州");

        assertThat(result).hasSize(1);
        assertThat(result.get(0).city()).isEqualTo("广州市");
    }


    // B14_FIX.1 R1: official administrative names must survive normalization.
    // 大理白族自治州 is the AMap cityname; stripping "自治州" would leave the
    // ethnic-suffix fragment "大理白族" — the previous normalizeCity bug.  The
    // canonical comparison uses the official RegionRef cityName, so the full
    // official name must match itself verbatim (no ethnic-name guessing).

    @Test
    void officialAutonomousPrefectureNameMatchesItselfVerbatim() throws Exception {
        PlaceSelectionTokenService tokens = tokens(NOW);
        PlaceRefCanonicalizer canonicalizer = new PlaceRefCanonicalizer(tokens);
        PlaceCandidate daliCandidate = new PlaceCandidate(
                "AMAP", "B001234567", "大理古城", "云南省大理白族自治州大理市古城路",
                "云南省", "大理白族自治州", "大理市", 100.1595, 25.7075, false, null);
        String token = tokens.issue(OWNER, daliCandidate);

        List<PlaceRefInput> result = canonicalizer.canonicalize(
                OWNER, List.of(ref(token)), List.of(), "大理白族自治州");

        assertThat(result).hasSize(1);
        assertThat(result.get(0).city()).isEqualTo("大理白族自治州");
    }

    @Test
    void officialXiangxiAutonomousPrefectureNameMatchesItselfVerbatim() throws Exception {
        PlaceSelectionTokenService tokens = tokens(NOW);
        PlaceRefCanonicalizer canonicalizer = new PlaceRefCanonicalizer(tokens);
        PlaceCandidate xiangxiCandidate = new PlaceCandidate(
                "AMAP", "B001234567", "凤凰古城", "湖南省湘西土家族苗族自治州凤凰县",
                "湖南省", "湘西土家族苗族自治州", "凤凰县", 109.5996, 27.9483, false, null);
        String token = tokens.issue(OWNER, xiangxiCandidate);

        List<PlaceRefInput> result = canonicalizer.canonicalize(
                OWNER, List.of(ref(token)), List.of(), "湘西土家族苗族自治州");

        assertThat(result).hasSize(1);
        assertThat(result.get(0).city()).isEqualTo("湘西土家族苗族自治州");
    }

    @Test
    void officialYanbianAutonomousPrefectureNameMatchesItselfVerbatim() throws Exception {
        PlaceSelectionTokenService tokens = tokens(NOW);
        PlaceRefCanonicalizer canonicalizer = new PlaceRefCanonicalizer(tokens);
        PlaceCandidate yanbianCandidate = new PlaceCandidate(
                "AMAP", "B001234567", "延吉帽儿山", "吉林省延边朝鲜族自治州延吉市",
                "吉林省", "延边朝鲜族自治州", "延吉市", 129.4694, 42.9166, false, null);
        String token = tokens.issue(OWNER, yanbianCandidate);

        List<PlaceRefInput> result = canonicalizer.canonicalize(
                OWNER, List.of(ref(token)), List.of(), "延边朝鲜族自治州");

        assertThat(result).hasSize(1);
        assertThat(result.get(0).city()).isEqualTo("延边朝鲜族自治州");
    }

    @Test
    void officialLeagueAndPrefectureSuffixesStillNormalize() throws Exception {
        // 阿拉善盟 -> 阿拉善 and 大兴安岭地区 -> 大兴安岭 remain valid
        // suffix-normalization cases (no ethnic fragment involved).
        PlaceSelectionTokenService tokens = tokens(NOW);
        PlaceRefCanonicalizer canonicalizer = new PlaceRefCanonicalizer(tokens);
        PlaceCandidate alxaCandidate = new PlaceCandidate(
                "AMAP", "B001234567", "阿拉善英雄会", "内蒙古自治区阿拉善盟",
                "内蒙古自治区", "阿拉善盟", "阿拉善左旗", 105.7289, 38.8516, false, null);
        String alxaToken = tokens.issue(OWNER, alxaCandidate);
        List<PlaceRefInput> alxaResult = canonicalizer.canonicalize(
                OWNER, List.of(ref(alxaToken)), List.of(), "阿拉善盟");
        assertThat(alxaResult).hasSize(1);
        assertThat(alxaResult.get(0).city()).isEqualTo("阿拉善盟");

        PlaceCandidate dxalCandidate = new PlaceCandidate(
                "AMAP", "B001234567", "漠河北极村", "黑龙江省大兴安岭地区",
                "黑龙江省", "大兴安岭地区", "漠河市", 122.5386, 52.9722, false, null);
        String dxalToken = tokens.issue(OWNER, dxalCandidate);
        List<PlaceRefInput> dxalResult = canonicalizer.canonicalize(
                OWNER, List.of(ref(dxalToken)), List.of(), "大兴安岭地区");
        assertThat(dxalResult).hasSize(1);
        assertThat(dxalResult.get(0).city()).isEqualTo("大兴安岭地区");
    }

    @Test
    void autonomousPrefectureCandidateStillRejectedForDifferentCity() {
        // 大理白族自治州 token must still be rejected for a 北京 trip.
        PlaceSelectionTokenService tokens = tokens(NOW);
        PlaceRefCanonicalizer canonicalizer = new PlaceRefCanonicalizer(tokens);
        PlaceCandidate daliCandidate = new PlaceCandidate(
                "AMAP", "B001234567", "大理古城", "云南省大理白族自治州大理市古城路",
                "云南省", "大理白族自治州", "大理市", 100.1595, 25.7075, false, null);
        String token = tokens.issue(OWNER, daliCandidate);

        assertThatThrownBy(() -> canonicalizer.canonicalize(
                OWNER, List.of(ref(token)), List.of(), "北京市"))
                .isInstanceOf(ApiException.class)
                .satisfies(error -> {
                    ApiException api = (ApiException) error;
                    assertThat(api.code()).isEqualTo("PLACE_REF_TOKEN_INVALID");
                });
    }

    @Test
    void xiangxiCandidateStillRejectedForXiAnTrip() {
        PlaceSelectionTokenService tokens = tokens(NOW);
        PlaceRefCanonicalizer canonicalizer = new PlaceRefCanonicalizer(tokens);
        PlaceCandidate xiangxiCandidate = new PlaceCandidate(
                "AMAP", "B001234567", "凤凰古城", "湖南省湘西土家族苗族自治州凤凰县",
                "湖南省", "湘西土家族苗族自治州", "凤凰县", 109.5996, 27.9483, false, null);
        String token = tokens.issue(OWNER, xiangxiCandidate);

        assertThatThrownBy(() -> canonicalizer.canonicalize(
                OWNER, List.of(ref(token)), List.of(), "西安市"))
                .isInstanceOf(ApiException.class)
                .satisfies(error -> {
                    ApiException api = (ApiException) error;
                    assertThat(api.code()).isEqualTo("PLACE_REF_TOKEN_INVALID");
                });
    }


}
