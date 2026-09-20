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
}
