package io.github.tobehardoo.trippilot.trip;

import java.time.LocalDate;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class TripTitleGeneratorTest {

    @Test
    void sameYearRangeDropsTheLeadingYearFromTheSecondDate() {
        assertThat(TripTitleGenerator.generate(
                "广州", LocalDate.of(2026, 8, 20), LocalDate.of(2026, 8, 21)))
                .isEqualTo("2026年08月20日—08月21日 广州市旅行规划");
    }

    @Test
    void differentYearRangeKeepsBothYears() {
        assertThat(TripTitleGenerator.generate(
                "广州", LocalDate.of(2026, 12, 30), LocalDate.of(2027, 1, 2)))
                .isEqualTo("2026年12月30日—2027年01月02日 广州市旅行规划");
    }

    @Test
    void cityNamesEndingWithCityKeepTheirSuffix() {
        assertThat(TripTitleGenerator.generate(
                "北京市", LocalDate.of(2026, 8, 20), LocalDate.of(2026, 8, 21)))
                .isEqualTo("2026年08月20日—08月21日 北京市旅行规划");
    }

    @Test
    void otherRegionSuffixesArePreserved() {
        assertThat(TripTitleGenerator.generate(
                "延边朝鲜族自治州", LocalDate.of(2026, 8, 20), LocalDate.of(2026, 8, 21)))
                .isEqualTo("2026年08月20日—08月21日 延边朝鲜族自治州旅行规划");
    }

    @Test
    void cityIsTrimmedBeforeUse() {
        assertThat(TripTitleGenerator.generate(
                " 广州 ", LocalDate.of(2026, 8, 20), LocalDate.of(2026, 8, 21)))
                .isEqualTo("2026年08月20日—08月21日 广州市旅行规划");
    }

    @Test
    void blankCityYieldsNoCitySubject() {
        assertThat(TripTitleGenerator.generate(
                "   ", LocalDate.of(2026, 8, 20), LocalDate.of(2026, 8, 21)))
                .isEqualTo("2026年08月20日—08月21日 旅行规划");
    }
}
