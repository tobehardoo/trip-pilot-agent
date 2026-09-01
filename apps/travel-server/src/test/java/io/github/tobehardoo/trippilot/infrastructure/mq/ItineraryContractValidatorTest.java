package io.github.tobehardoo.trippilot.infrastructure.mq;

import java.math.BigDecimal;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class ItineraryContractValidatorTest {

    @Test
    void rejectsNegativeMoney() {
        assertThat(ItineraryContractValidator.isPersistableMoney(new BigDecimal("-1")))
                .isFalse();
        assertThat(ItineraryContractValidator.isPersistableMoney(new BigDecimal("-0.01")))
                .isFalse();
    }

    @Test
    void rejectsNullMoney() {
        assertThat(ItineraryContractValidator.isPersistableMoney(null)).isFalse();
    }

    @Test
    void acceptsMoneyUpToThePersistenceLimit() {
        assertThat(ItineraryContractValidator.isPersistableMoney(
                new BigDecimal("9999999999.99"))).isTrue();
        assertThat(ItineraryContractValidator.isPersistableMoney(new BigDecimal("0")))
                .isTrue();
    }

    @Test
    void rejectsMoneyAboveThePersistenceLimit() {
        assertThat(ItineraryContractValidator.isPersistableMoney(
                new BigDecimal("10000000000.00"))).isFalse();
    }

    @Test
    void normalisesTrailingZerosBeforeCheckingScale() {
        // NUMERIC(12,2) stores 100.000 as 100.00, so trailing zeros beyond two
        // decimal places are persistable once normalised.
        assertThat(ItineraryContractValidator.isPersistableMoney(
                new BigDecimal("100.000"))).isTrue();
        assertThat(ItineraryContractValidator.isPersistableMoney(
                new BigDecimal("0.001"))).isFalse();
    }

    @Test
    void supportedProviderAcceptsOnlyDemoAndAmap() {
        assertThat(ItineraryContractValidator.supportedProvider("DEMO")).isTrue();
        assertThat(ItineraryContractValidator.supportedProvider("AMAP")).isTrue();
        assertThat(ItineraryContractValidator.supportedProvider("TAXI")).isFalse();
        assertThat(ItineraryContractValidator.supportedProvider(null)).isFalse();
    }

    @Test
    void validHttpUrlRequiresHttpSchemeAndHost() {
        assertThat(ItineraryContractValidator.validHttpUrl(
                "https://example.com/poi/1")).isTrue();
        assertThat(ItineraryContractValidator.validHttpUrl("ftp://example.com")).isFalse();
        assertThat(ItineraryContractValidator.validHttpUrl("not a url")).isFalse();
        assertThat(ItineraryContractValidator.validHttpUrl(null)).isFalse();
    }
}
