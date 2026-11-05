package com.migao.admin.service;

// case_ids: MC-230

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 口径卡条件语言的**写面校验器**判据（issue #8175 判据 2 / 6 的 Java 一侧）。
 *
 * <p>判据的核心不是「能解析 JSON」，而是**自由文本必须被拒**：一条口径的触发条件若是自然语言，
 * 读面无法判定它该不该生效、出口③也生成不出会红的用例 ⇒ 那张卡从写进库的那一刻起就是死字段。
 * 本仓对这类形态有铁律（自然语义断言不许只写不判），所以门槛设在写面。</p>
 *
 * <p><b>算子表与 Python 读面必须逐项相同</b>：本类钉的是 Java 侧那份，跨语言对账在
 * {@code tests/unit_ci_workflows/test_playbook_condition_contract.py}（只改一侧即红）。</p>
 */
@DisplayName("PlaybookConditionValidator：自由文本不可执行 / 算子表与读面同一份")
class PlaybookConditionValidatorTest {

    private static final String TRIGGER =
            "{\"field\":\"intent\",\"op\":\"in\",\"value\":[\"quote\"]}";

    @Nested
    @DisplayName("合法条件")
    class Valid {

        @Test
        @DisplayName("叶子条件零问题（含 exists 这类无 value 的算子）")
        void leafIsValid() {
            assertThat(PlaybookConditionValidator.validateJson(TRIGGER)).isEqualTo(List.of());
            assertThat(PlaybookConditionValidator.validateJson("{\"field\":\"role\",\"op\":\"exists\"}"))
                    .isEqualTo(List.of());
        }

        @Test
        @DisplayName("组合条件递归校验（all / not 混用）")
        void compositeIsValid() {
            String json = "{\"all\":[" + TRIGGER
                    + ",{\"not\":{\"field\":\"role\",\"op\":\"exists\"}}]}";
            assertThat(PlaybookConditionValidator.validateJson(json)).isEqualTo(List.of());
        }
    }

    @Nested
    @DisplayName("不可执行的条件（每条都要具名）")
    class Rejected {

        @Test
        @DisplayName("自由文本触发条件 ⇒ 明确拒绝（不是「解析失败就算通过」）")
        void freeTextIsRejected() {
            assertThat(PlaybookConditionValidator.validateJson("\"整卷优先\""))
                    .containsExactly("条件必须是 JSON 对象，实际是 STRING");
            assertThat(PlaybookConditionValidator.validateJson("整卷优先"))
                    .singleElement().asString().startsWith("条件不是合法 JSON");
        }

        @Test
        @DisplayName("空条件 ⇒ 拒绝（空条件 = 无条件生效，最危险）")
        void blankIsRejected() {
            assertThat(PlaybookConditionValidator.validateJson("")).containsExactly("条件是空对象");
            assertThat(PlaybookConditionValidator.validateJson("  ")).containsExactly("条件是空对象");
            assertThat(PlaybookConditionValidator.validateJson("{}")).containsExactly("条件是空对象");
        }

        @Test
        @DisplayName("未知算子 ⇒ 问题清单里点名那个算子与白名单")
        void unknownOperatorIsNamed() {
            assertThat(PlaybookConditionValidator.validateJson(TRIGGER.replace("in", "类似")))
                    .anyMatch(p -> p.contains("未知算子 类似") && p.contains("exists"));
        }

        @Test
        @DisplayName("value 形态不对 ⇒ 逐条具名")
        void valueShapeIsChecked() {
            assertThat(PlaybookConditionValidator.validateJson(
                    "{\"field\":\"intent\",\"op\":\"in\",\"value\":\"quote\"}"))
                    .containsExactly("算子 in 的 value 必须是非空数组");
            assertThat(PlaybookConditionValidator.validateJson(
                    "{\"field\":\"intent\",\"op\":\"contains\",\"value\":[\"x\"]}"))
                    .containsExactly("算子 contains 的 value 必须是非空字符串");
            assertThat(PlaybookConditionValidator.validateJson(
                    "{\"field\":\"intent\",\"op\":\"exists\",\"value\":1}"))
                    .containsExactly("算子 exists 不得带 value");
        }

        @Test
        @DisplayName("组合键混用 / 空组合 / 叶子缺 field ⇒ 具名")
        void structureIsChecked() {
            assertThat(PlaybookConditionValidator.validateJson(
                    "{\"all\":[" + TRIGGER + "],\"any\":[" + TRIGGER + "]}"))
                    .containsExactly("一个条件里同时出现多个组合键：[all, any]");
            assertThat(PlaybookConditionValidator.validateJson("{\"all\":[]}"))
                    .containsExactly("all 必须是非空数组");
            assertThat(PlaybookConditionValidator.validateJson("{\"op\":\"eq\",\"value\":1}"))
                    .containsExactly("叶子条件缺 field（或 field 不是字符串）");
        }
    }

    @Test
    @DisplayName("算子白名单恰为八项且顺序固定（Python 侧同表，跨语言对账判据守着）")
    void operatorWhitelistIsExact() {
        assertThat(PlaybookConditionValidator.OPS).containsExactly(
                "eq", "ne", "in", "not_in", "contains", "not_contains", "exists", "not_exists");
        assertThat(PlaybookConditionValidator.isExecutable(TRIGGER)).isTrue();
        assertThat(PlaybookConditionValidator.isExecutable("整卷优先")).isFalse();
    }
}
