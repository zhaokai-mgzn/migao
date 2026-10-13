package com.migao.admin.worker;

// case_ids: PG-072, PG-065, BM-006, HR-001, HR-002, UI-091

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 工人端页面闭词表测试 —— 默认值**只在一处**；页面集**只有一层**（issue #6828）。
 *
 * <p>判据（每条都能红）：</p>
 * <ol>
 *   <li>默认 = 全部页面（4 个，逐字）；改词表 / 加页面 ⇒ 本条红（默认值只有一处）；</li>
 *   <li>每个页面键都有商家面人话名（档案面板按它渲染；缺名 ⇒ 面板会显示机器码）；</li>
 *   <li><b>本类不提供任何权限相关 API</b>：工人页面码是**页面可见性**，不是权限码 ——
 *       一旦这里长出 {@code permissions} / {@code roles} 之类的方法，本条红（红线护栏）；</li>
 *   <li><b>单层求值</b>：{@code effectiveFor} 只认工人档案上的收窄（未收窄 ⇒ 全部页面），
 *       <b>不存在</b>「企业级 ∩ 个人」的两层入口（issue #6828 移除了企业级层；
 *       在参数表里加回第二层 ⇒ 本文件末条判据红）。</li>
 * </ol>
 */
@DisplayName("WorkerPages 工人端页面闭词表 + 单层求值（V141 / #6788 / #6828）")
class WorkerPagesTest {

    @Test
    @DisplayName("默认 = report/order/cut_calc/shipment（顺序即工人端默认页面顺序）")
    void defaultsAreTheFourWorkerPages() {
        assertThat(WorkerPages.defaultPages())
                .containsExactly("report", "order", "cut_calc", "shipment");
        assertThat(WorkerPages.ALL).containsExactlyInAnyOrderElementsOf(WorkerPages.defaultPages());
    }

    @Test
    @DisplayName("每次调用返回新列表（调用方改它不得污染默认值）")
    void defaultPagesIsNotASharedMutableInstance() {
        List<String> first = WorkerPages.defaultPages();
        assertThat(first).isNotSameAs(WorkerPages.defaultPages());
        assertThat(WorkerPages.defaultPages()).containsExactlyElementsOf(first);
    }

    @Test
    @DisplayName("每个页面键都有人话名（档案面板显示用；键是机器码）")
    void everyPageKeyHasAHumanLabel() {
        assertThat(WorkerPages.labels()).containsOnlyKeys(WorkerPages.defaultPages().toArray(String[]::new));
        assertThat(WorkerPages.labels().values()).allSatisfy(label -> assertThat(label).isNotBlank());
    }

    @Test
    @DisplayName("🔴 本类不得提供任何权限相关 API（页面码不是权限码）")
    void exposesNoPermissionSurface() {
        for (Method method : WorkerPages.class.getDeclaredMethods()) {
            assertThat(method.getName().toLowerCase())
                    .as("工人端页面码不是权限码（permissions 恒为 []）：%s", method.getName())
                    .doesNotContain("permission")
                    .doesNotContain("role")
                    .doesNotContain("authorit");
        }
    }

    // ════════════════════════════════════════════════════════════════════════════
    // 单层求值（issue #6828：企业级页面开关整层移除；真值 = users.worker_pages 一处）
    // ════════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("① 未收窄（null）⇒ 全部页面（存量与新建工人的默认行为零变化）")
    void nullRestrictionMeansAllPages() {
        assertThat(WorkerPages.effectiveFor(null)).containsExactlyElementsOf(WorkerPages.defaultPages());
    }

    @Test
    @DisplayName("② 档案收窄 ⇒ 只下发收窄集，顺序按闭词表（前端不再自己排一遍）")
    void restrictionNarrowsToTheSelectedPages() {
        assertThat(WorkerPages.effectiveFor(List.of("report", "cut_calc")))
                .containsExactly("report", "cut_calc");
        // 存储顺序与闭词表顺序无关：下发顺序恒按闭词表（避免「同一个人两次进页面菜单顺序不同」）
        assertThat(WorkerPages.effectiveFor(List.of("shipment", "report")))
                .containsExactly("report", "shipment");
    }

    @Test
    @DisplayName("③ **不是数组** ⇒ 当未收窄（fail-open）：字符串 / 映射 / 截断的 JSON 文本")
    void malformedStoredValueFallsBackToAllPages() {
        assertThat(WorkerPages.effectiveFor("report")).containsExactlyElementsOf(WorkerPages.defaultPages());
        assertThat(WorkerPages.effectiveFor(Map.of("report", true)))
                .containsExactlyElementsOf(WorkerPages.defaultPages());
        assertThat(WorkerPages.restrictedOrNull("report")).isNull();
        // 库里存的是原样 JSON 文本（String）：截断 / 非数组 ⇒ 同样当未收窄（不抛异常 —— 抛的话
        // GET /api/worker/me 会 500，把工人的活挡在外面，正是 fail-open 要避免的方向）
        assertThat(WorkerPages.restrictedOrNull("[\"report\"")).isNull();
        assertThat(WorkerPages.restrictedOrNull("{\"report\":true}")).isNull();
        assertThat(WorkerPages.effectiveFor("[oops]")).containsExactlyElementsOf(WorkerPages.defaultPages());
    }

