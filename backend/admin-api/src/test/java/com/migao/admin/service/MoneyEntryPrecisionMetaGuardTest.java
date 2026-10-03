// case_ids: AS-014
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.TreeSet;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 金额入口**小数位准入**的类级元守卫（issue #6221，铁律 8）。
 *
 * <h2>为什么需要它（只修一处 = 没修）</h2>
 * 本单的实例缺陷是「退款金额不校小数位」⇒ 写库静默归零。但**同一形态在别的金额入口照样成立**
 * —— `NUMERIC(·,2)` 列对所有调用方一视同仁地静默四舍五入。只修退款这一处，
 * 下一个人在「建单改价 / 收款 / 售后联动 / 入库单价 / 结算 / 发放 / 调账」上会**原样再犯一遍**，
 * 而没有任何东西会红。本守卫把「**凡写金额列的文件都必须在入口台账里登记**」变成机械判据。
 *
 * <h2>发现规则（自动，不靠人记）</h2>
 * <ol>
 *   <li><b>金额列 → setter</b>：从 {@code src/main/java/com/migao/admin/entity/*.java} 里
 *       {@code private BigDecimal <名含 amount/price/cost/fee/money>} 的字段**现取** setter 名
 *       （现取 15 个金额实体），再扫全仓 {@code src/main/java} 里这些 setter 的**调用点**
 *       （带实参，排除 `totals.setAmount()` 这类**取**名为 setAmount 的字段的形态）
 *       ⇒ 调用点所在文件必须在台账里。</li>
 *   <li><b>金额实体 → builder</b>：含金额字段的实体类的 {@code Xxx.builder()} 调用点同理
 *       （左侧加词边界，防 `InboundOrder.builder()` 被当成 `Order.builder()`）。</li>
 * </ol>
 * ⇒ 新加一个金额列、或在未登记的文件里写一笔金额 ⇒ **当场红并具名**（判据 7）。现取读数：
 * **19 个文件 / 39 处写面**（本包落库时）。
 *
 * <h2>台账四态（每条 = 文件 :: 符号）</h2>
 * <ul>
 *   <li>{@code GATED} —— 该写面在落库前过 {@code MoneyScale.requireTwoDecimals}（判据 9 核文本）；</li>
 *   <li>{@code EQUIVALENT_GATED} —— 该文件已有等价准入
 *       （{@code setScale(2, RoundingMode.UNNECESSARY)}，判据 9' 核文本）；</li>
 *   <li>{@code NO_NEW_INPUT_SOURCE} —— **无准入但不引入新的超精度输入源**：值来自库列回读、
 *       上游已准入值、代码常量，或该写面是同一笔金额的台账/版本/派生化（必须写理由，
 *       并指向它的**根条目**，防「同一笔钱的两次写被记成两个缺口」）；</li>
 *   <li>{@code DEBT} —— **外部输入直接落库**且无小数位准入，登记为债务，必须带 issue 号，
 *       且**只许缩短**（判据 10/11/13：条数现取 ≤ 冻结上限）。</li>
 * </ul>
 *
 * <h2>红证（判别力自证，判据 6~12 在内存里各注入一种坏形态）</h2>
 * 未登记写面 / 台账条目空转（写面被删/改名）/ 声称 GATED 但文件里没有判据文本 /
 * 债务不带 issue 号 / 豁免不带理由 / 债务条数超过冻结上限 / 扫描面为空（空跑）⇒ 各自判红；
 * 同一夹具不注入 ⇒ 不报（判据 6，反向对照）。
 *
 * <h2>边界（如实登记，§19.1）</h2>
 * <ul>
 *   <li>射程 = **实体 setter 调用点 + 金额实体 builder 调用点**。不覆盖：直接拼 SQL 的金额写面
 *       （{@code UpdateWrapper.setSql("... amount = ...")} —— 订单退款本身就是走它写的）、
 *       非实体 POJO 的金额字段、前端 / ai-agent / mini-app。</li>
 *   <li>「只许缩短」的机械半边 = {@code DEBT 条数 ≤ 冻结上限}；**判不了**「有人把冻结上限改大」
 *       —— 那落在 diff 评审里（与本仓既有台账同族边界）。</li>
 *   <li>本守卫**不跑**被它点名的那些测试（否则等于把全量套件再跑一遍）；
 *       判「这段代码真的会执行」也判不了 —— 结构面（调用点在不在、文本在不在）是它保证的全部。</li>
 *   <li>「外部输入 vs 派生化」的归类是**人读 + 代码注释**的判定，不是机械推断 ⇒ 每条 NO_NEW_INPUT_SOURCE
 *       都写了理由，评审可逐条质疑（这是本守卫最软的一环，如实登记）。</li>
 * </ul>
 */
@DisplayName("金额入口小数位准入 · 类级元守卫（issue #6221）")
class MoneyEntryPrecisionMetaGuardTest {

    /** 主源码根（相对 admin-api 模块目录 —— mvn 的工作目录）。 */
    private static final Path MAIN_ROOT = Paths.get("src/main/java");

    /** 金额准入判据的文本锚（不写行号：行号会漂移）。 */
    private static final String GATE_MARKER = "MoneyScale.requireTwoDecimals";
    /** 既有等价准入的文本锚（本仓既有范式，见 ProductionOperationPositionCommandService）。 */
    private static final String EQUIVALENT_MARKER = "RoundingMode.UNNECESSARY";

    /**
     * 债务台账的**冻结上限**（只许缩短）：本包落库时的现取读数（判据 13 现场复核）。
     * 🔴 将来**只许改小**；改大 = 把新缺口塞进豁免（评审可见，判据 11 会给出具名读数）。
     */
    private static final int FROZEN_DEBT_BASELINE = 17;

    /** 金额字段的识别规则（实体里现取，不硬编码字段清单）。 */
    private static final Pattern MONEY_FIELD = Pattern.compile(
            "^\\s*private\\s+BigDecimal\\s+(\\w*(?:[Aa]mount|[Pp]rice|[Cc]ost|[Ff]ee|[Mm]oney)\\w*)\\s*;",
            Pattern.MULTILINE);

    // ════════════════════════════ 台账（本包逐处读数）════════════════════════════

    /** 准入形态。 */
    enum Admission {
        /** 落库前过 {@code MoneyScale.requireTwoDecimals}（本包新增的单点准入）。 */
        GATED,
        /** 已有等价准入（{@code setScale(2, RoundingMode.UNNECESSARY)}）。 */
        EQUIVALENT_GATED,
        /** 无准入但**不引入新的超精度输入源**（库列回读 / 上游已准入 / 代码常量 / 同一笔钱的台账）。 */
        NO_NEW_INPUT_SOURCE,
        /** **外部输入直接落库**且无小数位准入 —— 债务，须带 issue 号，只许缩短。 */
        DEBT
    }

    /** 台账条目：文件 :: 符号 ⇒ 读数。 */
    record Site(String file, String symbol, Admission admission, String note) {
    }

    private static Site site(String file, String symbol, Admission admission, String note) {
        return new Site(file, symbol, admission, note);
    }

    /**
     * **入口台账**（本包的全仓金额入口扫描读数，19 个文件 / 39 处）。
     *
     * <p>读法：`<文件>` 里出现 `<符号>` 写面 ⇒ 该条给出**是否有小数位准入**。
     * DEBT 条目指向跟进单 **#6228**（本包只修退款这一处，其余入口按边界纪律不改）。</p>
     */
    private static List<Site> registry() {
        return List.of(
                // ── ① 本包修复的入口（GATED）──────────────────────────────────────
                site("com/migao/admin/service/OrderService.java", "setRefundAmount", Admission.GATED,
                        "退款（issue #6221）：refund_amount 落库前过 MoneyScale.requireTwoDecimalsOrNull"),
                site("com/migao/admin/service/OrderService.java", "FinanceTransaction.builder()", Admission.GATED,
                        "退款流水 amount = applied（同一笔已过准入）；收款流水 amount 取自订单实收（库列 numeric(12,2)）"),

                // ── ② 已有等价准入（EQUIVALENT_GATED，本仓既有范式）────────────────
                site("com/migao/admin/service/ProductionOperationPositionCommandService.java", "setUnitPrice",
                        Admission.EQUIVALENT_GATED,
                        "部位计件单价走 price() 的 setScale(2, RoundingMode.UNNECESSARY)（填 6.005 直接抛）"),
                site("com/migao/admin/service/ProductionRoutingCommandService.java", "ProductionRouteRule.builder()",
                        Admission.EQUIVALENT_GATED,
                        "特殊选项对客单价经 optionalCustomerPrice 的 setScale(2, UNNECESSARY) 准入"),

                // ── ③ 外部输入直接落库且**无**准入 ⇒ 债务（跟单 #6228）────────────
                site("com/migao/admin/service/AfterSalesTicketService.java", "setRefundAmount", Admission.DEBT,
                        "售后工单 refund_amount（NUMERIC(10,2)）建单直接落请求值；完结联动退款沿用同一未准入值（跟单 #6228）"),
                site("com/migao/admin/service/AgentBatchService.java", "setBasePrice", Admission.DEBT,
                        "批量改价的价来自批次输入，透传 ProductService.updateProductForAgent ⇒ 准入缺失同 ProductService（跟单 #6228）"),
                site("com/migao/admin/service/FinanceService.java", "FinanceTransaction.builder()", Admission.DEBT,
                        "手工登记收款/退款（request.amount）只判正、不校小数位；流水列 NUMERIC(12,2)（跟单 #6228）"),
                site("com/migao/admin/service/InboundOrderService.java", "InboundOrder.builder()", Admission.DEBT,
                        "入库单总额 = Σ(数量×单价)：数量已 1 位小数准入、**单价只判 > 0** ⇒ 积可超 2 位小数（跟单 #6228）"),
                site("com/migao/admin/service/InboundOrderService.java", "InboundOrderItem.builder()", Admission.DEBT,
                        "入库单行的 unitCost/amount 同上（单价无小数位准入）（跟单 #6228）"),
                site("com/migao/admin/service/OpeningRegisterImportService.java", "setUnitCost", Admission.DEBT,
                        "期初建账 Excel 导入单价来自外部表格，无小数位准入（跟单 #6228）"),
                site("com/migao/admin/service/OrderService.java", "setActualAmount", Admission.DEBT,
                        "建单/改单 actual_amount = 请求实收，任意精度直接落库（同文件响应 DTO 的 setActualAmount 非落库）（跟单 #6228）"),
                site("com/migao/admin/service/OrderService.java", "setDiscountAmount", Admission.DEBT,
                        "建单/改单 discount_amount 来自请求，无小数位准入（跟单 #6228）"),
                site("com/migao/admin/service/OrderService.java", "setTotalAmount", Admission.DEBT,
                        "建单/改单 total_amount = 服务端 Σ(单价×数量)，积可超 2 位小数（跟单 #6228）"),
                site("com/migao/admin/service/OrderService.java", "setUnitPrice", Admission.DEBT,
                        "订单明细 order_items.unit_price 只校 > 0，不校小数位（跟单 #6228）"),
                site("com/migao/admin/service/ProcessingFeeCombinationCommandService.java", "setUnitPrice",
                        Admission.DEBT,
                        "加工费组合单价只校 >= 0（requiredPrice），不校小数位（跟单 #6228）"),
                site("com/migao/admin/service/ProcessingFeeCombinationCommandService.java",
                        "ProcessingFeeCombination.builder()", Admission.DEBT,
                        "建单人工改价写入组合单价，同上（跟单 #6228）"),
                site("com/migao/admin/service/ProductService.java", "setBasePrice", Admission.DEBT,
                        "products.base_price（建品/改品/Excel 导入）来自请求，无小数位准入（跟单 #6228）"),
                site("com/migao/admin/service/ProductService.java", "setPrice", Admission.DEBT,
                        "product_skus.price（建品/改品/导入）同上（跟单 #6228）"),
                site("com/migao/admin/service/ProductionOperationCommandService.java", "setUnitPrice", Admission.DEBT,
                        "付工人的计件单价只校 >= 0（decimal()），不校小数位（跟单 #6228）"),
                site("com/migao/admin/service/ProductionOperationCommandService.java", "ProductionOperation.builder()",
                        Admission.DEBT,
                        "工序单价（含批量改价的局部实体）同上（跟单 #6228）"),
                site("com/migao/admin/service/WorkerInboundService.java", "setUnitCost", Admission.DEBT,
                        "工人面入库单价来自工人输入，透传 InboundOrderService ⇒ 准入缺失同上（跟单 #6228）"),

                // ── ④ 无准入但**不引入新的超精度输入源**（逐条给理由）──────────────
                site("com/migao/admin/service/CustomerService.java", "CustomerProfile.builder()",
                        Admission.NO_NEW_INPUT_SOURCE,
                        "客户画像的累计退款额由订单退款额聚合而来（库列回读值），不引入新的外部精度"),
                site("com/migao/admin/service/InboundOrderService.java", "StockBatch.builder()",
                        Admission.NO_NEW_INPUT_SOURCE,
                        "同一入库请求的 unitCost/amount 落到批次（根条目 = 本文件的 InboundOrderItem.builder()）"),
                site("com/migao/admin/service/InboundOrderService.java", "setTotalAmount", Admission.NO_NEW_INPUT_SOURCE,
                        "入库单主表同步内存对象的总额（同一笔钱，根条目 = 本文件的 InboundOrder.builder()）"),
                site("com/migao/admin/service/OrderService.java", "setAmount", Admission.NO_NEW_INPUT_SOURCE,
                        "订单明细内的响应 DTO（读面回显 unitPrice×quantity），不落库"),
                site("com/migao/admin/service/ProcessingFeeCombinationCommandService.java",
                        "ProcessingFeeCombinationVersion.builder()", Admission.NO_NEW_INPUT_SOURCE,
                        "改价版本台账：记录的是同一笔已写入的 unit_price（根条目 = 本文件的 setUnitPrice）"),
                site("com/migao/admin/service/ProductionInstanceRepricingService.java",
                        "ProductionInstanceRepricingLog.builder()", Admission.NO_NEW_INPUT_SOURCE,
                        "补价台账：值来自计件价矩阵库列（currentMatrixPrices 读回值）"),
                site("com/migao/admin/service/ProductionOperationCommandService.java",
                        "ProductionOperationPosition.builder()", Admission.NO_NEW_INPUT_SOURCE,
                        "新增部位行的 fallback 价取自工序库既有单价（库列回读值）"),
                site("com/migao/admin/service/ProductionOperationCommandService.java",
                        "ProductionOperationPriceVersion.builder()", Admission.NO_NEW_INPUT_SOURCE,
                        "计件改价版本台账：记录同一笔 unit_price（根条目 = 本文件的 setUnitPrice）"),
                site("com/migao/admin/service/ProductionOperationPositionCommandService.java",
                        "ProductionOperationPositionPriceVersion.builder()", Admission.NO_NEW_INPUT_SOURCE,
                        "部位改价版本台账：记录同一笔已过 UNNECESSARY 准入的 unit_price"),
                site("com/migao/admin/service/ProductionSeedTemplateService.java", "ProductionOperation.builder()",
                        Admission.NO_NEW_INPUT_SOURCE,
                        "开租播种的计件单价是**代码内常量**，没有外部输入面"),
                site("com/migao/admin/service/ProductionSeedTemplateService.java",
                        "ProductionOperationPosition.builder()", Admission.NO_NEW_INPUT_SOURCE,
                        "开租播种的部位单价同上（代码内常量）"),
                site("com/migao/admin/service/ProductionSeedTemplateService.java",
                        "ProductionOperationPriceVersion.builder()", Admission.NO_NEW_INPUT_SOURCE,
                        "开租播种的改价版本台账同上（代码内常量）"),
                site("com/migao/admin/service/ProductionSeedTemplateService.java", "ProductionRouteRule.builder()",
                        Admission.NO_NEW_INPUT_SOURCE,
                        "开租播种的特殊选项对客单价同上（代码内常量）"),
                site("com/migao/admin/service/ProductionService.java", "ProcessingPositionOperation.builder()",
                        Admission.NO_NEW_INPUT_SOURCE,
                        "实例化部位工序时拷的是路线/工序库既有单价（库列回读值）"),
                site("com/migao/admin/service/ProductionService.java", "ProductionWorkLog.builder()",
                        Admission.NO_NEW_INPUT_SOURCE,
                        "报工台账的单价快照取自工序库（库列回读值），用于计件工资计算"),
                site("com/migao/admin/service/RemnantService.java", "FabricRemnant.builder()",
                        Admission.NO_NEW_INPUT_SOURCE,
                        "余料成本（recoveredUnitCost/recoveredAmount）取自批次库列回读值"),
                site("com/migao/admin/service/StockBatchConsumptionService.java", "StockBatchConsumption.builder()",
                        Admission.NO_NEW_INPUT_SOURCE,
                        "批次消耗台账的 unitCost 取自批次库列回读值"),
                site("com/migao/admin/support/fieldtruth/CustomerProfileTruthMask.java", "setTotalRefundAmount",
                        Admission.NO_NEW_INPUT_SOURCE,
                        "PII 脱敏：把金额置 null，不产生任何金额值")
        );
    }

    // ════════════════════════════ 判据 0~5（真实树）════════════════════════════

    @Test
    @DisplayName("判据 0~5：全仓金额入口台账双向对齐（未登记即红 / 台账不许空转 / 准入文本在 / 债务只许缩短）")
    void everyMoneyEntryIsRegisteredAndBacked() throws IOException {
        Map<String, Set<String>> discovered = discover(MAIN_ROOT);
        Map<String, String> texts = fileTexts(MAIN_ROOT, discovered.keySet());
        List<String> violations = validate(discovered, registry(), texts);

        long sites = discovered.values().stream().mapToLong(Set::size).sum();
        System.out.println("[#6221 元守卫] 现取：文件 " + discovered.size() + " 个 / 写面 " + sites
                + " 处；DEBT 现取 = " + registry().stream().filter(s -> s.admission() == Admission.DEBT).count()
                + "（冻结上限 " + FROZEN_DEBT_BASELINE + "）");
        discovered.forEach((f, symbols) -> System.out.println("[#6221 元守卫]   " + f + " ⇒ " + symbols));

        assertThat(violations)
                .as("金额入口台账有 %d 条违规（未登记 / 空转 / 缺准入文本 / 债务增长）", violations.size())
                .isEmpty();
    }

    @Test
    @DisplayName("判据 0'：扫描面非空（扫不到 = 空跑，必须红）")
    void scanSurfaceIsNotEmpty() throws IOException {
        assertThat(discover(MAIN_ROOT)).as("发现规则扫不到任何金额写面 ⇒ 守卫会静默空跑").isNotEmpty();
    }

    // ════════════════════════════ 判据 6~13：判别力自证（内存注入）════════════════════

    /** 干净夹具：一条 GATED + 一条 DEBT，且文本齐备。 */
    private static Map<String, Set<String>> cleanDiscovered() {
        Map<String, Set<String>> d = new TreeMap<>();
        d.put("A.java", new TreeSet<>(Set.of("setRefundAmount")));
        d.put("B.java", new TreeSet<>(Set.of("setUnitPrice")));
        return d;
    }

    private static List<Site> cleanRegistry() {
        return List.of(
                site("A.java", "setRefundAmount", Admission.GATED, "过 MoneyScale"),
                site("B.java", "setUnitPrice", Admission.DEBT, "无准入（跟单 #6228）"));
    }

    private static Map<String, String> cleanTexts() {
        Map<String, String> t = new LinkedHashMap<>();
        t.put("A.java", "var x = MoneyScale.requireTwoDecimalsOrNull(raw, \"金额\");");
        t.put("B.java", "row.setUnitPrice(raw);");
        return t;
    }

    @Test
    @DisplayName("判据 6：夹具不注入 ⇒ 零违规（证明红由注入引起，不是夹具本身红）")
    void cleanFixture_hasNoViolation() {
        assertThat(validate(cleanDiscovered(), cleanRegistry(), cleanTexts())).isEmpty();
    }

    @Test
    @DisplayName("判据 7：新增金额写面**未登记** ⇒ 具名红")
    void redproof_unregisteredMoneyWriteSite() {
        Map<String, Set<String>> discovered = cleanDiscovered();
        discovered.put("C.java", new TreeSet<>(Set.of("setActualAmount")));

        assertThat(validate(discovered, cleanRegistry(), cleanTexts()))
                .anySatisfy(v -> assertThat(v).contains("UNREGISTERED").contains("C.java").contains("setActualAmount"));
    }

    @Test
    @DisplayName("判据 8：台账条目**空转**（条目在、写面已摘）⇒ 红")
    void redproof_staleLedgerEntry() {
        Map<String, Set<String>> discovered = cleanDiscovered();
        discovered.remove("B.java");

        assertThat(validate(discovered, cleanRegistry(), cleanTexts()))
                .anySatisfy(v -> assertThat(v).contains("STALE-LEDGER").contains("B.java"));
    }

    @Test
    @DisplayName("判据 9：声称 GATED 但文件里**没有** MoneyScale 调用 ⇒ 红（登记未被兑现）")
    void redproof_gatedClaimWithoutGateText() {
        Map<String, String> texts = cleanTexts();
        texts.put("A.java", "var x = raw; // 声称过了准入，实际没有");

        assertThat(validate(cleanDiscovered(), cleanRegistry(), texts))
                .anySatisfy(v -> assertThat(v).contains("GATE-TEXT-MISSING").contains("A.java"));
    }

    @Test
    @DisplayName("判据 10：DEBT 条目不带 issue 号 ⇒ 红（豁免必须可追）")
    void redproof_debtWithoutIssueReference() {
        List<Site> reg = List.of(
                site("A.java", "setRefundAmount", Admission.GATED, "过 MoneyScale"),
                site("B.java", "setUnitPrice", Admission.DEBT, "无准入（没有跟单号）"));

        assertThat(validate(cleanDiscovered(), reg, cleanTexts()))
                .anySatisfy(v -> assertThat(v).contains("DEBT-WITHOUT-ISSUE").contains("B.java"));
    }

    @Test
    @DisplayName("判据 10'：豁免条目不写理由 ⇒ 红（不能空口说「不是输入源」）")
    void redproof_exemptionWithoutReason() {
        List<Site> reg = List.of(
                site("A.java", "setRefundAmount", Admission.GATED, "过 MoneyScale"),
                site("B.java", "setUnitPrice", Admission.NO_NEW_INPUT_SOURCE, " "));

        assertThat(validate(cleanDiscovered(), reg, cleanTexts()))
                .anySatisfy(v -> assertThat(v).contains("EXEMPT-WITHOUT-REASON").contains("B.java"));
    }

    @Test
    @DisplayName("判据 11：DEBT 条数**长过冻结上限** ⇒ 红（豁免只许缩短）")
    void redproof_debtGrowth() {
        List<Site> reg = new ArrayList<>(cleanRegistry());
        Map<String, Set<String>> discovered = cleanDiscovered();
        Set<String> b = new TreeSet<>(discovered.get("B.java"));
        for (int i = 0; i <= FROZEN_DEBT_BASELINE; i++) {
            reg.add(site("B.java", "setUnitPrice" + i, Admission.DEBT, "新增缺口（跟单 #6228）"));
            b.add("setUnitPrice" + i);
        }
        discovered.put("B.java", b);

        assertThat(validate(discovered, reg, cleanTexts()))
                .anySatisfy(v -> assertThat(v).contains("DEBT-GREW"));
    }

    @Test
    @DisplayName("判据 12：扫描面为空（发现规则失效）⇒ fail-closed 红")
    void redproof_emptyScanFailsClosed() {
        assertThat(validate(new TreeMap<>(), cleanRegistry(), cleanTexts()))
                .anySatisfy(v -> assertThat(v).contains("SCAN-EMPTY"));
    }

    @Test
    @DisplayName("判据 13：现取 DEBT 条数 ≤ 冻结上限（只许缩短；读数现场打印）")
    void liveDebtCountDoesNotExceedFrozenBaseline() {
        long debt = registry().stream().filter(s -> s.admission() == Admission.DEBT).count();
        assertThat(debt)
                .as("DEBT 条数现取 = %d（冻结上限 %d，只许缩短）", debt, FROZEN_DEBT_BASELINE)
                .isLessThanOrEqualTo(FROZEN_DEBT_BASELINE);
    }

    // ════════════════════════════ 发现 + 校验（纯函数，可注入）════════════════════════════

    /**
     * 发现规则（自动）：实体金额字段 ⇒ setter 调用点；金额实体 ⇒ builder 调用点。
     * 返回 `相对主源码根的文件路径 → 命中的符号集`。
     */
    static Map<String, Set<String>> discover(Path mainRoot) throws IOException {
        Set<String> moneyFields = new TreeSet<>();
        Set<String> moneyEntities = new TreeSet<>();
        Path entityRoot = mainRoot.resolve("com/migao/admin/entity");
        for (Path p : javaFiles(entityRoot)) {
            String text = Files.readString(p);
            Matcher m = MONEY_FIELD.matcher(text);
            boolean any = false;
            while (m.find()) {
                moneyFields.add(m.group(1));
                any = true;
            }
            if (any) {
                moneyEntities.add(p.getFileName().toString().replace(".java", ""));
            }
        }

        Map<String, Set<String>> found = new TreeMap<>();
        for (Path p : javaFiles(mainRoot)) {
            String text = Files.readString(p);
            String rel = relative(mainRoot, p);
            for (String field : moneyFields) {
                String setter = "set" + Character.toUpperCase(field.charAt(0)) + field.substring(1);
                // 带实参才算写面（`totals.setAmount()` 是**取**名为 setAmount 的字段，不是写）
                if (Pattern.compile("\\." + setter + "\\s*\\(\\s*[^)\\s]").matcher(text).find()) {
                    found.computeIfAbsent(rel, k -> new TreeSet<>()).add(setter);
                }
            }
            for (String entity : moneyEntities) {
                // 词边界：`InboundOrder.builder()` 不得被当成 `Order.builder()`
                if (Pattern.compile("(?<![A-Za-z0-9_])" + entity + "\\.builder\\(\\)").matcher(text).find()) {
                    found.computeIfAbsent(rel, k -> new TreeSet<>()).add(entity + ".builder()");
                }
            }
        }
        return found;
    }

    /** 台账校验（纯函数，便于内存注入红证）：返回**违规清单**（空 = 通过）。 */
    static List<String> validate(Map<String, Set<String>> discovered,
                                 List<Site> registry,
                                 Map<String, String> fileTexts) {
        List<String> violations = new ArrayList<>();
        if (discovered.isEmpty()) {
            violations.add("SCAN-EMPTY：发现规则没扫到任何金额写面 ⇒ 守卫在空跑（fail-closed）");
            return violations;
        }

        // ① 未登记即红（文件 :: 符号级）
        for (Map.Entry<String, Set<String>> e : discovered.entrySet()) {
            for (String symbol : e.getValue()) {
                boolean registered = registry.stream()
                        .anyMatch(s -> s.file().equals(e.getKey()) && s.symbol().equals(symbol));
                if (!registered) {
                    violations.add("UNREGISTERED：金额写面未登记 ⇒ " + e.getKey() + " :: " + symbol);
                }
            }
        }

        // ② 台账不许空转（登记的条目必须在扫描面里活着）
        for (Site s : registry) {
            if (!discovered.getOrDefault(s.file(), Set.of()).contains(s.symbol())) {
                violations.add("STALE-LEDGER：台账条目已不被扫到（写面被删/改名 ⇒ 同步台账）⇒ "
                        + s.file() + " :: " + s.symbol());
            }
        }

        // ③ 登记未被兑现：声称过准入的文件里必须有那条判据的文本
        for (Site s : registry) {
            String text = fileTexts.getOrDefault(s.file(), "");
            if (s.admission() == Admission.GATED && !text.contains(GATE_MARKER)) {
                violations.add("GATE-TEXT-MISSING：登记为 GATED 但文件里没有 " + GATE_MARKER
                        + " ⇒ " + s.file());
            }
            if (s.admission() == Admission.EQUIVALENT_GATED && !text.contains(EQUIVALENT_MARKER)) {
                violations.add("EQUIVALENT-TEXT-MISSING：登记为等价准入但文件里没有 " + EQUIVALENT_MARKER
                        + " ⇒ " + s.file());
            }
        }

        // ④ 债务必须可追（带 issue 号）；豁免必须给理由
        for (Site s : registry) {
            if (s.admission() == Admission.DEBT && !s.note().matches("(?s).*#\\d{3,}.*")) {
                violations.add("DEBT-WITHOUT-ISSUE：债务条目必须带跟进 issue 号 ⇒ " + s.file() + " :: " + s.symbol());
            }
            if (s.admission() == Admission.NO_NEW_INPUT_SOURCE && s.note().isBlank()) {
                violations.add("EXEMPT-WITHOUT-REASON：豁免条目必须写理由 ⇒ " + s.file() + " :: " + s.symbol());
            }
        }

        // ⑤ 豁免只许缩短（条数现取）
        long debt = registry.stream().filter(s -> s.admission() == Admission.DEBT).count();
        if (debt > FROZEN_DEBT_BASELINE) {
            violations.add("DEBT-GREW：DEBT 条数现取 = " + debt + "，冻结上限 = " + FROZEN_DEBT_BASELINE
                    + "（豁免只许缩短；新增金额写面请落 MoneyScale 准入而不是塞进台账）");
        }
        return violations;
    }

    private static List<Path> javaFiles(Path root) throws IOException {
        if (!Files.isDirectory(root)) {
            return List.of();
        }
        try (Stream<Path> walk = Files.walk(root)) {
            return walk.filter(p -> p.toString().endsWith(".java")).sorted().toList();
        }
    }

    private static String relative(Path root, Path file) {
        return root.relativize(file).toString().replace('\\', '/');
    }

    private static Map<String, String> fileTexts(Path mainRoot, Set<String> relatives) throws IOException {
        Map<String, String> texts = new LinkedHashMap<>();
        for (String rel : relatives) {
            texts.put(rel, Files.readString(mainRoot.resolve(rel)));
        }
        return texts;
    }
}
