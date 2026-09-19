package com.migao.admin.service;

// case_ids: PG-041

import com.migao.admin.entity.ProcessingFeeCombination;
import com.migao.admin.entity.ProcessingItem;
import com.migao.admin.mapper.ProcessingFeeCombinationMapper;
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

    private ProcessingFeeCalculator calculator;

    @BeforeEach
    void setUp() {
        // 取价查询用 `LambdaQueryWrapper<ProcessingFeeCombination>` ⇒ 断言查询条件需要 lambda 缓存
        // （否则 `getSqlSegment()` 抛「can not find lambda cache」，断言退化成错误而不是结论）
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(assistant, ProcessingFeeCombination.class);
        calculator = new ProcessingFeeCalculator(combinationMapper);
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

    private void givenCombinations(ProcessingFeeCombination... rows) {
        when(combinationMapper.selectList(any())).thenReturn(List.of(rows));
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
