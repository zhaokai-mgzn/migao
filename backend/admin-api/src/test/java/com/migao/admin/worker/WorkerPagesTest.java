package com.migao.admin.worker;

// case_ids: PG-072, BM-006, HR-001, HR-002, UI-091

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 工人端页面闭词表测试（V141，母单 #5161）—— 默认值**只在一处**。
 *
 * <p>判据（每条都能红）：</p>
 * <ol>
 *   <li>默认 = 全部页面（4 个，逐字）；改词表 / 加页面 ⇒ 本条与
 *       {@code WorkerPageConfigServiceTest} 的默认判据同时红（两份默认值会漂）；</li>
 *   <li>每个页面键都有商家面人话名（配置面板按它渲染；缺名 ⇒ 面板会显示机器码）；</li>
 *   <li><b>本类不提供任何权限相关 API</b>：工人页面码是**页面可见性**，不是权限码 ——
 *       一旦这里长出 {@code permissions} / {@code roles} 之类的方法，本条红（红线护栏）。</li>
 * </ol>
 */
@DisplayName("WorkerPages 工人端页面闭词表（V141 / 母单 #5161）")
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
    @DisplayName("每个页面键都有人话名（面板显示用；键是机器码）")
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
    // 工人档案级收窄（issue #6788；用户 2026-10-13 逐字「工人档案上也应该设置 h5 工人端的
    // 菜单权限，这样让不同岗位的工人只关注他自己有权限的功能了」）—— 几何 / 默认值 / fail 方向
    // ════════════════════════════════════════════════════════════════════════════

    /** 企业页（四页全开）—— 求交判据的基准。 */
    private static final List<String> TENANT = List.of("report", "order", "cut_calc", "shipment");

    @Test
    @DisplayName("① 未收窄（null）⇒ 下发 = 企业页逐值复制（存量与新建工人的默认行为零变化）")
    void nullRestrictionFollowsTheEnterpriseSet() {
        assertThat(WorkerPages.effectiveFor(TENANT, null)).containsExactlyElementsOf(TENANT);
        // 企业只开两页时同样逐值跟随（不补回「默认四页」—— 默认值只有 defaultPages() 一处）
        assertThat(WorkerPages.effectiveFor(List.of("report", "cut_calc"), null))
                .containsExactly("report", "cut_calc");
    }

    @Test
    @DisplayName("② 企业级是天花板：企业页 ∩ 个人收窄（企业只开 report/cut_calc + 个人勾 report/shipment ⇒ 只剩 report）")
    void workerRestrictionNeverWidensTheEnterpriseSet() {
        assertThat(WorkerPages.effectiveFor(List.of("report", "cut_calc"), List.of("report", "shipment")))
                .containsExactly("report");
        // 个人勾的页企业一页都没开 ⇒ 空集（**不是**把个人那份放出去）
        assertThat(WorkerPages.effectiveFor(List.of("report"), List.of("shipment"))).isEmpty();
        // 顺序按**企业页**（读面原样下发，前端不再自己排一遍）
        assertThat(WorkerPages.effectiveFor(TENANT, List.of("shipment", "report")))
                .containsExactly("report", "shipment");
    }

    @Test
    @DisplayName("③ **不是数组** ⇒ 当未收窄（fail-open）：字符串 / 映射 / 截断的 JSON 文本")
    void malformedStoredValueFallsBackToFollowTheEnterprise() {
        assertThat(WorkerPages.effectiveFor(TENANT, "report")).containsExactlyElementsOf(TENANT);
        assertThat(WorkerPages.effectiveFor(TENANT, Map.of("report", true))).containsExactlyElementsOf(TENANT);
        assertThat(WorkerPages.restrictedOrNull("report")).isNull();
        // 库里存的是原样 JSON 文本（String）：截断 / 非数组 ⇒ 同样当未收窄（不抛异常 —— 抛的话
        // GET /api/worker/me 会 500，把工人的活挡在外面，正是 fail-open 要避免的方向）
        assertThat(WorkerPages.restrictedOrNull("[\"report\"")).isNull();
        assertThat(WorkerPages.restrictedOrNull("{\"report\":true}")).isNull();
        assertThat(WorkerPages.effectiveFor(TENANT, "[oops]")).containsExactlyElementsOf(TENANT);
    }

    @Test
    @DisplayName("③ 是数组但元素全非字符串 ⇒ 空集（**不是**未收窄）：只有「整体不是数组」才 fail-open")
    void allNonStringElementsMeanNothingVisible() {
        assertThat(WorkerPages.effectiveFor(TENANT, List.of(1, 2))).isEmpty();
        assertThat(WorkerPages.restrictedOrNull(List.of(1, 2))).isEmpty();
        assertThat(WorkerPages.effectiveForOrFallback(TENANT, List.of(1, 2))).containsExactlyElementsOf(TENANT);
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
    @DisplayName("③ 求交为空 ⇒ 回落企业页集（否则工人端把空集读成「没读到权限」而**全开**，与收窄相反）")
    void emptyIntersectionFallsBackInsteadOfOpeningEverything() {
        // 工人被收窄到 cut_calc，而企业把 cut_calc 关了 ⇒ 交集为空
        assertThat(WorkerPages.effectiveFor(List.of("report", "order"), List.of("cut_calc"))).isEmpty();
        assertThat(WorkerPages.effectiveForOrFallback(List.of("report", "order"), List.of("cut_calc")))
                .containsExactly("report", "order");
        // 未收窄 / 企业一页没开：两条都回企业页集（后者本身就是空 ⇒ 工人端按全开跑，由调用方记日志）
        assertThat(WorkerPages.effectiveForOrFallback(List.of("report"), null)).containsExactly("report");
        assertThat(WorkerPages.effectiveForOrFallback(List.of(), List.of("report"))).isEmpty();
    }

    @Test
    @DisplayName("④ 未知键 / 非字符串元素 ⇒ 裁掉；剩余真键照旧生效（只少不多，绝不放宽）")
    void unknownKeysAreDroppedAndNeverWiden() {
        assertThat(WorkerPages.effectiveFor(TENANT, Arrays.asList("report", "not_a_page", "resport")))
                .containsExactly("report");
        // 全是未知键 ⇒ 空集（企业页一页都不露），绝不退化成「全开」
        assertThat(WorkerPages.effectiveFor(TENANT, List.of("not_a_page"))).isEmpty();
        assertThat(WorkerPages.restrictedOrNull(Arrays.asList("cut_calc", 7, null)))
                .containsExactly("cut_calc");
    }

    @Test
    @DisplayName("④ 空数组 = 显式「一页都不给」（读侧能表达；**写侧**已拒，见 invalidRestrictions）")
    void emptyListMeansExplicitlyNothing() {
        assertThat(WorkerPages.effectiveFor(TENANT, List.of())).isEmpty();
        assertThat(WorkerPages.restrictedOrNull(List.of())).isEmpty();
        // 库里的空数组文本同样读成空集（脏数据方向：只裁不放宽）
        assertThat(WorkerPages.restrictedOrNull("[]")).isEmpty();
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
}
