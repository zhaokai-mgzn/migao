package com.migao.admin.worker;

// case_ids: PG-072, PG-065, BM-006, BM-056, HR-001, HR-002, UI-091, MC-158

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
    @DisplayName("默认 = report/piecework/order/cut_calc/shipment/to_ship（顺序即工人端默认页面顺序）")
    void defaultsAreTheFourWorkerPages() {
        // issue #6767（2026-10-12 用户逐字「需要给工人看」）：新增 `piecework`（我的计件，含金额）
        // —— 键与商家面人话名同批登记（WorkerPages.labels），默认与可选页同源 ⇒ 本条即闭词表守卫。
        assertThat(WorkerPages.defaultPages())
                .containsExactly("report", "piecework", "order", "cut_calc", "shipment", "to_ship",
                        "stock", "inbound", "reprint");
        // issue #7814（用户 2026-10-26「新增的工人菜单在这里也要能设置」）：`to_ship`（待发货单）
        // 与 `shipment`（拍照发货）是**两个能力** —— 读面 / 写面。合并成一个键 ⇒ 商家想关掉其中一个
        // 就得两个都关（菜单开关 = 显隐，关错了现场就没入口）。默认集合里两者都在。
        // issue #7162：`inspect`（质检）在闭词表里，但**不在默认集合**（逐人开、且是服务端写准入）
        // issue #8337：`inbound` / `reprint`（拍照入库 / 补打入库标签）此前**无键、恒显示**，现进闭词表；
        // 它们同时在默认集合里 —— 只加键不加默认 = 让「未收窄」的存量工人在升级那一刻丢掉这两个入口。
        assertThat(WorkerPages.ALL).containsExactly(
                "report", "piecework", "order", "cut_calc", "shipment", "to_ship", "stock",
                "inbound", "reprint", "inspect", "rework");
        // issue #7860：`rework`（手机端「报返工的加工单列表」）也不在默认集合 —— 用户裁定
        // 「在工人档案中设置过可见权限的工人」才看得到；报返工的**写**准入与此无关。
        assertThat(WorkerPages.defaultPages()).doesNotContain("inspect", "rework");
        assertThat(WorkerPages.optionalPages()).containsExactly("inspect", "rework");
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
        assertThat(WorkerPages.labels()).containsOnlyKeys(WorkerPages.ALL.toArray(String[]::new));
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
        assertThat(WorkerPages.restrictedOrNull(List.of("stocktake"))).isEmpty();
        assertThat(WorkerPages.effectiveFor(List.of("stocktake")))
                .containsExactlyElementsOf(WorkerPages.defaultPages());
        assertThat(WorkerPages.effectiveFor("[]")).containsExactlyElementsOf(WorkerPages.defaultPages());
        assertThat(WorkerPages.effectiveFor(List.of(1, 2)))
                .containsExactlyElementsOf(WorkerPages.defaultPages());
    }

    @Test
    @DisplayName("④ 🔴 inspect 逐人开：默认不出现；收窄集里给了才下发（且排最后）")
    void inspectIsOptInAndNeverInDefaults() {
        // 未收窄 ⇒ 默认页（不含质检）
        assertThat(WorkerPages.effectiveFor(null)).doesNotContain(WorkerPages.INSPECT);
        // 逐人开：收窄集里带 inspect ⇒ 下发（默认页在前、inspect 最后）
        assertThat(WorkerPages.effectiveFor(List.of("report", "inspect")))
                .containsExactly("report", "inspect");
        // 只开质检也可以（收窄到一页 = 就这一页）
        assertThat(WorkerPages.effectiveFor(List.of("inspect"))).containsExactly("inspect");
        // 写侧校验认得这个键（不在闭词表外）
        assertThat(WorkerPages.validateRestriction(List.of("inspect")).errors()).isEmpty();
    }

    @Test
    @DisplayName("⑤ 🔴 rework 逐人开（issue #7860 / #7932）：默认不出现；给了才下发；只开它**不许**回落默认页")
    void reworkIsOptInAndNeverInDefaults() {
        // 未收窄 ⇒ 默认页（不含返工记录）
        assertThat(WorkerPages.effectiveFor(null)).doesNotContain(WorkerPages.REWORK);
        // 逐人开：收窄集里带 rework ⇒ 下发（默认页在前、rework 在后）
        assertThat(WorkerPages.effectiveFor(List.of("report", "rework")))
                .containsExactly("report", "rework");
        // 🔴 只开返工记录：下发就是**这一页** —— 不得因为「其它默认页没勾」回落成全部默认页
        //    （那是把商家的意图反过来：想只开一页，工人却看到六页）
        assertThat(WorkerPages.effectiveFor(List.of("rework"))).containsExactly("rework");
        // 商家「全勾保存」的形态（默认页 + 两个能力页）⇒ 闭词表一个不少
        List<String> all = new ArrayList<>(WorkerPages.defaultPages());
        all.addAll(WorkerPages.optionalPages());
        assertThat(WorkerPages.effectiveFor(all))
                .containsExactlyElementsOf(new ArrayList<>(WorkerPages.ALL));
        // 写侧认得这两个能力页键
        assertThat(WorkerPages.validateRestriction(List.of("inspect", "rework")).errors()).isEmpty();
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

    // ════════════════════════════════════════════════════════════════════════════
    // 岗位 → 默认菜单 + 首屏最多 3 项（issue #8337）
    // 用户 2026-11-01 逐字「通常每个工序或者每个工人只能操作 1-3 个菜单，根据工人岗位来定菜单的」
    // ════════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("⑥ 键集补齐：拍照入库 / 补打入库标签这两张**已存在的**工人端页面有了页面键（此前无键、恒显示）")
    void inboundAndReprintPagesAreKeyedNow() {
        // 判据 ①（双向）：键集 ⊇ 工人端真实页面（两张物料页在 bmini 上早已存在：
        // frontend/bmini-app/src/pages/worker/inbound|reprint/index.tsx）
        assertThat(WorkerPages.ALL).contains("inbound", "reprint");
        assertThat(WorkerPages.labels()).containsEntry("inbound", "拍照入库")
                .containsEntry("reprint", "补打入库标签");
        // 写侧认得这两个键（否则商家配不出来 = 「少」的那一半）
        assertThat(WorkerPages.validateRestriction(List.of("inbound")).errors()).isEmpty();
        assertThat(WorkerPages.validateRestriction(List.of("reprint")).errors()).isEmpty();
        // 读侧按闭词表顺序下发
        assertThat(WorkerPages.effectiveFor(List.of("reprint", "inbound")))
                .containsExactly("inbound", "reprint");
    }

    @Test
    @DisplayName("⑦ 每个岗位都有默认菜单，且默认键**全部在闭词表内**、项数 ≤ 上限（判据 ②）")
    void everyPositionHasDefaultsInsideTheVocabulary() {
        assertThat(WorkerPages.positions()).isNotEmpty();
        assertThat(WorkerPages.positionDefaults().keySet())
                .as("每个岗位都必须有默认菜单（少一个 ⇒ 建号时该岗位静默落回全部页面）")
                .containsExactlyInAnyOrderElementsOf(WorkerPages.positions());
        for (Map.Entry<String, List<String>> entry : WorkerPages.positionDefaults().entrySet()) {
            assertThat(entry.getValue())
                    .as("岗位 %s 的默认菜单里出现了闭词表以外的键（配了也点不进去）", entry.getKey())
                    .isNotEmpty()
                    .allSatisfy(key -> assertThat(WorkerPages.ALL).contains(key))
                    .as("岗位 %s 的默认菜单超过首屏上限（默认值自己就违规）", entry.getKey())
                    .hasSizeLessThanOrEqualTo(WorkerPages.MAX_PAGES_PER_WORKER);
            // 默认菜单必须能通过写侧校验（默认值 = 合法值，不是「默认就 422」）
            assertThat(WorkerPages.validateRestriction(entry.getValue()).errors())
                    .as("岗位 %s 的默认菜单过不了写侧校验", entry.getKey())
                    .isEmpty();
        }
        // 每个岗位都有人话说明（配置面下拉副标）
        assertThat(WorkerPages.positionLabels().keySet())
                .containsExactlyInAnyOrderElementsOf(WorkerPages.positions());
    }

    @Test
    @DisplayName("⑧ 岗位默认菜单 == issue 判据的读数（裁剪=报工+计件 2 项 / 仓管=入库+补打+库存 3 项 / 发货=发货+待发货）")
    void positionDefaultsMatchTheIssueCriteria() {
        assertThat(WorkerPages.positionDefaults().get("裁剪"))
                .containsExactly("report", "piecework");
        assertThat(WorkerPages.positionDefaults().get("车位"))
                .containsExactly("report", "piecework");
        assertThat(WorkerPages.positionDefaults().get("仓管"))
                .containsExactly("inbound", "reprint", "stock");
        assertThat(WorkerPages.positionDefaults().get("发货"))
                .containsExactly("shipment", "to_ship");
        // 能力页（质检 / 返工）**不**进任何岗位默认（issue #7162 / #7860 的既有裁定）
        for (List<String> defaults : WorkerPages.positionDefaults().values()) {
            assertThat(defaults).doesNotContain("inspect", "rework");
        }
    }

    @Test
    @DisplayName("⑨ 未设岗位 / 未登记的岗位 ⇒ 回落全部默认页（存量工人零变化、读侧 fail-open）")
    void blankOrDefaultUnknownPositionFallsBackToAllDefaults() {
        assertThat(WorkerPages.defaultPagesFor(null)).containsExactlyElementsOf(WorkerPages.defaultPages());
        assertThat(WorkerPages.defaultPagesFor("  ")).containsExactlyElementsOf(WorkerPages.defaultPages());
        assertThat(WorkerPages.defaultPagesFor("不存在的岗位"))
                .containsExactlyElementsOf(WorkerPages.defaultPages());
        assertThat(WorkerPages.isPosition("仓管")).isTrue();
        assertThat(WorkerPages.isPosition(" 仓管 ")).isTrue();
        assertThat(WorkerPages.isPosition(null)).isFalse();
        assertThat(WorkerPages.isPosition("仓储")).isFalse();
    }

    @Test
    @DisplayName("⑩ 首屏最多 3 项：3 项通过、4 项**具名**拒错（说清上限 + 你填了几项）（判据 ④ 边界两侧）")
    void pageCapIsThreeAndTheFourthIsRejectedByName() {
        assertThat(WorkerPages.MAX_PAGES_PER_WORKER).isEqualTo(3);
        // 边界内侧：正好 3 项 ⇒ 通过
        WorkerPages.Validation three = WorkerPages.validateRestriction(
                List.of("inbound", "reprint", "stock"));
        assertThat(three.errors()).isEmpty();
        assertThat(three.pages()).containsExactly("inbound", "reprint", "stock");
        // 边界外侧：第 4 项 ⇒ 拒且**具名**（上限 3 / 你填了 4 / 列出这 4 项）
        WorkerPages.Validation four = WorkerPages.validateRestriction(
                List.of("inbound", "reprint", "stock", "report"));
        assertThat(four.ok()).isFalse();
        assertThat(four.errors()).hasSize(1);
        assertThat(four.errors().get(0).getKey()).isEqualTo("workerPages");
        assertThat(four.errors().get(0).getValue())
                .contains("最多 3 项")
                .contains("你填了 4 项");
        // 超出时**不**返回可落库的集合（调用方不能「部分写入」）
        assertThat(four.pages()).hasSize(4);
    }

    @Test
    @DisplayName("⑪ 存量数据：旧键集（不含新键）读面不炸、**不**被默认集合反向放宽（判据 ⑥ 负控）")
    void legacyStoredSetsKeepWorkingAndAreNotWidened() {
        // 真机读数（issue #8337）：租户 46 的验收工人原 workerPages = 8 项 —— 原样读出来
        String legacy = "[\"report\",\"piecework\",\"order\",\"shipment\",\"to_ship\",\"stock\","
                + "\"inspect\",\"rework\"]";
        assertThat(WorkerPages.effectiveFor(legacy)).containsExactly(
                "report", "piecework", "order", "shipment", "to_ship", "stock", "inspect", "rework");
        // 旧集合里**没有** inbound / reprint ⇒ 下发就没有它们（不做隐式补齐：那会放宽）
        assertThat(WorkerPages.effectiveFor(legacy)).doesNotContain("inbound", "reprint");
        // 已撤 / 未知键照旧被裁掉，不抛异常（读写两侧都不炸）
        assertThat(WorkerPages.effectiveFor("[\"report\",\"legacy_page\"]")).containsExactly("report");
        assertThat(WorkerPages.effectiveFor("[oops]")).containsExactlyElementsOf(WorkerPages.defaultPages());
    }
}