    @Test
    @DisplayName("③ 归一后为空集（全未知键 / 空数组文本）⇒ 回落全部页面，**不是**空数组"
            + "（工人端把空数组读成「没读到权限 ⇒ 全开」，原样下发等于服务端与端侧口径分叉）")
    void dirtyRestrictionFallsBackToAllPages() {
        // 全是未知键 ⇒ 归一为空集（只裁不放宽）⇒ 下发侧回落全开（fail-open，与 H5 的 effectivePages 同口径）
        assertThat(WorkerPages.restrictedOrNull(List.of("stock"))).isEmpty();
        assertThat(WorkerPages.effectiveFor(List.of("stock")))
                .containsExactlyElementsOf(WorkerPages.defaultPages());
        assertThat(WorkerPages.effectiveFor("[]")).containsExactlyElementsOf(WorkerPages.defaultPages());
        assertThat(WorkerPages.effectiveFor(List.of(1, 2)))
                .containsExactlyElementsOf(WorkerPages.defaultPages());
    }

    @Test
    @DisplayName("③ 存储往返：真键集合 → JSON 文本 → 归一集合（原样、保序）")
    void storedJsonRoundTripsThroughTheNormalizer() {
        String stored = WorkerPages.storedJson(List.of("cut_calc", "report"));
        assertThat(stored).isEqualTo("[\"cut_calc\",\"report\"]");
        assertThat(WorkerPages.normalizeStored(stored)).containsExactly("cut_calc", "report");
        // null = 未收窄（不写空数组 —— 空数组在工人端会被读成「没读到权限 ⇒ 全开」）
        assertThat(WorkerPages.storedJson(null)).isNull();
        assertThat(WorkerPages.normalizeStored(null)).isNull();
    }

    @Test
    @DisplayName("④ 未知键 / 非字符串元素 ⇒ 裁掉；剩余真键照旧生效（只少不多，绝不放宽）")
    void unknownKeysAreDroppedAndNeverWiden() {
        assertThat(WorkerPages.effectiveFor(Arrays.asList("report", "not_a_page", "resport")))
                .containsExactly("report");
        assertThat(WorkerPages.restrictedOrNull(Arrays.asList("cut_calc", 7, null)))
                .containsExactly("cut_calc");
    }

    @Test
    @DisplayName("⑤ 合法输入归一：null ⇒ 未收窄；真键 ⇒ 保留请求顺序")
    void validRestrictionsAreNormalized() {
        assertThat(WorkerPages.validateRestriction(null).ok()).isTrue();
        assertThat(WorkerPages.validateRestriction(null).pages()).isNull();

        WorkerPages.Validation two = WorkerPages.validateRestriction(List.of("cut_calc", "report"));
        assertThat(two.ok()).isTrue();
        assertThat(two.pages()).containsExactly("cut_calc", "report");
    }

    @Test
    @DisplayName("⑤ 空数组 ⇒ 422（工人端把它读成「没读到权限 ⇒ 全开」，允许它 = 让商家点出相反的结果）")
    void emptyRestrictionIsRejectedOnTheWriteSide() {
        WorkerPages.Validation empty = WorkerPages.validateRestriction(new ArrayList<>());
        assertThat(empty.ok()).isFalse();
        assertThat(empty.errors()).hasSize(1);
        assertThat(empty.errors().get(0).getKey()).isEqualTo("workerPages");
        assertThat(empty.errors().get(0).getValue()).contains("停用");
    }

    @Test
    @DisplayName("⑤ 非法输入 ⇒ 逐条理由 + 点名下标（未知键 / 重复键 / 非字符串 / 非数组），一条都不静默吞掉")
    void invalidRestrictionsAreReportedOneByOne() {
        WorkerPages.Validation unknown = WorkerPages.validateRestriction(List.of("report", "resport"));
        assertThat(unknown.ok()).isFalse();
        assertThat(unknown.errors()).hasSize(1);
        assertThat(unknown.errors().get(0).getKey()).isEqualTo("workerPages[1]");
        assertThat(unknown.errors().get(0).getValue()).contains("resport");

        WorkerPages.Validation duplicate = WorkerPages.validateRestriction(List.of("report", "report"));
        assertThat(duplicate.errors().get(0).getKey()).isEqualTo("workerPages[1]");
        assertThat(duplicate.errors().get(0).getValue()).contains("重复");

        WorkerPages.Validation wrongType = WorkerPages.validateRestriction(List.of("report", 7));
        assertThat(wrongType.errors()).hasSize(1);
        assertThat(wrongType.errors().get(0).getKey()).isEqualTo("workerPages[1]");
        assertThat(wrongType.errors().get(0).getValue()).contains("字符串");

        WorkerPages.Validation notArray = WorkerPages.validateRestriction("report");
        assertThat(notArray.ok()).isFalse();
        assertThat(notArray.errors().get(0).getKey()).isEqualTo("workerPages");
    }

    @Test
    @DisplayName("🔴 单层求值：本类不得再长出「企业级 ∩ 档案级」的两层入口（issue #6828 移除了企业级层）")
    void exposesNoTwoLayerEntryPoint() {
        for (Method method : WorkerPages.class.getDeclaredMethods()) {
            assertThat(method.getName())
                    .as("企业级页面开关已整层移除（issue #6828）：两层求值入口 %s 不得复活", method.getName())
                    .isNotEqualTo("effectiveForOrFallback");
        }
        // effectiveFor 的**唯一**入参 = 档案上的收窄原值（没有第二个「企业页集」参数）
        assertThat(WorkerPages.class.getDeclaredMethods())
                .filteredOn(m -> m.getName().equals("effectiveFor"))
                .singleElement()
                .satisfies(m -> assertThat(m.getParameterCount()).isEqualTo(1));
    }
}
