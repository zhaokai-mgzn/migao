// case_ids: PG-070
package com.migao.admin.validation;

import com.migao.admin.exception.BusinessException;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import java.util.LinkedHashMap;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 分页入参准入（issue #6222）的**判据本体**：纯函数，不依赖 Spring / 不起上下文。
 *
 * <p>口径 = **显式拒绝**（400 {@code VALIDATION_ERROR}，带 {@code error.details[].field}），
 * 不是钳到合法下界（理由见 {@link PaginationParamGate} 的「口径裁定」）。</p>
 *
 * <p><b>白名单是判据的一半</b>：只有 {@code page} / {@code size}（大小写不敏感）在射程内；
 * 其它参数名（{@code othersize} / {@code pageSize} / {@code fileSize}）**必须不被判定**
 * —— 否则任何带 "size" 字样的业务参数都会被误拒（新的假红）。</p>
 */
@DisplayName("#6222 分页入参准入：size<0 / 非整数 ⇒ 400；page<1 有意不拒；白名单之外不判")
class PaginationParamGateTest {

    // ────────────────────────── ① 红：非法入参必须被拒 ──────────────────────────

    @Test
    @DisplayName("🔴 size=-5（issue 逐字复现的入参）⇒ 400 VALIDATION_ERROR，field=size")
    void negativeSize_isRejectedWith400() {
        assertThatThrownBy(() -> PaginationParamGate.requireValid("size", "-5"))
                .isInstanceOf(BusinessException.class)
                .satisfies(thrown -> {
                    BusinessException e = (BusinessException) thrown;
                    assertThat(e.getCode()).isEqualTo("VALIDATION_ERROR");
                    assertThat(e.getHttpStatus()).isEqualTo(400);
                    assertThat(e.getMessage()).contains("size=-5");
                    assertThat(e.getDetails()).hasSize(1);
                    assertThat(e.getDetails().get(0).getField()).isEqualTo("size");
                    assertThat(e.getDetails().get(0).getMessage()).contains("不能为负数");
                });
    }

    @Test
    @DisplayName("✅ page<1 **有意不拒**（裁定 2026-10-03）：page=0 / -1 / **page=1 返回同一页** ⇒ 不是本单缺陷")
    void nonPositivePage_isAccepted() {
        // 依据（主会话在未修复构建 :8080 现取）：
        //   page=0&size=3 / page=1&size=3 / page=-1&size=3 ⇒ 三条 200 · total=359 · rows=3 · **同一首行 id**
        // ⇒ MP 已把 page<1 钳到第 1 页（只是宽容，不是缺陷）；拒它会让 0 基分页调用方从「能拿第 1 页」变报错。
        for (String ok : new String[]{"0", "-1", "-5"}) {
            assertThatCode(() -> PaginationParamGate.requireValid("page", ok))
                    .as("page=%s 必须放行（观察项，不在本单射程）", ok)
                    .doesNotThrowAnyException();
        }
    }

    @ParameterizedTest(name = "size=[{0}] ⇒ 400（非十进制整数）")
    @ValueSource(strings = {"abc", "", " ", "1.5", "+5", "1e3", "9223372036854775808", "-", "--5"})
    @DisplayName("🔴 非十进制整数（含正号前缀 / 小数 / 溢出）⇒ 400，不静默落 500")
    void nonDecimalValue_isRejectedWith400(String bad) {
        assertThatThrownBy(() -> PaginationParamGate.requireValid("size", bad))
                .as("size=[%s]", bad)
                .isInstanceOf(BusinessException.class)
                .satisfies(thrown -> assertThat(((BusinessException) thrown).getHttpStatus()).isEqualTo(400));
    }

    // ────────────────────────── ② 绿：合法入参逐字不变 ──────────────────────────

    @Test
    @DisplayName("✅ size=0 / size=1 / size=500 / 前后空白（` 20 `）合法")
    void legalSizes_areAccepted() {
        for (String ok : new String[]{"0", "1", "20", "500", " 20 "}) {
            assertThatCode(() -> PaginationParamGate.requireValid("size", ok))
                    .as("size=[%s] 必须放行", ok)
                    .doesNotThrowAnyException();
        }
    }

    @Test
    @DisplayName("✅ page=1 / page=99999 合法")
    void legalPages_areAccepted() {
        for (String ok : new String[]{"1", "2", "99999"}) {
            assertThatCode(() -> PaginationParamGate.requireValid("page", ok))
                    .as("page=[%s] 必须放行", ok)
                    .doesNotThrowAnyException();
        }
    }

    // ────────────────────────── ③ 白名单：射程之外一律不判 ──────────────────────────

    @Test
    @DisplayName("✅ 白名单之外不被判定（othersize / pageSize / fileSize / sizex）")
    void otherParamNames_areNotJudged() {
        for (String name : new String[]{"othersize", "pageSize", "fileSize", "sizex", "pages"}) {
            assertThat(PaginationParamGate.isPaginationParamName(name))
                    .as("%s 不在射程内", name)
                    .isFalse();
            assertThatCode(() -> PaginationParamGate.requireValid(name, "-5"))
                    .as("%s=-5 必须放行（不是分页参数）", name)
                    .doesNotThrowAnyException();
        }
    }

    @Test
    @DisplayName("参数名大小写不敏感（?SIZE=-5 同样被拒；?Page=-1 放行 —— page 无下界）")
    void paramNameIsCaseInsensitive() {
        assertThat(PaginationParamGate.isPaginationParamName("SIZE")).isTrue();
        assertThat(PaginationParamGate.isPaginationParamName("Page")).isTrue();
        assertThatThrownBy(() -> PaginationParamGate.requireValid("SIZE", "-5"))
                .isInstanceOf(BusinessException.class);
        assertThatCode(() -> PaginationParamGate.requireValid("Page", "-1"))
                .doesNotThrowAnyException();
    }

    // ────────────────────────── ④ 整参数集入口（拦截器直接复用这一条） ──────────────────────────

    @Test
    @DisplayName("整参数集入口：坏值在任一条即拒；重复参数（size=-5&size=20）也拒")
    void wholeParamMap_isJudged() {
        Map<String, String[]> bad = new LinkedHashMap<>();
        bad.put("status", new String[]{"pending"});
        bad.put("size", new String[]{"-5"});
        assertThatThrownBy(() -> PaginationParamGate.requireValid(bad))
                .isInstanceOf(BusinessException.class)
                .satisfies(thrown -> assertThat(((BusinessException) thrown).getDetails().get(0).getField())
                        .isEqualTo("size"));

        Map<String, String[]> repeated = new LinkedHashMap<>();
        repeated.put("size", new String[]{"-5", "20"});
        assertThatThrownBy(() -> PaginationParamGate.requireValid(repeated))
                .as("重复参数里任一个非法即拒（不静默采用后一个）")
                .isInstanceOf(BusinessException.class);

        Map<String, String[]> good = new LinkedHashMap<>();
        good.put("page", new String[]{"2"});
        good.put("size", new String[]{"20"});
        good.put("keyword", new String[]{"窗帘"});
        assertThatCode(() -> PaginationParamGate.requireValid(good)).doesNotThrowAnyException();
    }
}
