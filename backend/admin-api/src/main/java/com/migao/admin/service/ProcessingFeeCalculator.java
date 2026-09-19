package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.entity.ProcessingFeeCombination;
import com.migao.admin.entity.ProductionRouteRule;
import com.migao.admin.mapper.ProcessingFeeCombinationMapper;
import com.migao.admin.mapper.ProductionRouteRuleMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 加工费**消费面**（V68 表的取价点；issue #4406 P1 + #4525 包 A；用户裁定 2026-09-19）。
 *
 * <h2>它替换了什么</h2>
 * 旧口径 = <b>Σ 加工项单价 × 数量</b>（{@code OrderService.sumProcessingFee} 的 {@code extractProcessingItems} 求和）
 * ⇒ #4386 让商家能配「组合 → 元/米」，但**配了组合费用订单金额一分不变**（消费面未接）。
 * 新口径（#4525 起两层账）：
 * <pre>
 * 行加工费 = 组合价(元/米) × 加工费米数  +  Σ 选中特殊选项( 单价(元/套) × 套数 )
 *            套数 = 1（用户裁定 R8：「1 套 = 1 个订单行」）
 * </pre>
 *
 * <h2>口径（用户裁定，不得自行放宽）</h2>
 * 「**未定价组合 ⇒ 加工费 = 0（unpriced），直接切，不回落 Σ 加工项**」
 * ⇒ 未命中**绝不**静默套任何默认价（#4308「静默回落」同族纪律：静默 = 算错钱且无人知道）。
 * 代价已知并接受：商家必须先配组合，否则加工费为 0。
 *
 * <h2>「未定价」有两层，都必须在 detail 里可判（设计 §4.2）</h2>
 * <ul>
 *   <li><b>组合未命中</b> ⇒ 整体 {@code fee_source='unpriced'}、金额 0、<b>不回落</b> Σ 加工项；
 *       此时 {@code special_options[]} 也按 0 计（组合那半都没有价，谈选项价无意义）；</li>
 *   <li><b>组合命中 ∧ 某选项未定价</b>（{@code customer_unit_price IS NULL}）⇒ {@code fee_source}
 *       仍 {@code 'matched'}（组合那半有效），**该选项**在 {@code special_options[]} 里
 *       {@code priced:false} + 计 0 + 可行动 hint ⇒ 绝不静默按 0 收。</li>
 * </ul>
 *
 * <h2>为什么单独一个类（而不是塞回 OrderService）</h2>
 * ① 取价是**纯函数**（{@code processing_info} + 价目表 → 一个数 + 可审计构成），
 *    与订单生命周期无关 ⇒ 可单测、可被下单页/Agent 侧共用（单一真值源 R10 的前提）；
 * ② {@code OrderService} 已 13 个依赖，再塞取价逻辑会让「谁在算加工费」不可 grep
 *    （同 #4386 对写面/读面的处置）。
 *
 * <h2>四条不许违反的纪律</h2>
 * <ul>
 *   <li><b>组合键归一化只有一份</b>：复用
 *       {@link ProcessingFeeCombinationCommandService#compositionKey}（写面冻结的口径：
 *       trim → 丢空 → 去重 → 按 Unicode 码点升序 → {@code +} 连接）——
 *       自己拼一份 ⇒ 商家录入与下单匹配可以不一致，且**不会变红**；</li>
 *   <li><b>加工费米数 = 该樘窗主布行米数</b>（裁定 R-b）：{@code processingMeters}（算料侧主布行米数），
 *       兼容键 {@code fabric_meters}；纱**不另按米收**（已含在组合档位单价里）。缺米数 = 算不出钱 ⇒
 *       **不凭 {@code quantity} 猜**，同样记 {@code unpriced}；</li>
 *   <li><b>两套账不互读</b>（真值源 §4 / R9）：本类**只**读
 *       {@code processing_fee_combinations}（元/米）与 {@code production_route_rules.customer_unit_price}
 *       （元/套）—— 两者都是**对顾客收的售价**；**绝不**读 {@code production_operations.unit_price}
 *       或 {@code production_route_rules.factor}（给工人付的计件成本）—— 互读 = 把内部计件单价
 *       泄漏成对客售价（#4525 判据 10）；</li>
 *   <li><b>特殊选项匹配 = 精确相等</b>：{@code specialOptions[]} 里的选项名就是
 *       {@code production_route_rules.trigger_value}（ERP 逐字写法），**不得**用 {@code contains}
 *       模糊匹配 —— 错一个字 ⇒ 静默少收/多收钱（#4389 同族纪律）。</li>
 * </ul>
 *
 * <h2>可审计（{@code processingFeeDetail}）</h2>
 * 记下**组合 / 命中哪条规则 / 单价 / 单价来源 / 加工费米数 / 米数来源 / {@code fee_source} 三态**，
 * 与工序实例的 {@code qty_source} 同族纪律：**不许静默**。金额本身仍是 number
 * （{@code processingFee}，{@code OrderItemList} / {@code OrderTable} 直接读）⇒ 新增信息一律进 detail。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ProcessingFeeCalculator {

    /** {@code fee_source} 三态（设计 §5.7.5 ②；与工序侧 {@code route_source} 四态同族）。 */
    public static final String FEE_SOURCE_MATCHED = "matched";
    public static final String FEE_SOURCE_UNPRICED = "unpriced";
    /** 人工改价（商家在单笔订单上改价，必须留痕）—— 通道**未落码**（本包只接线自动取价）。 */
    public static final String FEE_SOURCE_MANUAL = "manual";

    /** 加工费米数的键族（唯一生产者 = 算料侧 {@code curtain_calc}；键名与加工单白名单逐字一致）。 */
    private static final List<String> METER_KEYS = List.of("processingMeters", "fabric_meters");

    /** 可行动提示里的定价入口（商家看到提示要能直接找到地方补价）。 */
    private static final String PRICING_ENTRY = "/production/processing-fees";

    /**
     * 特殊选项**对客单价**所在的规则类型（{@code production_route_rules.trigger_kind}）。
     * 只有这一类的行才有 {@code customer_unit_price}（设计 §4.1：非 option 行一律 NULL）。
     */
    private static final String TRIGGER_KIND_OPTION = "option";

    /** JSON 字符串形态的 {@code processing_info} 解析（自定义 {@code @Select} 路径不经 TypeHandler）。 */
    private static final com.fasterxml.jackson.databind.ObjectMapper JSON =
            new com.fasterxml.jackson.databind.ObjectMapper();

    private final ProcessingFeeCombinationMapper combinationMapper;

    /** 特殊选项对客单价（{@code production_route_rules.customer_unit_price}，V77）。 */
    private final ProductionRouteRuleMapper routeRuleMapper;

    // ══════════════════════════════ 对外结果 ══════════════════════════════

    /**
     * 一个**选中特殊选项**的取价结果（设计 §4.3；R5 + R8「1 套 = 1 个订单行」）。
     *
     * @param name      选项名（**逐字 = {@code processing_info.specialOptions[]} 的元素**
     *                  = {@code production_route_rules.trigger_value}；它是 join key，不得改写）
     * @param unitPrice 该选项的**对客元/套**单价；未定价 = {@code null}（**≠ 0**）
     * @param sets      套数 = **恒 1**（用户裁定 R8：「1 套 = 1 个订单行」）
     * @param amount    {@code unitPrice × sets}；未定价 = 0
     * @param priced    是否已定价（{@code false} = 库里 {@code customer_unit_price IS NULL}）
     *                  ⇒ 取价侧**显式可见**，绝不静默按 0 收
     */
    public record SpecialOption(String name, BigDecimal unitPrice, int sets,
                               BigDecimal amount, boolean priced) {
    }

    /**
     * 一行的加工费结果。
     *
     * @param amount              **组合那半**（元）= 组合单价 × 加工费米数；未定价 / 缺米数 = 0
     * @param feeSource           三态：matched / unpriced / manual（**枚举不变**）
     * @param compositionKey      归一化组合键（未命中时也要记下"当时选的是什么"）
     * @param unitPrice           命中的组合单价（元/米）；未命中 = null
     * @param meters              加工费米数（= 该樘窗主布行米数）；缺 = null
     * @param specialOptions      选中特殊选项的逐项取价（**按选项名 Unicode 码点升序**，确定性）
     * @param specialOptionsTotal Σ 选项价（元）；没选 = 0
     * @param detail              可审计构成（落 {@code processing_info.processingFeeDetail}，原样透传）
     * @param hint                未定价 / 缺米数时的**可行动**提示；命中且齐全 = null
     */
    public record Fee(BigDecimal amount, String feeSource, String compositionKey,
                      List<String> items, String matchedRuleId, BigDecimal unitPrice,
                      String priceSource, BigDecimal meters, String metersSource,
                      List<SpecialOption> specialOptions, BigDecimal specialOptionsTotal,
                      Map<String, Object> detail, String hint) {

        /**
         * **行加工费** = 组合那半 + Σ 选项价（设计 §4.3：「唯一进订单金额的数」）。
         *
         * <p>{@code amount} 只记组合那半（与 #4406 的既有语义/键名**一字不改**），
         * 行金额由本方法合成 ⇒ 订单金额 / 试算合计都走这里，**不另拼一份口径**。</p>
         */
        public BigDecimal lineAmount() {
            return nz(amount).add(nz(specialOptionsTotal));
        }

        /** 选项价合计（非空时才有值；空 = 0，不是 null —— 调用方不必判空）。 */
        private static BigDecimal nz(BigDecimal value) {
            return value == null ? BigDecimal.ZERO : value;
        }

        static Fee unpriced(String compositionKey, List<String> items, BigDecimal unitPrice,
                            String priceSource, BigDecimal meters, String metersSource, String hint) {
            // 组合那半都没有价 ⇒ 选项价不参与（仍记进 detail 供审计：选了哪些选项是**事实**）
            return new Fee(BigDecimal.ZERO, FEE_SOURCE_UNPRICED, compositionKey, items, null,
                    unitPrice, priceSource, meters, metersSource, List.of(), BigDecimal.ZERO,
                    detail(compositionKey, items, null, unitPrice, priceSource, meters, metersSource,
                            FEE_SOURCE_UNPRICED, BigDecimal.ZERO, List.of(), BigDecimal.ZERO, hint),
                    hint);
        }

        static Fee matched(String compositionKey, List<String> items, String matchedRuleId,
                           BigDecimal unitPrice, String priceSource, BigDecimal meters,
                           String metersSource, List<SpecialOption> specialOptions, String hint) {
            // 金额按**人类可读刻度**落 detail（`8.00 × 12.30` 的裸乘积是 `98.4000`）：
            // detail 是给人与对账看的，尾随零不是信息；订单金额本身仍是精确值。
            // ⚠️ 不得用裸 `stripTrailingZeros()`：它会把 80.00 变成 `8E+1`（科学计数法进 JSON）
            // ⇒ 前端按 number 解析得到 8E1 字符串，是**新的**静默错账。
            BigDecimal amount = money(unitPrice.multiply(meters));
            BigDecimal optionsTotal = money(optionsTotal(specialOptions));
            return new Fee(amount, FEE_SOURCE_MATCHED, compositionKey, items, matchedRuleId,
                    unitPrice, priceSource, meters, metersSource, specialOptions, optionsTotal,
                    detail(compositionKey, items, matchedRuleId, unitPrice, priceSource, meters,
                            metersSource, FEE_SOURCE_MATCHED, amount, specialOptions, optionsTotal, hint),
                    hint);
        }

        /** Σ 选项价（未定价项按 0 计 —— 它们已在 {@code priced:false} 上显式可见）。 */
        private static BigDecimal optionsTotal(List<SpecialOption> specialOptions) {
            BigDecimal total = BigDecimal.ZERO;
            for (SpecialOption option : specialOptions == null ? List.<SpecialOption>of() : specialOptions) {
                total = total.add(nz(option.amount()));
            }
            return total;
        }

        /** 可审计构成的**唯一**构造点（键名冻结：新增键只在这里加，读面不另拼一份）。 */
        private static Map<String, Object> detail(String compositionKey, List<String> items,
                                                  String matchedRuleId, BigDecimal unitPrice,
                                                  String priceSource, BigDecimal meters,
                                                  String metersSource, String feeSource,
                                                  BigDecimal amount, List<SpecialOption> specialOptions,
                                                  BigDecimal specialOptionsTotal, String hint) {
            Map<String, Object> detail = new LinkedHashMap<>();
            detail.put("composition", compositionKey);
            detail.put("items", items);
            detail.put("matched_rule_id", matchedRuleId);
            detail.put("unit_price", unitPrice);
            detail.put("price_source", priceSource);
            detail.put("meters", meters);
            detail.put("meters_source", metersSource);
            detail.put("fee_source", feeSource);
            detail.put("amount", amount);
            // ── #4525 新增（**只加不改**：既有 10 个键的语义与键名一字未动）──
            detail.put("special_options", optionDetails(specialOptions));
            detail.put("special_options_total", specialOptionsTotal);
            detail.put("hint", hint);
            return detail;
        }

        /** 选项明细的 JSON 形态（**有序** LinkedHashMap：键序稳定，便于人读与前端渲染）。 */
        private static List<Map<String, Object>> optionDetails(List<SpecialOption> specialOptions) {
            List<Map<String, Object>> rows = new ArrayList<>();
            for (SpecialOption option : specialOptions == null ? List.<SpecialOption>of() : specialOptions) {
                Map<String, Object> row = new LinkedHashMap<>();
                row.put("name", option.name());
                row.put("unit_price", option.unitPrice());
                row.put("sets", option.sets());
                row.put("amount", option.amount());
                row.put("priced", option.priced());
                rows.add(row);
            }
            return rows;
        }

        /**
         * 金额刻度：去尾随零、**保留至少 2 位小数**、禁止科学计数法（{@code 80.00} 不得变 {@code 8E+1}）。
         * 值不变（{@code compareTo} 相等），只是形态可读（人看 detail / 前端按 number 解析）。
         */
        private static BigDecimal money(BigDecimal value) {
            if (value == null) {
                return null;
            }
            BigDecimal stripped = value.stripTrailingZeros();
            return stripped.scale() < 2 ? stripped.setScale(2) : stripped;
        }
    }

    // ══════════════════════════════ 取价 ══════════════════════════════

    /**
     * 批量取价（**一次**加载租户价目表，逐行匹配）—— 订单创建是三条路径（表单 / Agent / 程序化）
     * 的唯一共享入口，一次下单 N 行不应查 N 次库。
     *
     * @param processingInfos 逐行的 {@code processing_info}（可含 JSON 字符串形态，见
     *                        {@link ProcessingFeeQueryService#featureNames}）；顺序与返回**一一对应**
     */
    public List<Fee> feesFor(List<?> processingInfos, Long tenantId) {
        Map<String, ProcessingFeeCombination> priced = pricedCombinations(tenantId);
        Map<String, BigDecimal> optionPrices = optionPrices(tenantId);
        List<Fee> fees = new ArrayList<>();
        for (Object info : processingInfos == null ? List.<Object>of() : processingInfos) {
            fees.add(feeFor(info, priced, optionPrices));
        }
        return fees;
    }

    /**
     * 单行取价（**纯函数**，不碰库）：选配 → 组合键 → 匹配 → 组合单价 × 米数 + Σ 选项价 × 1。
     *
     * <p>命中但米数缺失也返回 {@code unpriced}（0 元）—— 米数是金额的另一个因子，
     * 缺它就只能算 0；**不凭 {@code quantity} 猜**（猜出来的钱无人可复核）。</p>
     *
     * <p>特殊选项**只在组合命中且米数齐全**时才计费（组合未命中 ⇒ 整体 unpriced 且金额 0，
     * 不回落 Σ 加工项、也不单独收选项价）—— 设计 §4.2。</p>
     */
    public static Fee feeFor(Object processingInfo, Map<String, ProcessingFeeCombination> priced) {
        return feeFor(processingInfo, priced, Map.of());
    }

    /**
     * 单行取价（带**特殊选项价目**）。
     *
     * @param optionPrices {@code 选项名 → 对客元/套单价}（{@code customer_unit_price IS NULL} 的
     *                     选项**不在** map 里 = 未定价 ⇒ {@code priced:false} + 计 0）
     */
    public static Fee feeFor(Object processingInfo, Map<String, ProcessingFeeCombination> priced,
                             Map<String, BigDecimal> optionPrices) {
        List<String> items = ProcessingFeeQueryService.featureNames(processingInfo);
        String compositionKey = ProcessingFeeCombinationCommandService.compositionKey(items);
        BigDecimal meters = meters(processingInfo);
        String metersSource = meters == null ? null : metersSource(processingInfo);
        if (compositionKey.isEmpty()) {
            return Fee.unpriced(compositionKey, List.of(), null, null, meters, metersSource,
                    "本行没有选配任何加工项 ⇒ 没有可收的加工费（加工费按选配组合收）。"
                            + "若这单本该有加工费，请确认下单时是否漏选了加工项");
        }
        ProcessingFeeCombination row = priced == null ? null : priced.get(compositionKey);
        if (row == null || row.getUnitPrice() == null) {
            return Fee.unpriced(compositionKey, ProcessingFeeQueryService.itemsOf(compositionKey),
                    null, null, meters, metersSource,
                    String.format("选配组合「%s」在「加工费组合」里没有价 ⇒ 本行加工费按 0 计（未定价），"
                                    + "**不套任何默认价**。请去「加工费管理」(%s) 为该组合定价，"
                                    + "或确认这些加工项不该组合收费",
                            compositionKey, PRICING_ENTRY));
        }
        List<String> normalizedItems = ProcessingFeeQueryService.itemsOf(compositionKey);
        if (meters == null) {
            return Fee.unpriced(compositionKey, normalizedItems, row.getUnitPrice(), row.getSource(),
                    null, null,
                    String.format("选配组合「%s」已定价 ¥%s/米，但本行**缺加工费米数** ⇒ 加工费按 0 计。"
                                    + "加工费米数 = 该樘窗主布行米数（算料侧给出，键 `processingMeters`）"
                                    + "⇒ 请补算料米数后重下单",
                            compositionKey, row.getUnitPrice().toPlainString()));
        }
        List<SpecialOption> specialOptions = specialOptions(processingInfo, optionPrices);
        return Fee.matched(compositionKey, normalizedItems, row.getId(), row.getUnitPrice(),
                row.getSource(), meters, metersSource, specialOptions,
                unpricedOptionsHint(specialOptions));
    }

    /**
     * 选中特殊选项的逐项取价（**按选项名 Unicode 码点升序**，设计 §4.3 —— 与
     * {@code compositionKey} 同族纪律：顺序不确定 ⇒ 同一张单两次生成得到不同明细）。
     *
     * <p>选项名取自 {@code processing_info.specialOptions}（**顶层字符串数组**，
     * 与 {@code processingItems} 的「对象数组带 name」**不同形**）。</p>
     */
    static List<SpecialOption> specialOptions(Object processingInfo,
                                              Map<String, BigDecimal> optionPrices) {
        List<String> names = specialOptionNames(processingInfo);
        List<SpecialOption> options = new ArrayList<>();
        for (String name : names) {
            // 精确相等匹配（**不得**用 contains：错一个字 ⇒ 静默少收/多收钱）
            BigDecimal unitPrice = optionPrices == null ? null : optionPrices.get(name);
            boolean priced = unitPrice != null;
            options.add(new SpecialOption(name, unitPrice, 1,
                    priced ? unitPrice : BigDecimal.ZERO, priced));
        }
        options.sort(Comparator.comparingInt(option -> option.name().codePointAt(0)));
        return options;
    }

    /** 未定价选项的**可行动**提示（设计 §4.2：未定价必须在 detail 里可判，不许静默按 0 收）。 */
    private static String unpricedOptionsHint(List<SpecialOption> specialOptions) {
        List<String> unpriced = new ArrayList<>();
        for (SpecialOption option : specialOptions) {
            if (!option.priced()) {
                unpriced.add(option.name());
            }
        }
        if (unpriced.isEmpty()) {
            return null;
        }
        return String.format("特殊选项 %s **未定价**（对客元/套为空）⇒ 这几项按 0 计、"
                        + "**不套任何默认价**。请去「加工费管理」(%s) 为它们定价",
                unpriced, PRICING_ENTRY);
    }

    /** 选中的特殊选项名（{@code processing_info.specialOptions: string[]}；缺失 / 非数组 = 没选）。 */
    static List<String> specialOptionNames(Object processingInfo) {
        Map<String, Object> info = asMap(processingInfo);
        if (info == null) {
            return List.of();
        }
        Object raw = info.get("specialOptions");
        if (!(raw instanceof List<?> list)) {
            return List.of();
        }
        List<String> names = new ArrayList<>();
        for (Object element : list) {
            if (element != null && !String.valueOf(element).isBlank()) {
                names.add(String.valueOf(element));
            }
        }
        return names;
    }

    /**
     * 读面：取**落库时算好的**加工费（{@code processing_info.processingFeeDetail}），**不重算**。
     *
     * <p>为什么读面必须读存量而不是重算：R13「改组合价 ⇒ 新单按新价，**已生成订单一字不变**」
     * —— 重算会让历史订单金额随价目表漂移（同真值源 §4「历史报工按当时价」纪律）。
     * 存量单（接线前生成，无 {@code processingFeeDetail}）**不猜**：返回 0 + {@code unpriced}，
     * 让「这一行没有权威加工费」显式可见，而不是拿一个重算值冒充历史。</p>
     */
    @SuppressWarnings("unchecked")
    public static Fee storedFee(Object processingInfo) {
        Map<String, Object> info = asMap(processingInfo);
        if (info == null) {
            return null;
        }
        Object raw = info.get("processingFeeDetail");
        if (!(raw instanceof Map<?, ?> detail)) {
            return null;
        }
        Map<String, Object> detailMap = new LinkedHashMap<>((Map<String, Object>) detail);
        BigDecimal amount = decimal(detailMap.get("amount"));
        String feeSource = detailMap.get("fee_source") == null
                ? FEE_SOURCE_UNPRICED : String.valueOf(detailMap.get("fee_source"));
        return new Fee(amount == null ? BigDecimal.ZERO : amount, feeSource,
                text(detailMap.get("composition")), stringList(detailMap.get("items")),
                text(detailMap.get("matched_rule_id")), decimal(detailMap.get("unit_price")),
                text(detailMap.get("price_source")), decimal(detailMap.get("meters")),
                text(detailMap.get("meters_source")),
                storedOptions(detailMap.get("special_options")),
                decimal(detailMap.get("special_options_total")),
                detailMap, text(detailMap.get("hint")));
    }

    /**
     * 落库的选项明细 → {@link SpecialOption}（**读面与写面同源**：键名只有一处定义）。
     *
     * <p>存量单（#4525 之前生成）没有 {@code special_options} 键 ⇒ 返回空列表
     * （= 当时确实没按套收过费，不是「漏读」）。</p>
     */
    private static List<SpecialOption> storedOptions(Object raw) {
        if (!(raw instanceof List<?> list)) {
            return List.of();
        }
        List<SpecialOption> options = new ArrayList<>();
        for (Object element : list) {
            if (!(element instanceof Map<?, ?> row)) {
                continue;
            }
            options.add(new SpecialOption(
                    text(row.get("name")),
                    decimal(row.get("unit_price")),
                    row.get("sets") instanceof Number number ? number.intValue() : 1,
                    decimal(row.get("amount")),
                    Boolean.TRUE.equals(row.get("priced"))));
        }
        return options;
    }

    /**
     * 把结果写回 {@code processing_info}（**落库的唯一动作**）：金额 + 可审计构成进
     * {@code processingFeeDetail}，键名与 {@link #storedFee} 读面**同源**（只有这里写、那里读）。
     *
     * <p>就地改传入的 Map（{@code createOrder} 随后把同一个引用落库）—— 调用方负责
     * 「Map 形态才写」（JSON 字符串形态由调用方先归一化，见 {@code OrderService}）。</p>
     */
    @SuppressWarnings("unchecked")
    public static void attach(Object processingInfo, Fee fee) {
        if (processingInfo instanceof Map && fee != null) {
            ((Map<String, Object>) processingInfo).put("processingFeeDetail", fee.detail());
        }
    }

    // ══════════════════════════════ 读取工具 ══════════════════════════════

    /**
     * 租户**活跃**组合价目表（{@code tenant_id + deleted=0 + status=active}，按 composition_key 索引）。
     *
     * <p>停用行**不参与取价**（{@code status=disabled} 是「下架」语义）—— 若取到停用价，
     * 商家下架一个组合后订单金额照旧，且没有任何信号说明「取的是已下架价」。</p>
     */
    private Map<String, ProcessingFeeCombination> pricedCombinations(Long tenantId) {
        List<ProcessingFeeCombination> rows = combinationMapper.selectList(
                new LambdaQueryWrapper<ProcessingFeeCombination>()
                        .eq(ProcessingFeeCombination::getTenantId, tenantId)
                        .eq(ProcessingFeeCombination::getDeleted, 0)
                        .eq(ProcessingFeeCombination::getStatus, "active"));
        Map<String, ProcessingFeeCombination> byKey = new LinkedHashMap<>();
        for (ProcessingFeeCombination row : rows == null ? List.<ProcessingFeeCombination>of() : rows) {
            if (row.getCompositionKey() != null) {
                byKey.put(row.getCompositionKey(), row);
            }
        }
        return byKey;
    }

    /**
     * 租户**特殊选项对客单价**表（{@code trigger_kind='option' + deleted=0 + status=active}，
     * 按 {@code trigger_value} 索引）—— issue #4525，V77 的 {@code customer_unit_price}。
     *
     * <p><b>只收已定价的行</b>：{@code customer_unit_price IS NULL} 的选项**不进** map
     * ⇒ 取价侧命中不到 ⇒ {@code priced:false} + 计 0 + 可行动 hint（**不静默按 0 收**）。
     * 把 NULL 塞成 0 进 map 会让「未定价」与「定价 0 元」在数据上不可区分 —— 那正是本单要治的形态。</p>
     *
     * <p>⚠️ 只读 {@code customer_unit_price}（对客售价账），**绝不**读 {@code factor}
     * （给工人付的计件系数）—— 两套账不互读（设计 §4.1 / 判据 10）。</p>
     */
    private Map<String, BigDecimal> optionPrices(Long tenantId) {
        List<ProductionRouteRule> rows = routeRuleMapper.selectList(
                new LambdaQueryWrapper<ProductionRouteRule>()
                        .eq(ProductionRouteRule::getTenantId, tenantId)
                        .eq(ProductionRouteRule::getDeleted, 0)
                        .eq(ProductionRouteRule::getStatus, "active")
                        .eq(ProductionRouteRule::getTriggerKind, TRIGGER_KIND_OPTION));
        Map<String, BigDecimal> byName = new LinkedHashMap<>();
        for (ProductionRouteRule row : rows == null ? List.<ProductionRouteRule>of() : rows) {
            if (row.getTriggerValue() != null && row.getCustomerUnitPrice() != null) {
                byName.put(row.getTriggerValue(), row.getCustomerUnitPrice());
            }
        }
        return byName;
    }

    /** 加工费米数（= 主布行米数）：{@code processingMeters} 优先，兼容 {@code fabric_meters}。 */
    private static BigDecimal meters(Object processingInfo) {
        Map<String, Object> info = asMap(processingInfo);
        if (info == null) {
            return null;
        }
        for (String key : METER_KEYS) {
            BigDecimal value = decimal(info.get(key));
            if (value != null) {
                return value;
            }
        }
        return null;
    }

    /** 米数取自哪个键（可审计：与工序实例 `qty_source` 同族，不许静默）。 */
    private static String metersSource(Object processingInfo) {
        Map<String, Object> info = asMap(processingInfo);
        if (info == null) {
            return null;
        }
        for (String key : METER_KEYS) {
            if (decimal(info.get(key)) != null) {
                return key;
            }
        }
        return null;
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> asMap(Object processingInfo) {
        Object normalized = processingInfo;
        if (normalized instanceof String s && !s.isBlank()) {
            try {
                normalized = JSON.readValue(s, Map.class);
            } catch (Exception e) {
                return null;
            }
        }
        return normalized instanceof Map ? (Map<String, Object>) normalized : null;
    }

    private static BigDecimal decimal(Object value) {
        if (value == null) {
            return null;
        }
        if (value instanceof BigDecimal decimal) {
            return decimal;
        }
        try {
            return new BigDecimal(String.valueOf(value).trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private static String text(Object value) {
        return value == null ? null : String.valueOf(value);
    }

    private static List<String> stringList(Object value) {
        if (!(value instanceof List<?> list)) {
            return List.of();
        }
        List<String> result = new ArrayList<>(list.size());
        for (Object element : list) {
            result.add(element == null ? null : String.valueOf(element));
        }
        return result;
    }
}
