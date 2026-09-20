package com.migao.admin.service;

// case_ids: PG-041, PG-042, PG-043

import com.migao.admin.entity.ProcessingFeeCombination;
import com.migao.admin.entity.ProcessingItem;
import com.migao.admin.entity.ProductionRouteRule;
import com.migao.admin.mapper.ProcessingFeeCombinationMapper;
import com.migao.admin.mapper.ProductionRouteRuleMapper;
import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.when;

/**
 * 加工费**消费面**：按选配组合取价（issue #4406，P1；用户裁定 2026-09-19）。
 *
 * <h2>为什么必须有这个类</h2>
 * #4386 交付了「商家能配组合价」，但下单侧仍按 **Σ 加工项单价 × 数量** 算 ⇒
 * 配了组合费用**订单金额一分不变**（可达性判据：谁发射 / 哪个入口可达 / 有无测试钉住 —— 前两项都答不出）。
 * 本类 = 那个消费点：**选配 → 归一化组合键 → 匹配 {@code processing_fee_combinations} → 单价 × 加工费米数**。
 *
 * <h2>口径（用户裁定，不得自行放宽）</h2>
 * 「**未定价组合 ⇒ 加工费 = 0（unpriced），直接切，不回落 Σ 加工项**」
 * ⇒ 未命中**绝不**静默套任何默认价（#4308「静默回落」同族纪律：静默 = 算错钱且无人知道）。
 *
 * <h2>每条判据的红证（不会红的断言 = 空断言）</h2>
 * <ul>
 *   <li><b>判据 1（红证）</b>：选配组合命中组合价 ⇒ 金额 = 该组合单价 × 加工费米数。
 *       修复前 {@code OrderService.sumProcessingFee} = Σ 加工项 ⇒ 今天必红；</li>
 *   <li><b>判据 2（红证，注入法）</b>：未定价组合 ⇒ 金额 **0** + {@code fee_source=unpriced} + 可行动提示。
 *       注入法：让未命中分支返回任意非 0 金额（或回落 Σ 加工项）⇒ 本用例红；</li>
 *   <li><b>判据 3</b>：组合键归一化**复用** {@link ProcessingFeeCombinationCommandService#compositionKey}
 *       ⇒ 书写顺序无关（`韩褶+打孔+定型` ≡ `定型+打孔+韩褶`，同一笔钱）；</li>
 *   <li><b>判据 4（R15）</b>：组合费用**无商品维度** —— 同一选配在任意商品上取到**同一个价**；</li>
 *   <li><b>判据 5（R9）</b>：两套账不互读 —— 对外加工费**不得**由 {@code production_operations.unit_price}
 *       算出（注入法：给加工项目录/工序一个完全不同的单价，断言金额一字不变）。</li>
 * </ul>
 *
 * <h2>加工费米数 = 该樘窗主布行米数（裁定 R-b）</h2>
 * 纱**不另按米收**（纱那部分的加工已含在组合档位单价里）。故米数取
 * {@code processing_info.processingMeters}（算料侧主布行米数），兼容键 {@code fabric_meters}。
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("加工费消费面：按选配组合取价（issue #4406）")
class ProcessingFeeCalculatorTest {

    private static final Long TENANT = 1L;

    @Mock
    private ProcessingFeeCombinationMapper combinationMapper;

    @Mock
    private ProductionRouteRuleMapper routeRuleMapper;

    private ProcessingFeeCalculator calculator;

    @BeforeEach
    void setUp() {
        // 取价查询用 `LambdaQueryWrapper<…>` ⇒ 断言查询条件需要 lambda 缓存
        // （否则 `getSqlSegment()` 抛「can not find lambda cache」，断言退化成错误而不是结论）
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(assistant, ProcessingFeeCombination.class);
        TableInfoHelper.initTableInfo(assistant, ProductionRouteRule.class);
        // 默认：租户没有任何特殊选项价（既有用例的基线 —— 没选选项 ⇒ 金额与 #4406 逐分相同）
        lenient().when(routeRuleMapper.selectList(any())).thenReturn(List.of());
        calculator = new ProcessingFeeCalculator(combinationMapper, routeRuleMapper);
    }

    // ══════════════════════════ 夹具 ══════════════════════════

    /** 组合定价行（唯一键 (tenant_id, composition_key) WHERE deleted = 0）。 */
    private static ProcessingFeeCombination combination(String key, String unitPrice) {
        return ProcessingFeeCombination.builder()
                .id("combo-" + key)
                .tenantId(TENANT)
                .compositionKey(key)
                .unitPrice(new BigDecimal(unitPrice))
                .status("active")
                .sortOrder(0)
                .source("实证")
                .deleted(0)
                .build();
    }

    /** 特殊选项规则行（V77 起带 `customer_unit_price`，元/套）。 */
    private static ProductionRouteRule optionRule(String name, String customerUnitPrice) {
        return ProductionRouteRule.builder()
                .id("rr-option-" + name)
                .tenantId(TENANT)
                .triggerKind("option")
                .triggerValue(name)
                .action("insert")
                .status("active")
                .customerUnitPrice(customerUnitPrice == null ? null : new BigDecimal(customerUnitPrice))
                .deleted(0)
                .build();
    }

    private void givenCombinations(ProcessingFeeCombination... rows) {
        when(combinationMapper.selectList(any())).thenReturn(List.of(rows));
    }

    /** 特殊选项价目（`customer_unit_price` 非空的行；NULL 行**不参与**取价 ⇒ `priced:false`）。 */
    private void givenOptionRules(ProductionRouteRule... rows) {
        when(routeRuleMapper.selectList(any())).thenReturn(List.of(rows));
    }

    /** 订单行选配（唯一生产者的形态：`processing_info` 顶层 + `processingItems[].name`）。 */
    private static Map<String, Object> processingInfo(Object meters, String... itemNames) {
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("curtainType", "布帘");
        info.put("craft", "韩褶");
        if (meters != null) {
            info.put("processingMeters", meters);
        }
        List<Map<String, Object>> items = new ArrayList<>();
        for (String name : itemNames) {
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("id", "pi-" + name);
            entry.put("name", name);
            // 加工项目录单价（Σ 口径的输入）：刻意给一个与组合价完全不同的数
            // ⇒ 判据 1/2/5 的注入法都能证伪「还在 Σ 加工项」。
            entry.put("unitPrice", new BigDecimal("9.50"));
            entry.put("quantity", new BigDecimal("2"));
            entry.put("unit", "米");
            items.add(entry);
        }
        info.put("processingItems", items);
        return info;
    }

    private ProcessingFeeCalculator.Fee compute(Map<String, Object> info) {
        return calculator.feesFor(List.of(info), TENANT).get(0);
    }

    // ══════════════════════════ 判据 1：命中组合价 ══════════════════════════

    @Test
    @DisplayName("判据 1·命中组合 ⇒ 金额 = 组合单价 × 加工费米数（不再 Σ 加工项）")
    void matchedCombinationUsesCombinationPriceTimesProcessingMeters() {
        givenCombinations(combination("定型+打孔+韩褶", "8.00"));

        ProcessingFeeCalculator.Fee fee = compute(processingInfo(
                new BigDecimal("12.30"), "韩褶", "打孔", "定型"));

        // 组合价 ¥8.00/m × 12.30m = 98.40（**不是** Σ 加工项 9.50 × 2 = 19.00）
        assertThat(fee.amount()).isEqualByComparingTo("98.40");
        assertThat(fee.amount()).isNotEqualByComparingTo("19.00");
        assertThat(fee.feeSource()).isEqualTo("matched");
        assertThat(fee.compositionKey()).isEqualTo("定型+打孔+韩褶");
        assertThat(fee.unitPrice()).isEqualByComparingTo("8.00");
        assertThat(fee.priceSource()).isEqualTo("实证");
        assertThat(fee.meters()).isEqualByComparingTo("12.30");
        assertThat(fee.metersSource()).isEqualTo("processingMeters");
        assertThat(fee.matchedRuleId()).isEqualTo("combo-定型+打孔+韩褶");
        // 可审计：组合 / 命中哪条规则 / 单价 / 单价来源 / 米数 / 米数来源 / 三态 逐键可见
        assertThat(fee.detail())
                .containsEntry("composition", "定型+打孔+韩褶")
                .containsEntry("matched_rule_id", "combo-定型+打孔+韩褶")
                .containsEntry("unit_price", new BigDecimal("8.00"))
                .containsEntry("price_source", "实证")
                .containsEntry("meters", new BigDecimal("12.30"))
                .containsEntry("meters_source", "processingMeters")
                .containsEntry("fee_source", "matched");
        assertThat(fee.detail().get("items")).isEqualTo(List.of("定型", "打孔", "韩褶"));
        // #4525 回归不变量：**没选特殊选项** ⇒ 空数组 + 合计 0 ⇒ 行金额与改前逐分相同
        assertThat(fee.specialOptions()).isEmpty();
        assertThat(fee.specialOptionsTotal()).isEqualByComparingTo("0");
        assertThat(fee.lineAmount()).isEqualByComparingTo(fee.amount());
        assertThat(fee.lineAmount()).isEqualByComparingTo("98.40");
        assertThat(fee.detail())
                .containsEntry("special_options", List.of());
        assertThat((BigDecimal) fee.detail().get("special_options_total")).isEqualByComparingTo("0");
    }

    @Test
    @DisplayName("判据 1·组合键归一化与书写顺序无关（同一笔钱，命中同一条规则）")
    void compositionKeyOrderIndependent() {
        givenCombinations(combination("定型+打孔+韩褶", "8.00"));

        ProcessingFeeCalculator.Fee reordered = compute(processingInfo(
                new BigDecimal("10.00"), "定型", "打孔", "韩褶"));
        ProcessingFeeCalculator.Fee original = compute(processingInfo(
                new BigDecimal("10.00"), "韩褶", "打孔", "定型"));

        assertThat(reordered.compositionKey()).isEqualTo("定型+打孔+韩褶");
        assertThat(reordered.amount()).isEqualByComparingTo(original.amount());
        assertThat(reordered.amount()).isEqualByComparingTo("80.00");
    }

    // ══════════════════════════ 判据 2：未定价 ⇒ 0 + unpriced ══════════════════════════

    @Test
    @DisplayName("判据 2·未定价组合 ⇒ 金额 0 + fee_source=unpriced + 可行动提示（绝不回落 Σ 加工项）")
    void unpricedCombinationYieldsZeroWithActionableHint() {
        givenCombinations(combination("定型+打孔+韩褶", "8.00"));

        // 注入法：库里只有「定型+打孔+韩褶」，本行选配是「打孔+定型」⇒ 无命中。
        // 若本分支给出**任意非 0 金额**（含回落 Σ 加工项 9.50 × 2 = 19.00、或套默认档 8.00/m）
        // ⇒ 下面两条断言红。
        ProcessingFeeCalculator.Fee fee = compute(processingInfo(
                new BigDecimal("12.30"), "打孔", "定型"));

        assertThat(fee.amount()).isEqualByComparingTo("0");
        assertThat(fee.feeSource()).isEqualTo("unpriced");
        // 提示按**归一化键**写（读的人与库里 `composition_key` 看到同一个串，不必自己再归一一次）
        assertThat(fee.hint()).isNotBlank().contains("定型+打孔").contains("加工费");
        assertThat(fee.detail())
                .containsEntry("fee_source", "unpriced")
                .containsEntry("unit_price", null)
                .containsEntry("matched_rule_id", null);
    }

    @Test
    @DisplayName("判据 2·库里一条组合价都没有（商家未配置）⇒ 同样 0 + unpriced，不静默套默认价")
    void emptyCombinationTableYieldsZeroNotDefaultPrice() {
        givenCombinations();

        ProcessingFeeCalculator.Fee fee = compute(processingInfo(
                new BigDecimal("12.30"), "韩褶", "打孔", "定型"));

        assertThat(fee.amount()).isEqualByComparingTo("0");
        assertThat(fee.feeSource()).isEqualTo("unpriced");
        assertThat(fee.hint()).isNotBlank();
    }

    // ══════════════════════════ 判据 4：无商品维度（R15）══════════════════════════

    @Test
    @DisplayName("判据 4（R15）·同一选配在任意商品上取到同一个价（组合费用无商品维度）")
    void sameCompositionSamePriceOnAnyProduct() {
        givenCombinations(combination("定型+打孔+韩褶", "8.00"));

        // 两份 processing_info 的**唯一差别**是商品侧信息（`productId` / `productName`）——
        // 取价路径不看它们（#4371 解耦后组合费用表是店铺级、无商品维度）。
        Map<String, Object> onCurtain = processingInfo(new BigDecimal("10.00"), "韩褶", "打孔", "定型");
        onCurtain.put("productId", "prod-curtain");
        onCurtain.put("productName", "蜂巢帘");
        Map<String, Object> onSheer = processingInfo(new BigDecimal("10.00"), "韩褶", "打孔", "定型");
        onSheer.put("productId", "prod-sheer");
        onSheer.put("productName", "纱帘");
        onSheer.put("curtainType", "纱帘");

        ProcessingFeeCalculator.Fee a = compute(onCurtain);
        ProcessingFeeCalculator.Fee b = compute(onSheer);

        assertThat(a.unitPrice()).isEqualByComparingTo(b.unitPrice());
        assertThat(a.amount()).isEqualByComparingTo(b.amount());
        assertThat(a.amount()).isEqualByComparingTo("80.00");
    }

    // ══════════════════════════ 判据 5：两套账不互读（R9）══════════════════════════

    @Test
    @DisplayName("判据 5（R9）·对外加工费不得由工序单价算出（加工项目录/工序价改动 ⇒ 金额一字不变）")
    void processingFeeNeverDerivedFromOperationUnitPrice() {
        givenCombinations(combination("定型+打孔+韩褶", "8.00"));

        // 注入法：`production_operations.unit_price`（内部计件单价）与加工项目录价都是
        // 完全不同的数（¥99.99 / ¥9.50），若加工费走了任一处 ⇒ 金额 ≠ 8.00 × 10.00 ⇒ 红。
        ProcessingItem operationLookalike = new ProcessingItem();
        operationLookalike.setName("定型");
        operationLookalike.setUnitPrice(new BigDecimal("99.99"));
        Map<String, Object> info = processingInfo(new BigDecimal("10.00"), "韩褶", "打孔", "定型");
        info.put("productionOperations", List.of(Map.of("name", "定型-布", "unitPrice", new BigDecimal("99.99"))));

        ProcessingFeeCalculator.Fee fee = compute(info);

        assertThat(fee.amount()).isEqualByComparingTo("80.00");
        assertThat(fee.unitPrice()).isEqualByComparingTo("8.00");
        assertThat(operationLookalike.getUnitPrice()).isEqualByComparingTo("99.99"); // 前置自断言：两套账的数确实不同
    }

    // ══════════════════════════ 加工费米数（裁定 R-b）══════════════════════════

    @Test
    @DisplayName("米数取主布行（processingMeters）；缺键时兼容 fabric_meters 并记下米数来源")
    void metersFallBackToFabricMetersAndRecordSource() {
        givenCombinations(combination("定型+打孔+韩褶", "8.00"));

        Map<String, Object> info = processingInfo(null, "韩褶", "打孔", "定型");
        info.put("fabric_meters", new BigDecimal("6.60"));

        ProcessingFeeCalculator.Fee fee = compute(info);

        assertThat(fee.meters()).isEqualByComparingTo("6.60");
        assertThat(fee.metersSource()).isEqualTo("fabric_meters");
        assertThat(fee.amount()).isEqualByComparingTo("52.80");
    }

    @Test
    @DisplayName("命中组合但**米数缺失** ⇒ 金额 0 且 fee_source=unpriced（不凭数量猜米数）")
    void matchedCombinationWithoutMetersYieldsZero() {
        givenCombinations(combination("定型+打孔+韩褶", "8.00"));

        // 注入法：若缺米数时改用 `quantity`（=2）或补默认米数 ⇒ 金额 ≠ 0 ⇒ 红。
        ProcessingFeeCalculator.Fee fee = compute(processingInfo(null, "韩褶", "打孔", "定型"));

        assertThat(fee.amount()).isEqualByComparingTo("0");
        assertThat(fee.feeSource()).isEqualTo("unpriced");
        assertThat(fee.unitPrice()).isEqualByComparingTo("8.00"); // 价命中了，缺的是米数
        assertThat(fee.hint()).isNotBlank().contains("米数");
        // 本行**没选**任何特殊选项 ⇒ 选项那半为 0（issue #4594 后：选了且已定价的选项**会照计**，
        // 与米数是否齐全无关 —— 那两条判据见 missingMetersStillChargesPricedSpecialOptions）
        assertThat(fee.specialOptionsTotal()).isEqualByComparingTo("0");
        assertThat(fee.lineAmount()).isEqualByComparingTo("0");
    }

    // ══════════════════════════ #4525 特殊选项按套计价（判据 1/2/3/10）══════════════════════════

    @Test
    @DisplayName("判据 1·加工费 = 组合价 × 米数 + Σ(选项价 × 套数)，逐分可核对（只算组合那半 ⇒ 红）")
    void specialOptionsAddPerSetFeeOnTopOfCombinationHalf() {
        givenCombinations(combination("定型+打孔+韩褶", "8.00"));
        givenOptionRules(optionRule("加铅块", "6.00"), optionRule("接高", "2.50"));

        Map<String, Object> info = processingInfo(new BigDecimal("12.30"), "韩褶", "打孔", "定型");
        info.put("specialOptions", List.of("加铅块", "接高"));
        ProcessingFeeCalculator.Fee fee = compute(info);

        // 组合那半：8.00 × 12.30 = 98.40；选项那半：(6.00 + 2.50) × 1 = 8.50
        assertThat(fee.amount()).isEqualByComparingTo("98.40");
        assertThat(fee.specialOptionsTotal()).isEqualByComparingTo("8.50");
        assertThat(fee.lineAmount()).isEqualByComparingTo("106.90");
        // 逐项可核对（每项 = 单价 × 计费套数；本行自成樘窗 ⇒ 套数 1 —— R8 改判 #4725：
        // 「1 套 = 1 樘窗（craftLineId 组）」；同樘窗其它行的同名选项 sets=0，见
        // sameOptionInOneWindowIsChargedOncePerWindow）
        assertThat(fee.specialOptions()).hasSize(2);
        for (ProcessingFeeCalculator.SpecialOption option : fee.specialOptions()) {
            assertThat(option.sets()).isEqualTo(1);
            assertThat(option.priced()).isTrue();
            assertThat(option.amount()).isEqualByComparingTo(option.unitPrice());
        }
        // 只算组合那半 ⇒ 106.90 vs 98.40 必红
        assertThat(fee.lineAmount()).isNotEqualByComparingTo(fee.amount());
        // detail 契约（设计 §4.3：新增键只加不改）
        assertThat(fee.detail()).containsKeys("special_options", "special_options_total");
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> rows = (List<Map<String, Object>>) fee.detail().get("special_options");
        assertThat(rows).hasSize(2);
        assertThat(rows.get(0)).containsEntry("name", "加铅块")
                .containsEntry("sets", 1).containsEntry("priced", true);
        assertThat(rows.get(0).get("unit_price")).isEqualTo(new BigDecimal("6.00"));
        assertThat(rows.get(0).get("amount")).isEqualTo(new BigDecimal("6.00"));
    }

    // ══════════════════ #4725（用户裁定「一樘窗 = 一套」）：套数按**樘窗组**计 ══════════════════

    @Test
    @DisplayName("#4725 一樘窗 = 一套：同樘窗（craftLineId）两行都选「加铅块」⇒ 该樘窗**只收一次**（旧口径 = 两次）")
    void sameOptionInOneWindowIsChargedOncePerWindow() {
        givenCombinations(combination("定型+打孔+韩褶", "8.00"));
        givenOptionRules(optionRule("加铅块", "6.00"));

        // 一樘窗的两条部位行（布帘 + 纱帘），同 `craftLineId` ⇒ **同一套**
        Map<String, Object> cloth = processingInfo(new BigDecimal("12.30"), "韩褶", "打孔", "定型");
        cloth.put("craftLineId", "win-1");
        cloth.put("specialOptions", List.of("加铅块"));
        Map<String, Object> sheer = processingInfo(null, "打孔");
        sheer.put("craftLineId", "win-1");
        sheer.put("specialOptions", List.of("加铅块"));

        List<ProcessingFeeCalculator.Fee> fees = calculator.feesFor(List.of(cloth, sheer), TENANT);

        // 一樘窗 = 一套 ⇒ 该樘窗的「加铅块」（¥6.00/套）只收 ¥6.00 一次
        assertThat(fees.get(0).specialOptionsTotal()).isEqualByComparingTo("6.00");
        assertThat(fees.get(1).specialOptionsTotal())
                .as("旧口径（每行各按 1 套收）⇒ 6.00 ⇒ 必红").isEqualByComparingTo("0");
        // **不静默**：第二行照旧列出该选项（名称 / 单价 / 定价态可见），只是本行计费套数 = 0
        assertThat(fees.get(1).specialOptions()).singleElement().satisfies(option -> {
            assertThat(option.name()).isEqualTo("加铅块");
            assertThat(option.sets()).isZero();
            assertThat(option.amount()).isEqualByComparingTo("0");
            assertThat(option.priced()).isTrue();
            assertThat(option.unitPrice()).isEqualByComparingTo("6.00");
        });
        // 套身份可审计：两行同属一樘窗 ⇒ **同一个** `set_key`
        assertThat(fees.get(0).detail()).containsEntry("set_key", "win-1");
        assertThat(fees.get(1).detail()).containsEntry("set_key", "win-1");
    }

    @Test
    @DisplayName("#4725 反向护栏：无 craftLineId 的两行 ⇒ 各自成樘窗 ⇒ 各收一次（与改前逐分相同）")
    void linesWithoutCraftLineIdAreTheirOwnWindows() {
        givenCombinations(combination("定型+打孔+韩褶", "8.00"));
        givenOptionRules(optionRule("加铅块", "6.00"));

        Map<String, Object> first = processingInfo(new BigDecimal("12.30"), "韩褶", "打孔", "定型");
        first.put("specialOptions", List.of("加铅块"));
        Map<String, Object> second = processingInfo(new BigDecimal("1.00"), "韩褶", "打孔", "定型");
        second.put("specialOptions", List.of("加铅块"));

        List<ProcessingFeeCalculator.Fee> fees = calculator.feesFor(List.of(first, second), TENANT);

        // 8.00×12.30 + 6.00 = 104.40；8.00×1.00 + 6.00 = 14.00（两樘窗各一套，逐值 = 改前）
        assertThat(fees.get(0).specialOptionsTotal()).isEqualByComparingTo("6.00");
        assertThat(fees.get(1).specialOptionsTotal()).isEqualByComparingTo("6.00");
        assertThat(fees.get(0).lineAmount()).isEqualByComparingTo("104.40");
        assertThat(fees.get(1).lineAmount()).isEqualByComparingTo("14.00");
    }

    @Test
    @DisplayName("判据 1·选项名按 **全名 Unicode 码点升序**（与书写顺序无关，两次生成逐值相同）")
    void specialOptionsAreSortedByCodePoint() {        givenCombinations(combination("定型+打孔+韩褶", "8.00"));
        // ⚠️ 判据必须用**首字符相同**的两个选项，否则「只比第一位」的实现也能通过
        // （实证：`接高`(U+63A5) 与 `加铅块`(U+52A0) 首字符不同 ⇒ 首字符比较同样得
        //  「加铅块, 接高」⇒ 那是**非判别性**判据 = 空断言）。
        // `加铅块`(加 U+52A0 + 铅 U+94C5) 与 `加花边`(加 U+52A0 + 花 U+82B1)：
        // 首字符**相同**，第二位 花(U+82B1) < 铅(U+94C5) ⇒ 全名序 = 「加花边」在前。
        givenOptionRules(optionRule("接高", "2.50"), optionRule("加铅块", "6.00"),
                optionRule("加花边", "1.50"));

        Map<String, Object> info = processingInfo(new BigDecimal("10.00"), "韩褶", "打孔", "定型");
        info.put("specialOptions", List.of("加铅块", "接高", "加花边"));   // 书写序 ≠ 码点序
        ProcessingFeeCalculator.Fee fee = compute(info);

        // 全名码点升序 ⇒ 加花边(U+82B1) < 加铅块(U+94C5) < 接高(U+63A5)？注意「接」U+63A5 < 「花」U+82B1
        // ⇒ 真序 = 接高(63A5) < 加花边(52A0 82B1)？「加」U+52A0 < 「接」U+63A5 ⇒ 加* 在前。
        // ⇒ 最终：加花边(52A0,82B1) < 加铅块(52A0,94C5) < 接高(63A5)
        assertThat(fee.specialOptions()).extracting(ProcessingFeeCalculator.SpecialOption::name)
                .containsExactly("加花边", "加铅块", "接高");
        assertThat(fee.specialOptionsTotal()).isEqualByComparingTo("10.00");

        // 换书写顺序 ⇒ 明细**逐值相同**（顺序不确定 = 同一张单两次生成不同明细）
        Map<String, Object> reordered = processingInfo(new BigDecimal("10.00"), "韩褶", "打孔", "定型");
        reordered.put("specialOptions", List.of("接高", "加花边", "加铅块"));
        assertThat(compute(reordered).specialOptions()).isEqualTo(fee.specialOptions());
        // 再换一次（把两个**首字符相同**的选项对调）—— 只比首字符的实现会在这里分叉
        Map<String, Object> reordered2 = processingInfo(new BigDecimal("10.00"), "韩褶", "打孔", "定型");
        reordered2.put("specialOptions", List.of("加铅块", "加花边", "接高"));
        assertThat(compute(reordered2).specialOptions()).isEqualTo(fee.specialOptions());
    }

    @Test
    @DisplayName("判据 3·选项未定价（customer_unit_price IS NULL）⇒ priced:false + 计 0 + 可行动 hint")
    void unpricedOptionIsExplicitlyVisibleAndNotSilentlyZero() {
        givenCombinations(combination("定型+打孔+韩褶", "8.00"));
        // 注入法：库里「接高」的 `customer_unit_price` 是 NULL ⇒ 取价侧命中不到 ⇒ priced:false。
        // 若把它当 0 静默处理（不给 hint、priced 仍 true）⇒ 下面断言红。
        givenOptionRules(optionRule("加铅块", "6.00"));

        Map<String, Object> info = processingInfo(new BigDecimal("10.00"), "韩褶", "打孔", "定型");
        info.put("specialOptions", List.of("加铅块", "接高"));
        ProcessingFeeCalculator.Fee fee = compute(info);

        // 组合那半有效 ⇒ fee_source 仍 matched（设计 §4.2）
        assertThat(fee.feeSource()).isEqualTo("matched");
        assertThat(fee.amount()).isEqualByComparingTo("80.00");
        // 未定价项：单价 null + priced:false + 计 0
        ProcessingFeeCalculator.SpecialOption unpriced = fee.specialOptions().stream()
                .filter(o -> o.name().equals("接高")).findFirst().orElseThrow();
        assertThat(unpriced.unitPrice()).isNull();
        assertThat(unpriced.priced()).isFalse();
        assertThat(unpriced.amount()).isEqualByComparingTo("0");
        // 已定价项照收
        assertThat(fee.specialOptionsTotal()).isEqualByComparingTo("6.00");
        assertThat(fee.lineAmount()).isEqualByComparingTo("86.00");
        // **可行动** hint（指向定价入口）—— 静默按 0 收 ⇒ hint 为 null ⇒ 红
        assertThat(fee.hint()).isNotBlank().contains("接高").contains("未定价")
                .contains("/production/processing-fees");
        assertThat(fee.detail()).containsEntry("hint", fee.hint());
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> rows = (List<Map<String, Object>>) fee.detail().get("special_options");
        assertThat(rows.stream().filter(r -> "接高".equals(r.get("name"))).findFirst().orElseThrow())
                .containsEntry("priced", false).containsEntry("unit_price", null);
    }

    @Test
    @DisplayName("判据 2·组合未命中 ⇒ **组合那半** 0 + unpriced；**已定价选项照计**（issue #4594 裁定）")
    void unmatchedCombinationStillChargesPricedSpecialOptions() {
        givenCombinations(combination("定型+打孔+韩褶", "8.00"));
        givenOptionRules(optionRule("加铅块", "6.00"));

        // 本行选配「打孔+定型」（库里没这个组合）⇒ 组合那半 0；选项「加铅块」有价 ⇒ **照计 6.00**
        // （用户裁定 2026-09-19：选项是按套的独立一笔账，与组合是否定价无关）。
        // 注入法：① 未定价分支把选项那半丢掉（`specialOptionsTotal` = 0）⇒ 红；
        //         ② 回落 Σ 加工项（9.50 × 2 = 19.00）⇒ 红。
        Map<String, Object> info = processingInfo(new BigDecimal("12.30"), "打孔", "定型");
        info.put("specialOptions", List.of("加铅块"));
        ProcessingFeeCalculator.Fee fee = compute(info);

        assertThat(fee.feeSource()).isEqualTo("unpriced");
        // `amount` 仍是**组合那半**（键名与语义一字未动）—— 未定价 ⇒ 那半 0
        assertThat(fee.amount()).isEqualByComparingTo("0");
        assertThat(fee.lineAmount()).isEqualByComparingTo("6.00");
        assertThat(fee.lineAmount()).isNotEqualByComparingTo("19.00");
        assertThat(fee.specialOptionsTotal()).isEqualByComparingTo("6.00");
        assertThat(fee.specialOptions()).hasSize(1);
        assertThat(fee.specialOptions().get(0).name()).isEqualTo("加铅块");
        assertThat(fee.specialOptions().get(0).priced()).isTrue();
        // 可审计构成里两半都在：组合那半 0 + 选项那半 6.00（选项未因组合未定价而消失）
        assertThat(fee.detail()).containsEntry("fee_source", "unpriced")
                .containsEntry("amount", BigDecimal.ZERO);
        assertThat((BigDecimal) fee.detail().get("special_options_total")).isEqualByComparingTo("6.00");
        assertThat((List<?>) fee.detail().get("special_options")).hasSize(1);
    }

    @Test
    @DisplayName("判据 2·组合未命中 + 选项**也未定价** ⇒ 行金额 0，且两半都能看出「未定价」")
    void unmatchedCombinationWithUnpricedOptionStaysZeroAndVisible() {
        givenCombinations(combination("定型+打孔+韩褶", "8.00"));
        givenOptionRules(optionRule("加铅块", null));

        Map<String, Object> info = processingInfo(new BigDecimal("12.30"), "打孔", "定型");
        info.put("specialOptions", List.of("加铅块"));
        ProcessingFeeCalculator.Fee fee = compute(info);

        assertThat(fee.feeSource()).isEqualTo("unpriced");
        assertThat(fee.lineAmount()).isEqualByComparingTo("0");
        // 选项未定价 ⇒ `priced:false` 显式可见（不许静默按 0 收）
        assertThat(fee.specialOptions()).hasSize(1);
        assertThat(fee.specialOptions().get(0).priced()).isFalse();
        assertThat(fee.specialOptions().get(0).unitPrice()).isNull();
    }

    @Test
    @DisplayName("判据 2·**缺米数** + 已定价选项 ⇒ 组合那半 0，选项价照计（选项与米数无关）")
    void missingMetersStillChargesPricedSpecialOptions() {
        givenCombinations(combination("定型+打孔+韩褶", "8.00"));
        givenOptionRules(optionRule("加铅块", "6.00"));

        Map<String, Object> info = processingInfo(null, "韩褶", "打孔", "定型");
        info.put("specialOptions", List.of("加铅块"));
        ProcessingFeeCalculator.Fee fee = compute(info);

        assertThat(fee.feeSource()).isEqualTo("unpriced");
        assertThat(fee.amount()).isEqualByComparingTo("0");
        assertThat(fee.unitPrice()).isEqualByComparingTo("8.00"); // 价命中了，缺的是米数
        assertThat(fee.lineAmount()).isEqualByComparingTo("6.00");
        assertThat(fee.specialOptionsTotal()).isEqualByComparingTo("6.00");
    }

    @Test
    @DisplayName("判据 2·**无加工项（空组合）** + 已定价选项 ⇒ 选项价照计（选项是独立一笔账）")
    void emptyCompositionStillChargesPricedSpecialOptions() {
        givenCombinations(combination("定型+打孔+韩褶", "8.00"));
        givenOptionRules(optionRule("加铅块", "6.00"));

        Map<String, Object> info = processingInfo(new BigDecimal("12.30"));
        info.put("specialOptions", List.of("加铅块"));
        ProcessingFeeCalculator.Fee fee = compute(info);

        assertThat(fee.compositionKey()).isEmpty();
        assertThat(fee.feeSource()).isEqualTo("unpriced");
        assertThat(fee.amount()).isEqualByComparingTo("0");
        assertThat(fee.lineAmount()).isEqualByComparingTo("6.00");
        assertThat(fee.specialOptionsTotal()).isEqualByComparingTo("6.00");
    }

    @Test
    @DisplayName("判据 10·两套账不互读：同表的计件系数档（factor）改了 ⇒ 对客加工费一字不变")
    void customerFeeNeverReadsPieceworkFactor() {
        givenCombinations(combination("定型+打孔+韩褶", "8.00"));
        // 同一张表里塞一条**计件系数档**（车间成本账，`action='factor'`）——
        // 注入法：若取价读 `factor`（或把 factor 行当选项价）⇒ 金额 ≠ 98.40 + 6.00 ⇒ 红。
        givenOptionRules(optionRule("加铅块", "6.00"), ProductionRouteRule.builder()
                .id("rr-factor-加铅块").tenantId(TENANT).triggerKind("option")
                .triggerValue("加铅块").action("factor").operation(null)
                .factor(new BigDecimal("1.700")).status("active").deleted(0).build());

        Map<String, Object> info = processingInfo(new BigDecimal("12.30"), "韩褶", "打孔", "定型");
        info.put("specialOptions", List.of("加铅块"));
        ProcessingFeeCalculator.Fee fee = compute(info);

        assertThat(fee.amount()).isEqualByComparingTo("98.40");
        assertThat(fee.specialOptionsTotal()).isEqualByComparingTo("6.00");
        assertThat(fee.lineAmount()).isEqualByComparingTo("104.40");
    }

    @Test
    @DisplayName("特殊选项匹配**精确相等**（不得 contains）：名字差一个字 ⇒ 视为未定价，不误收")
    void specialOptionMatchingIsExact() {
        givenCombinations(combination("定型+打孔+韩褶", "8.00"));
        givenOptionRules(optionRule("加铅块", "6.00"));

        Map<String, Object> info = processingInfo(new BigDecimal("10.00"), "韩褶", "打孔", "定型");
        info.put("specialOptions", List.of("铅块"));   // 缺「加」字 ⇒ 不是同一个选项
        ProcessingFeeCalculator.Fee fee = compute(info);

        assertThat(fee.specialOptionsTotal()).isEqualByComparingTo("0");
        assertThat(fee.specialOptions().get(0).priced()).isFalse();
        assertThat(fee.lineAmount()).isEqualByComparingTo("80.00");
    }

    @Test
    @DisplayName("读面（storedFee）：落库明细里的选项价原样读出，**不重算**（R13 快照冻结）")
    void storedFeeReadsPersistedSpecialOptions() {
        Map<String, Object> detail = new LinkedHashMap<>();
        detail.put("composition", "定型+打孔+韩褶");
        detail.put("items", List.of("定型", "打孔", "韩褶"));
        detail.put("unit_price", new BigDecimal("8.00"));
        detail.put("meters", new BigDecimal("12.30"));
        detail.put("fee_source", "matched");
        detail.put("amount", new BigDecimal("98.40"));
        detail.put("special_options", List.of(Map.of(
                "name", "加铅块", "unit_price", new BigDecimal("6.00"), "sets", 1,
                "amount", new BigDecimal("6.00"), "priced", true)));
        detail.put("special_options_total", new BigDecimal("6.00"));
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("processingFeeDetail", detail);

        ProcessingFeeCalculator.Fee fee = ProcessingFeeCalculator.storedFee(info);

        assertThat(fee).isNotNull();
        assertThat(fee.amount()).isEqualByComparingTo("98.40");
        assertThat(fee.specialOptionsTotal()).isEqualByComparingTo("6.00");
        assertThat(fee.lineAmount()).isEqualByComparingTo("104.40");
        assertThat(fee.specialOptions()).hasSize(1);
        assertThat(fee.specialOptions().get(0).name()).isEqualTo("加铅块");
        assertThat(fee.specialOptions().get(0).priced()).isTrue();
    }

    @Test
    @DisplayName("无加工项（空组合）⇒ 不取价、金额 0，且提示与「未定价」可区分")
    void noProcessingItemsYieldsZeroWithDistinctHint() {
        givenCombinations(combination("定型+打孔+韩褶", "8.00"));

        ProcessingFeeCalculator.Fee fee = compute(processingInfo(new BigDecimal("12.30")));

        assertThat(fee.amount()).isEqualByComparingTo("0");
        assertThat(fee.feeSource()).isEqualTo("unpriced");
        assertThat(fee.compositionKey()).isEmpty();
        assertThat(fee.hint()).isNotBlank();
    }

    // ══════════════════════════ 停用组合不参与取价 ══════════════════════════

    @Test
    @DisplayName("停用（status=disabled）组合不参与取价 ⇒ 视同未定价（不取错价）")
    void disabledCombinationIsNotUsedForPricing() {
        // 取价侧的查询条件必须带 `status=active`（+ deleted=0）：库里有停用行时它**不该**被取到。
        // 故这里断言的是**查询条件本身**（停用行被 SQL 过滤掉）—— 注入法：把 status 条件删掉 ⇒ 红。
        when(combinationMapper.selectList(any())).thenAnswer(invocation -> {
            com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<?> wrapper =
                    invocation.getArgument(0);
            assertThat(wrapper.getSqlSegment() + wrapper.getParamNameValuePairs().values())
                    .as("取价查询必须按 status=active 过滤（否则会取到已下架的价）")
                    .contains("status").contains("active");
            return List.of();
        });

        ProcessingFeeCalculator.Fee fee = compute(processingInfo(
                new BigDecimal("12.30"), "韩褶", "打孔", "定型"));

        assertThat(fee.amount()).isEqualByComparingTo("0");
        assertThat(fee.feeSource()).isEqualTo("unpriced");
    }

    // ══════════════════════ #4855 拼色加价（用户 2026-09-21 裁定）══════════════════════
    //
    // 裁定逐字：「拼色计价规则就是拼色款另加 2.4 元/米 先按这个算吧」＋
    // 「**两处都按 2.4 元/米（订单侧撤掉元/套）**」⇒ 订单侧**不再**对 `拼1次` / `拼2次`
    // 按 `production_route_rules.customer_unit_price`（元/套，V82 种子 3.00 / 5.00）计费，
    // 改按 **2.4 元/米 × 该款面料米数** —— 与报价侧（`curtain_calc.build_quote`）**同源同价**
    // （跨语言同源判据见 `tests/unit_ci_workflows/test_mixed_color_surcharge_cross_side.py`）。
    //
    // 🔴 三条边界（不得越界）：
    //   ① 只动 `拼1次` / `拼2次` 两行 —— 同一份 V82 种子里别的选项（双眼皮接高 / 布绑带…）**一字未动**；
    //   ② 那两行**不是**「未定价」：库里 `customer_unit_price` 一字未动（不改数据面），
    //      取价侧把它们记为 `billing=per_meter`（`priced=true`）⇒ **不进**「未定价」提示；
    //   ③ **不追溯**：存量单读面（`storedFee`）不重算、`production_work_logs` 一字不动。

    /** 拼色订单行：款式 + **面料米数**（`fabric_meters` = 报价侧同源键）+ 特殊选项。 */
    private static Map<String, Object> mixedColorInfo(String style, String fabricMeters, String... options) {
        // 单面料行时 `processing_meters == fabric_meters`（真值源 §6.1）⇒ 两个键同值（与下单页落库同形）
        Map<String, Object> info = processingInfo(
                fabricMeters == null ? null : new BigDecimal(fabricMeters), "韩褶");
        if (fabricMeters != null) {
            info.put("fabric_meters", new BigDecimal(fabricMeters));
        }
        if (style != null) {
            info.put("style", style);
        }
        if (options.length > 0) {
            info.put("specialOptions", List.of(options));
        }
        return info;
    }

    @Test
    @DisplayName("#4855 判据 1·拼色款 ⇒ 另加 2.4 元/米 × 面料米数；**不再**按元/套收拼1次的 3.00")
    void mixedColorSurchargeIsPerMeterTimesFabricMeters() {
        givenCombinations(combination("韩褶", "10.00"));
        givenOptionRules(optionRule("拼1次", "3.00"));

        ProcessingFeeCalculator.Fee fee = compute(mixedColorInfo("拼色", "34.10", "拼1次"));

        // 组合那半：10.00 × 34.10 = 341.00；拼色加价：2.4 × 34.10 = 81.84
        assertThat(fee.amount()).isEqualByComparingTo("341.00");
        assertThat(fee.mixedColor().surcharge()).isEqualByComparingTo("81.84");
        assertThat(fee.mixedColor().meters()).isEqualByComparingTo("34.10");
        assertThat(fee.mixedColor().metersSource()).isEqualTo("fabric_meters");
        assertThat(fee.mixedColor().options()).containsExactly("拼1次");
        assertThat(fee.lineAmount()).isEqualByComparingTo("422.84");
        // 🔴 撤掉元/套：库里那笔 3.00 元/套 **不再**计入（旧口径 341.00 + 3.00 = 344.00 ⇒ 红）
        assertThat(fee.specialOptionsTotal()).isEqualByComparingTo("0");
        assertThat(fee.lineAmount()).isNotEqualByComparingTo("344.00");
        // 边界 ②：拼1次 **不是**「未定价」—— 照列、`priced=true`、`billing=per_meter`、金额 0
        assertThat(fee.specialOptions()).singleElement().satisfies(option -> {
            assertThat(option.name()).isEqualTo("拼1次");
            assertThat(option.priced()).isTrue();
            assertThat(option.billing()).isEqualTo(ProcessingFeeCalculator.BILLING_PER_METER);
            assertThat(option.amount()).isEqualByComparingTo("0");
            assertThat(option.unitPrice()).isEqualByComparingTo("3.00");   // 库里那笔价**原样可见**（未改数据）
        });
        assertThat(fee.hint()).isNull();   // 米数齐全 ⇒ 无「未定价 / 缺米数」提示
        // detail 契约（#4855：新增键只加不改）
        assertThat(fee.detail())
                .containsEntry("mixed_color_surcharge", new BigDecimal("81.84"))
                .containsEntry("mixed_color_surcharge_per_meter", new BigDecimal("2.4"))
                .containsEntry("mixed_color_meters", new BigDecimal("34.10"))
                .containsEntry("mixed_color_meters_source", "fabric_meters");
        assertThat(fee.detail().get("mixed_color_options")).isEqualTo(List.of("拼1次"));
    }

    @Test
    @DisplayName("#4855 判据 1b·真值源 §10 算例逐值：拼2次 62.7 米 ⇒ 150.48 元（旧口径 5.00 元/套）")
    void mixedColorSurchargeMatchesTruthSourceExample() {
        givenCombinations(combination("韩褶", "10.00"));
        givenOptionRules(optionRule("拼2次", "5.00"));

        ProcessingFeeCalculator.Fee fee = compute(mixedColorInfo("拼色", "62.70", "拼2次"));

        assertThat(fee.amount()).isEqualByComparingTo("627.00");
        assertThat(fee.mixedColor().surcharge()).isEqualByComparingTo("150.48");
        assertThat(fee.lineAmount()).isEqualByComparingTo("777.48");
        assertThat(fee.lineAmount()).isNotEqualByComparingTo("632.00");   // 旧口径（627.00 + 5.00）⇒ 红
    }

    @Test
    @DisplayName("#4855 判据 2·**单色款不受影响**（回归）：款式=单色 / 不传 style ⇒ 加价 0、行金额逐分不变")
    void singleColorHasNoMixedColorSurcharge() {
        givenCombinations(combination("韩褶", "10.00"));
        givenOptionRules(optionRule("拼1次", "3.00"));

        ProcessingFeeCalculator.Fee noStyle = compute(mixedColorInfo(null, "13.30"));
        assertThat(noStyle.mixedColor().surcharge()).isEqualByComparingTo("0");
        assertThat(noStyle.lineAmount()).isEqualByComparingTo("133.00");

        ProcessingFeeCalculator.Fee single = compute(mixedColorInfo("单色", "13.30"));
        assertThat(single.mixedColor().surcharge()).isEqualByComparingTo("0");
        assertThat(single.lineAmount()).isEqualByComparingTo("133.00");
        assertThat(single.mixedColor()).isEqualTo(ProcessingFeeCalculator.MixedColor.NONE);
    }

    @Test
    @DisplayName("#4855 判据 3·一樘窗只收一次（同 `craftLineId` 两行 ⇒ 只有第一行承接）")
    void mixedColorChargedOncePerWindow() {
        givenCombinations(combination("韩褶", "10.00"));

        Map<String, Object> cloth = mixedColorInfo("拼色", "34.10");
        cloth.put("craftLineId", "w1");
        Map<String, Object> sheer = mixedColorInfo("拼色", "20.00");
        sheer.put("craftLineId", "w1");
        sheer.put("processingMeters", new BigDecimal("20.00"));

        List<ProcessingFeeCalculator.Fee> fees = calculator.feesFor(List.of(cloth, sheer), TENANT);

        assertThat(fees.get(0).mixedColor().surcharge()).isEqualByComparingTo("81.84");
        assertThat(fees.get(1).mixedColor().surcharge()).isEqualByComparingTo("0");     // 不重复收
        assertThat(fees.get(1).lineAmount()).isEqualByComparingTo("200.00");            // 组合那半照算
    }

    @Test
    @DisplayName("#4855 判据 4·拼色但**缺面料米数** ⇒ 加价 0 + 可行动提示（不猜米数）")
    void missingFabricMetersYieldsZeroWithActionableHint() {
        givenCombinations(combination("韩褶", "10.00"));

        Map<String, Object> info = processingInfo(null, "韩褶");   // 无 processingMeters / fabric_meters
        info.put("style", "拼色");
        ProcessingFeeCalculator.Fee fee = compute(info);

        assertThat(fee.mixedColor().surcharge()).isEqualByComparingTo("0");
        assertThat(fee.mixedColor().meters()).isNull();
        assertThat(fee.hint()).contains("拼色加价").contains("缺面料米数");
    }

    @Test
    @DisplayName("#4855 判据 5·其余特殊选项仍按元/套（拼色加价是**第三半**，不与选项那半混算）")
    void otherOptionsStillChargedPerSet() {
        givenCombinations(combination("韩褶", "10.00"));
        givenOptionRules(optionRule("加铅块", "6.00"), optionRule("拼1次", "3.00"));

        ProcessingFeeCalculator.Fee fee = compute(mixedColorInfo("拼色", "34.10", "加铅块", "拼1次"));

        assertThat(fee.specialOptions()).extracting(ProcessingFeeCalculator.SpecialOption::name)
                .containsExactly("加铅块", "拼1次");
        assertThat(fee.specialOptionsTotal()).isEqualByComparingTo("6.00");
        assertThat(fee.mixedColor().surcharge()).isEqualByComparingTo("81.84");
        assertThat(fee.lineAmount()).isEqualByComparingTo("428.84");    // 341.00 + 6.00 + 81.84
    }

    @Test
    @DisplayName("#4855 边界登记·**拼3次**不在本裁定范围：仍按元/套计（纸表未登记其用料系数）")
    void unregisteredMixedTimesStillChargedPerSet() {
        givenCombinations(combination("韩褶", "10.00"));
        givenOptionRules(optionRule("拼3次", "7.00"));

        ProcessingFeeCalculator.Fee fee = compute(mixedColorInfo("拼色", "34.10", "拼3次"));

        assertThat(fee.specialOptionsTotal()).isEqualByComparingTo("7.00");
        assertThat(fee.specialOptions()).singleElement()
                .satisfies(option -> assertThat(option.billing())
                        .isEqualTo(ProcessingFeeCalculator.BILLING_PER_SET));
        assertThat(fee.lineAmount()).isEqualByComparingTo("429.84");    // 341.00 + 7.00 + 81.84
    }

    @Test
    @DisplayName("#4855 边界登记·拼次选项但款式≠拼色 ⇒ 两侧都不计（元/套已撤、加价只认拼色款）")
    void mixedTimesWithoutMixedStyleIsChargedNowhere() {
        givenCombinations(combination("韩褶", "10.00"));
        givenOptionRules(optionRule("拼1次", "3.00"));

        ProcessingFeeCalculator.Fee fee = compute(mixedColorInfo("单色", "34.10", "拼1次"));

        assertThat(fee.specialOptionsTotal()).isEqualByComparingTo("0");
        assertThat(fee.mixedColor().surcharge()).isEqualByComparingTo("0");
        assertThat(fee.lineAmount()).isEqualByComparingTo("341.00");
        // 不静默：选项仍在明细里可见（billing=per_meter），只是两侧都不计
        assertThat(fee.specialOptions()).singleElement()
                .satisfies(option -> assertThat(option.billing())
                        .isEqualTo(ProcessingFeeCalculator.BILLING_PER_METER));
    }

    @Test
    @DisplayName("#4855 判据 6·**不追溯**：存量单读面不重算（无键 ⇒ 0），有键 ⇒ 原样读回")
    void storedFeeNeverRecomputesMixedColorSurcharge() {
        Map<String, Object> legacyDetail = new LinkedHashMap<>();
        legacyDetail.put("amount", new BigDecimal("341.00"));
        legacyDetail.put("fee_source", "matched");
        legacyDetail.put("meters", new BigDecimal("34.10"));
        legacyDetail.put("special_options", List.of());
        legacyDetail.put("special_options_total", BigDecimal.ZERO);
        Map<String, Object> legacy = Map.of("processingFeeDetail", legacyDetail);

        // #4855 之前生成的单：detail 里**没有**拼色加价那半 ⇒ 0（当时确实没这一笔，不是「漏读」，
        // 也**不重算** —— R13「改价 ⇒ 新单按新价，已生成订单一字不变」）
        ProcessingFeeCalculator.Fee stored = ProcessingFeeCalculator.storedFee(legacy);
        assertThat(stored.mixedColor().surcharge()).isEqualByComparingTo("0");
        assertThat(stored.lineAmount()).isEqualByComparingTo("341.00");

        Map<String, Object> withSurcharge = new LinkedHashMap<>(legacyDetail);
        withSurcharge.put("mixed_color_surcharge", new BigDecimal("81.84"));
        withSurcharge.put("mixed_color_meters", new BigDecimal("34.10"));
        withSurcharge.put("mixed_color_meters_source", "fabric_meters");
        withSurcharge.put("mixed_color_options", List.of("拼1次"));

        ProcessingFeeCalculator.Fee storedNew = ProcessingFeeCalculator.storedFee(
                Map.of("processingFeeDetail", withSurcharge));
        assertThat(storedNew.mixedColor().surcharge()).isEqualByComparingTo("81.84");
        assertThat(storedNew.mixedColor().meters()).isEqualByComparingTo("34.10");
        assertThat(storedNew.mixedColor().options()).containsExactly("拼1次");
        assertThat(storedNew.lineAmount()).isEqualByComparingTo("422.84");
    }

    // ══════════════════════════ issue #4872：行级人工改价 ══════════════════════════
    //   判据（issue 冻结口径）：
    //     ① 组合**未命中** ∧ 组合键非空 ∧ override 是**正数** ⇒ 采用：fee_source='manual'、
    //        unit_price=override、金额 = override × 加工费米数；
    //     ② 组合**命中** ⇒ **必须忽略** override（既有组合价一字不动）；
    //     ③ 无 override 且未命中 ⇒ 与现状**逐字不变**（仍 unpriced、组合那半记 0、不回落 Σ 加工项）。
    //   🔴 红证：把 `overridePrice` 的采用分支去掉（或让它同时作用于命中分支）⇒ ①②两条必红。

    /** 往选配里加一条行级人工改价（元/米）。 */
    private static Map<String, Object> withOverride(Map<String, Object> info, Object override) {
        info.put("processingFeeOverride", override);
        return info;
    }

    @Test
    @DisplayName("#4872 判据 ①·组合**未命中** + override ⇒ fee_source=manual + 金额 = override × 米数")
    void manualOverrideOnUnmatchedCombinationUsesOverrideTimesMeters() {
        // 库里只有别的组合的价 ⇒ 本行（韩褶+打孔）未命中
        givenCombinations(combination("定型+打孔+韩褶", "8.00"));

        ProcessingFeeCalculator.Fee fee = compute(withOverride(
                processingInfo(new BigDecimal("12.30"), "韩褶", "打孔"), new BigDecimal("12.50")));

        // 12.50 × 12.30 = 153.75（**不是** Σ 加工项 9.50×2×2 = 38.00，也**不是**未定价 0）
        assertThat(fee.amount()).isEqualByComparingTo("153.75");
        assertThat(fee.amount()).isNotEqualByComparingTo("0");
        assertThat(fee.feeSource()).isEqualTo(ProcessingFeeCalculator.FEE_SOURCE_MANUAL);
        assertThat(fee.unitPrice()).isEqualByComparingTo("12.50");
        // 单价来源也要能回答「这个价是谁定的」（detail 键名不变，只填值）
        assertThat(fee.priceSource()).isEqualTo("manual");
        assertThat(fee.meters()).isEqualByComparingTo("12.30");
        assertThat(fee.metersSource()).isEqualTo("processingMeters");
        assertThat(fee.matchedRuleId()).isNull();
        assertThat(fee.lineAmount()).isEqualByComparingTo("153.75");
        // `items` 是**规范化**特征名有序列表（与组合键同源口径）
        assertThat(fee.compositionKey()).isEqualTo("打孔+韩褶");
        assertThat(fee.items()).containsExactly("打孔", "韩褶");
        assertThat(fee.detail())
                .containsEntry("composition", "打孔+韩褶")
                .containsEntry("items", List.of("打孔", "韩褶"))
                .containsEntry("matched_rule_id", null)
                .containsEntry("unit_price", new BigDecimal("12.50"))
                .containsEntry("price_source", "manual")
                .containsEntry("meters", new BigDecimal("12.30"))
                .containsEntry("meters_source", "processingMeters")
                .containsEntry("fee_source", "manual")
                .containsEntry("amount", new BigDecimal("153.75"));
    }

    @Test
    @DisplayName("#4872 判据 ①·override 是**字符串/浮点**形态（wire 形态）同样取到（不因类型退化成 unpriced）")
    void manualOverrideAcceptsWireShapes() {
        givenCombinations(combination("定型+打孔+韩褶", "8.00"));

        ProcessingFeeCalculator.Fee fee = compute(withOverride(
                processingInfo(new BigDecimal("10.00"), "韩褶"), "12.50"));

        assertThat(fee.feeSource()).isEqualTo(ProcessingFeeCalculator.FEE_SOURCE_MANUAL);
        assertThat(fee.amount()).isEqualByComparingTo("125.00");
    }

    @Test
    @DisplayName("#4872 判据 ②·组合**命中** ⇒ override 被**忽略**（既有组合价一字不动）—— 红证")
    void manualOverrideIsIgnoredWhenCombinationIsPriced() {
        givenCombinations(combination("打孔+韩褶", "8.00"));

        ProcessingFeeCalculator.Fee fee = compute(withOverride(
                processingInfo(new BigDecimal("12.30"), "韩褶", "打孔"), new BigDecimal("12.50")));

        // 仍按组合价 8.00 × 12.30 = 98.40；**不是** override × 米数 153.75、也不是 manual
        assertThat(fee.feeSource()).isEqualTo(ProcessingFeeCalculator.FEE_SOURCE_MATCHED);
        assertThat(fee.unitPrice()).isEqualByComparingTo("8.00");
        assertThat(fee.priceSource()).isEqualTo("实证");
        assertThat(fee.amount()).isEqualByComparingTo("98.40");
        assertThat(fee.amount()).isNotEqualByComparingTo("153.75");
        assertThat(fee.matchedRuleId()).isEqualTo("combo-打孔+韩褶");
        assertThat(fee.detail()).containsEntry("fee_source", "matched")
                .containsEntry("unit_price", new BigDecimal("8.00"))
                .containsEntry("amount", new BigDecimal("98.40"));
    }

    @Test
    @DisplayName("#4872 判据 ③·**无** override + 未命中 ⇒ 与现状逐字不变（仍 unpriced、组合那半 0、不回落 Σ 加工项）")
    void withoutOverrideUnmatchedCombinationKeepsUnpriced() {
        givenCombinations(combination("定型+打孔+韩褶", "8.00"));

        ProcessingFeeCalculator.Fee fee = compute(processingInfo(new BigDecimal("12.30"), "韩褶", "打孔"));

        assertThat(fee.feeSource()).isEqualTo(ProcessingFeeCalculator.FEE_SOURCE_UNPRICED);
        assertThat(fee.amount()).isEqualByComparingTo("0");
        assertThat(fee.unitPrice()).isNull();
        assertThat(fee.hint()).isNotBlank();
    }

    @Test
    @DisplayName("#4872·非正数 override（0 / 负数 / 非数值）**不算改价** ⇒ 仍走 unpriced（0 元改价 = 静默归零，不许）")
    void nonPositiveOverrideIsNotAManualPrice() {
        givenCombinations(combination("定型+打孔+韩褶", "8.00"));

        for (Object override : List.of(BigDecimal.ZERO, new BigDecimal("-5.00"), "abc", "")) {
            ProcessingFeeCalculator.Fee fee = compute(withOverride(
                    processingInfo(new BigDecimal("12.30"), "韩褶", "打孔"), override));
            assertThat(fee.feeSource())
                    .as("override=%s 不得被当成人改价（0/负数/非数值一律 = 没改价）", override)
                    .isEqualTo(ProcessingFeeCalculator.FEE_SOURCE_UNPRICED);
            assertThat(fee.amount()).isEqualByComparingTo("0");
            assertThat(fee.hint()).isNotBlank();
        }
    }

    @Test
    @DisplayName("#4872·**空组合**（没选加工项）+ override ⇒ 仍 unpriced（组合键非空是采用的前置条件）")
    void manualOverrideWithoutCompositionStaysUnpriced() {
        givenCombinations(combination("定型+打孔+韩褶", "8.00"));

        ProcessingFeeCalculator.Fee fee = compute(withOverride(
                processingInfo(new BigDecimal("12.30")), new BigDecimal("12.50")));

        assertThat(fee.compositionKey()).isEmpty();
        assertThat(fee.feeSource()).isEqualTo(ProcessingFeeCalculator.FEE_SOURCE_UNPRICED);
        assertThat(fee.amount()).isEqualByComparingTo("0");
    }

    @Test
    @DisplayName("#4872·未命中 + override 但**缺米数** ⇒ unpriced（改价也是单价×米数，不凭 quantity 猜）")
    void manualOverrideWithoutMetersStaysUnpriced() {
        givenCombinations(combination("定型+打孔+韩褶", "8.00"));

        ProcessingFeeCalculator.Fee fee = compute(withOverride(
                processingInfo(null, "韩褶", "打孔"), new BigDecimal("12.50")));

        assertThat(fee.feeSource()).isEqualTo(ProcessingFeeCalculator.FEE_SOURCE_UNPRICED);
        assertThat(fee.amount()).isEqualByComparingTo("0");
        // 不静默：改价意图与缺的因子都要看得见
        assertThat(fee.unitPrice()).isEqualByComparingTo("12.50");
        assertThat(fee.detail()).containsEntry("price_source", "manual");
        assertThat(fee.hint()).contains("人工改价").contains("缺加工费米数");
    }

    @Test
    @DisplayName("#4872·人工改价那半与**已定价特殊选项**正交：行金额 = override × 米数 + Σ 选项价")
    void manualOverrideStillChargesPricedSpecialOptions() {
        givenCombinations(combination("定型+打孔+韩褶", "8.00"));
        givenOptionRules(optionRule("加铅块", "6.00"));

        Map<String, Object> info = processingInfo(new BigDecimal("12.30"), "韩褶", "打孔");
        info.put("specialOptions", List.of("加铅块"));

        ProcessingFeeCalculator.Fee fee = compute(withOverride(info, new BigDecimal("12.50")));

        assertThat(fee.amount()).isEqualByComparingTo("153.75");
        assertThat(fee.specialOptionsTotal()).isEqualByComparingTo("6.00");
        assertThat(fee.lineAmount()).isEqualByComparingTo("159.75");
    }
}
