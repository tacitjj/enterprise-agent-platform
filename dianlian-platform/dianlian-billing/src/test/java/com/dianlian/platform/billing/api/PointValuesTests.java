package com.dianlian.platform.billing.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import org.junit.jupiter.api.Test;

class PointValuesTests {

    @Test
    void convertsPublicPointValuesWithoutFloatingPointRounding() {
        assertThat(PointValues.parseDisplayValue("12.5")).isEqualTo(12_500_000L);
        assertThat(PointValues.parseDisplayValue("0.000001")).isEqualTo(1L);
        assertThat(PointValues.formatDisplayValue(12_500_000L)).isEqualTo("12.5");
        assertThat(PointValues.formatDisplayValue(0L)).isEqualTo("0");
    }

    @Test
    void rejectsValuesThatDoNotMatchThePublicFixedPointContract() {
        assertThatThrownBy(() -> PointValues.parseDisplayValue("-1"))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> PointValues.parseDisplayValue("1.0000001"))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> PointValues.parseDisplayValue("999999999999999999999999"))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> PointValues.formatDisplayValue(-1L))
                .isInstanceOf(IllegalArgumentException.class);
    }
}
