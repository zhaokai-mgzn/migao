// case_ids: OR-046
package com.migao.admin.dto;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.validation.ConstraintViolation;
import jakarta.validation.Validation;
import jakarta.validation.Validator;
import jakarta.validation.ValidatorFactory;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.Set;
import java.util.stream.Collectors;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 整卷售卖**可录入字段**的传输层契约（issue #5846）——边界必须**显式拒绝**，不许静默取整。
 *
 * <p>用户 2026-10-01 裁定 A：「订单中售卖整卷布料时，应该有卷数和实际米数两字段」。
 * 两个字段复用既有列 {@code order_items.roll_count} / {@code order_items.roll_length_m}
 * （不加迁移）：{@code rollCount} = 卷数，{@code rollLengthM} = <b>每卷实际米数</b>
 * （下发页默认带出商品 {@code products.roll_length_m}）。</p>
 *
 * <p><b>本类判的是「输入面」</b>（与 {@link com.migao.admin.service.OrderServiceTest} 的
 * 「采用/分流」判据互补）：</p>
 * <ol>
 *   <li><b>边界 4xx</b>：卷数 &lt; 0 ⇒ 违反 Bean Validation 约束（控制器 {@code @Valid} ⇒ 400）；
 *       每卷米数 ≤ 0 ⇒ 同上；卷数 = 0 <b>合法</b>（那是「全散剪」这个真实结论，不是非法值）；</li>
 *   <li><b>传输层不静默取整</b>：JSON {@code "rollCount": 2.5} 必须**原样**落到 DTO（读回 2.5），
 *       由服务层显式 422 拒绝 —— 🔴 <b>不许截断成 2 卷</b>（Jackson 默认
 *       {@code ACCEPT_FLOAT_AS_INT=true}，字段若声明成 {@code Integer} 就会静默截断）；</li>
 *   <li><b>非数 ⇒ 400</b>：{@code "abc"} 这类非数值在反序列化期即失败
 *       （{@code HttpMessageNotReadableException} ⇒ 400），不落库、不 500。</li>
 * </ol>
 *
 * <p><b>红证</b>：把 {@code rollCount} 改回 {@code Integer} ⇒ 判据 2 红（{@code 2.5} 被截成 2）；
 * 去掉 {@code @DecimalMin} ⇒ 判据 1 红；把字段改成 primitive {@code int} ⇒
 * {@link com.migao.admin.service.OrderRollAllocationAuthorityTest} 红（「未给」与「0 卷」不可分）。</p>
 */
@DisplayName("#5846 整卷售卖录入字段的传输层契约：边界 4xx · 不静默取整 · 非数即 400")
class OrderRollInputContractTest {

    private final ObjectMapper objectMapper = new ObjectMapper();

    private static Set<String> violationsOf(OrderCreateRequest.OrderItemRequest item) {
        try (ValidatorFactory factory = Validation.buildDefaultValidatorFactory()) {
            Validator validator = factory.getValidator();
            return validator.validate(item).stream()
                    .map(ConstraintViolation::getPropertyPath)
                    .map(Object::toString)
                    .collect(Collectors.toSet());
        }
    }

    private static OrderCreateRequest.OrderItemRequest item(String rollCount, String rollLengthM) {
        OrderCreateRequest.OrderItemRequest item = new OrderCreateRequest.OrderItemRequest();
        item.setRollCount(rollCount == null ? null : new BigDecimal(rollCount));
        item.setRollLengthM(rollLengthM == null ? null : new BigDecimal(rollLengthM));
        return item;
    }

    @Test
    @DisplayName("#5846 卷数 -1 ⇒ 违反约束（控制器 @Valid ⇒ 4xx），不静默取整也不落负值")
    void negativeRollCountViolatesConstraint() {
        assertThat(violationsOf(item("-1", "60"))).contains("rollCount");
    }

    @Test
    @DisplayName("#5846 卷数 0 **合法**（「全散剪」是真实结论，不是非法值）")
    void zeroRollCountIsAllowed() {
        assertThat(violationsOf(item("0", "60"))).doesNotContain("rollCount");
    }

    @Test
    @DisplayName("#5846 每卷米数 0 / -1 ⇒ 违反约束（4xx）")
    void nonPositiveRollLengthViolatesConstraint() {
        assertThat(violationsOf(item("2", "0"))).contains("rollLengthM");
        assertThat(violationsOf(item("2", "-1"))).contains("rollLengthM");
    }

    @Test
    @DisplayName("#5846 卷数 2 + 每卷 58.5 ⇒ 两个字段都无约束违规（合法态）")
    void validPairHasNoViolationOnRollFields() {
        Set<String> violations = violationsOf(item("2", "58.5"));
        assertThat(violations).doesNotContain("rollCount");
        assertThat(violations).doesNotContain("rollLengthM");
    }

    @Test
    @DisplayName("#5846 传输层不静默取整：JSON rollCount=2.5 必须原样落到 DTO（由服务层 422 拒绝）")
    void fractionalRollCountSurvivesDeserialization() throws Exception {
        OrderCreateRequest.OrderItemRequest parsed = objectMapper.readValue(
                "{\"rollCount\": 2.5, \"rollLengthM\": 58.5}",
                OrderCreateRequest.OrderItemRequest.class);

        assertThat(parsed.getRollCount())
                .as("2.5 不许被静默截断成 2 卷（字段声明成 Integer 时 Jackson 会截断）")
                .isNotNull()
                .isEqualByComparingTo("2.5");
    }

    @Test
    @DisplayName("#5846 非数 ⇒ 反序列化期即失败（400，不落库、不 500）")
    void nonNumericRollFieldsAreRejectedAtTransport() {
        assertThatThrownBy(() -> objectMapper.readValue(
                "{\"rollCount\": \"abc\"}", OrderCreateRequest.OrderItemRequest.class))
                .isInstanceOf(com.fasterxml.jackson.core.JsonProcessingException.class);
        assertThatThrownBy(() -> objectMapper.readValue(
                "{\"rollLengthM\": \"abc\"}", OrderCreateRequest.OrderItemRequest.class))
                .isInstanceOf(com.fasterxml.jackson.core.JsonProcessingException.class);
    }
}
