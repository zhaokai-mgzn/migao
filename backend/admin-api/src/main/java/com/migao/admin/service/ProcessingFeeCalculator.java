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
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 加工费**消费面**（V68 表的取价点；issue #4406 P1 + #4525 包 A；用户裁定 2026-09-19）。
 *
 * <h2>它替换了什么</h2>
 * 旧口径 = <b>Σ 加工项单价 × 数量</b>（{@code OrderService.sumProcessingFee} 的 {@code extractProcessingItems} 求和）
 * ⇒ #4386 让商家能配「组合 → 元/米」，但**配了组合费用订单金额一分不变**（消费面未接）。
 * 新口径（#4525 起两层账）：
 * <pre>
 * 行加工费 = 组合价(元/米) × 加工费米数  +  Σ 选中特殊选项( 单价(元/套) × 套数 )
 *            套数 = 该选项在**本行所属樘窗**里的计费套数（用户裁定 R8；2026-09-20 / #4725 改判：
 *                   「1 套 = 1 樘窗 = 一个 craftLineId 组」，不再是「1 套 = 1 个订单行」）
 *                   ⇒ **同一樘窗内同名选项只收一次**：承接那一行 = 1，同樘窗其它行 = 0（仍列出、金额 0）
 * </pre>
 *
 * <h2>口径（用户裁定，不得自行放宽）</h2>
 * 「**未定价组合 ⇒ 组合那半 = 0（unpriced），直接切，不回落 Σ 加工项**」
 * ⇒ 未命中**绝不**静默套任何默认价（#4308「静默回落」同族纪律：静默 = 算错钱且无人知道）。
 * 代价已知并接受：商家必须先配组合，否则**组合那半**为 0。
 *
 * <h2>「未定价」有两层，都必须在 detail 里可判（设计 §4.2）</h2>
 * <ul>
 *   <li><b>组合未命中 / 无加工项 / 缺米数</b> ⇒ {@code fee_source='unpriced'}、{@code amount}（**组合那半**）
 *       为 0、<b>不回落</b> Σ 加工项；但 {@code special_options[]} **照常取价并计入行金额**
 *       （用户裁定 2026-09-19 / issue #4594：选项是**按套的独立一笔账**，与组合是否定价、
 *       米数是否齐全**无关** —— 曾经「组合没配价 ⇒ 选项被吞」会让商家勾了扣环/抱枕却一分钱不体现）；</li>
 *   <li><b>组合命中 ∧ 某选项未定价</b>（{@code customer_unit_price IS NULL}）⇒ {@code fee_source}
 *       仍 {@code 'matched'}（组合那半有效），**该选项**在 {@code special_options[]} 里
 *       {@code priced:false} + 计 0 + 可行动 hint ⇒ 绝不静默按 0 收。</li>
 * </ul>
 * ⇒ {@code fee_source} 只表达**组合那半**的三态（matched / unpriced / manual），
 * **不再蕴含「行金额 = 0」**（枚举取值不变）；行金额一律走 {@link Fee#lineAmount()}。
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
    /**
     * 人工改价（商家在单笔订单上改价，必须留痕）—— issue #4872 起**已落码**
     * （此前全仓只有声明，取价侧**从不产出** {@code manual}）。
     *
     * <p>采用条件（三条**同时**成立，缺一不采用）：① 该行组合**未命中**活跃价目；
     * ② 组合键非空；③ {@code processing_info.processingFeeOverride} 是**正数**。
     * **命中组合时一律忽略 override**（既有组合价一字不动 —— 改价通道不得成为绕过组合价的旁路）。</p>
     */
    public static final String FEE_SOURCE_MANUAL = "manual";

    /**
     * 行级**人工改价**单价键（元/米）：{@code items[].processingInfo.processingFeeOverride}
     * （与 {@code processingMeters} / {@code specialOptions} 同层）。
     */
    static final String OVERRIDE_KEY = "processingFeeOverride";

    /** 加工费米数的键族（唯一生产者 = 算料侧 {@code curtain_calc}；键名与加工单白名单逐字一致）。 */
    private static final List<String> METER_KEYS = List.of("processingMeters", "fabric_meters");

    /** 可行动提示里的定价入口（商家看到提示要能直接找到地方补价）。 */
    private static final String PRICING_ENTRY = "/production/processing-fees";

    /**
     * 特殊选项**对客单价**所在的规则类型（{@code production_route_rules.trigger_kind}）。
     * 只有这一类的行才有 {@code customer_unit_price}（设计 §4.1：非 option 行一律 NULL）。
     */
    private static final String TRIGGER_KIND_OPTION = "option";

    /**
     * 拼色**报价加价**单价（元/米）—— 用户 2026-09-21 裁定逐字：
     * 「拼色计价规则就是拼色款另加 2.4 元/米 先按这个算吧」＋「**两处都按 2.4 元/米（订单侧撤掉元/套）**」。
     *
     * <p>⚠️ 这是**跨语言副本**：真值源 = ai-agent 算料引擎
     * {@code backend/ai-agent-service/app/tools/curtain_calc.py} 的 {@code MIXED_COLOR_SURCHARGE_PER_METER}
     * （真值源文档 §0 登记）。两侧**必须逐值相等**，由
     * {@code tests/unit_ci_workflows/test_mixed_color_surcharge_cross_side.py} 逐值读源比对（漂移即红）——
     * 「报价侧与订单侧同源同价」是本裁定的硬要求（只改一侧 ⇒ 顾客看到的价 ≠ 下单收的价）。</p>
     */
    static final BigDecimal MIXED_COLOR_SURCHARGE_PER_METER = new BigDecimal("2.4");

    /** 款式取值（**逐字** = 算料引擎 {@code curtain_calc.STYLE_MIXED} / 前端 {@code STYLE_OPTIONS}）。 */
    static final String STYLE_MIXED = "拼色";

    /**
     * **改按元/米计**的拼次选项（用户 2026-09-21 裁定：订单侧**撤掉**这几项的**元/套**计费）。
     *
     * <p>为什么写「选项名」而不是从库里读：选项名是**冻结的 join key**（与
     * {@code production_route_rules.trigger_value} / 前端 {@code SPECIAL_OPTIONS} 逐字一致）；
     * 而 V82 种子那笔元/套价（{@code customer_unit_price}）**已发布、不可改**（issue #4235）⇒
     * 在**取价口径层**停止使用它（库里那一列照旧保留 —— 改数据要新迁移，本包不动数据面）。
     * 库里那笔价仍在明细里**可见**（{@code special_options[]} 不再列它；改由拼色加价那半体现）。</p>
     *
     * <p>⚠️ 纸表**未登记** {@code 拼3次} 的用料系数（算料侧 fail-closed）⇒ 它**不在**本集合里、
     * 仍按元/套计 —— 见 PR 的未实现项登记。</p>
     */
    static final Set<String> PER_METER_MIXED_OPTIONS = Set.of("拼1次", "拼2次");

    /**
     * 拼色加价的**米数键族** = **该款面料米数**（与报价侧 {@code build_quote.fabric_meters} 同源）。
     *
     * <p>⚠️ 与 {@link #METER_KEYS}（加工费米数 = 主布行米数）**刻意分开**：那是「组合那半」的因子，
     * 本键族是**面料**口径（真值源 §6.1：{@code fabric_meters} = Σ 面料行米数）。单面料行时两者同值。</p>
     */
    private static final List<String> MIXED_COLOR_METER_KEYS =
            List.of("fabric_meters", "processingMeters", "meters");

    /** 樘窗级去重键（#4725「一樘窗 = 一套」同口径：拼色加价**一樘窗只收一次**）。 */
    private static final String MIXED_COLOR_CHARGE_KEY = "\u0000mixed-color-surcharge";

    /** JSON 字符串形态的 {@code processing_info} 解析（自定义 {@code @Select} 路径不经 TypeHandler）。 */
    private static final com.fasterxml.jackson.databind.ObjectMapper JSON =
            new com.fasterxml.jackson.databind.ObjectMapper();

    private final ProcessingFeeCombinationMapper combinationMapper;

    /** 特殊选项对客单价（{@code production_route_rules.customer_unit_price}，V77）。 */
    private final ProductionRouteRuleMapper routeRuleMapper;

    // ══════════════════════════════ 对外结果 ══════════════════════════════

    /**
     * 一个**选中特殊选项**的取价结果（设计 §4.3；R5 + R8「1 套 = 1 樘窗（`craftLineId` 组）」，#4725）。
     *
     * @param name      选项名（**逐字 = {@code processing_info.specialOptions[]} 的元素**
     *                  = {@code production_route_rules.trigger_value}；它是 join key，不得改写）
     * @param unitPrice 该选项的**对客元/套**单价；未定价 = {@code null}（**≠ 0**）；
     *                  {@code billing=per_meter} 时它是**库里那笔价的原值**（仅供审计，不再被取价使用）
     * @param sets      **本行**该选项的计费套数：一樘窗（`craftLineId` 组）内同名选项只收一次 ⇒
     *                  承接那一行 = 1、同樘窗其它行 = **0**（选项仍列出、金额 0 —— **不静默吞掉**）；
     *                  无 {@code craftLineId} 的行**各自成樘窗** ⇒ 每行各 1
     * @param amount    {@code unitPrice × sets}；未定价 / 非承接行 / **改按元/米计** = 0
     * @param priced    是否已定价（{@code false} = 库里 {@code customer_unit_price IS NULL}）
     *                  ⇒ 取价侧**显式可见**，绝不静默按 0 收
     * @param billing   **计价口径**三态（#4855 新增；{@link #BILLING_PER_SET} /
     *                  {@link #BILLING_PER_METER} / {@link #BILLING_UNPRICED}）——
     *                  {@code per_meter} = 该选项**改按元/米计**（拼色加价那半），**不是**「未定价」
     */
    public record SpecialOption(String name, BigDecimal unitPrice, int sets,
                               BigDecimal amount, boolean priced, String billing) {
    }

    /** 计价口径：按**元/套**计（既有 15 项特殊选项）。 */
    public static final String BILLING_PER_SET = "per_set";
    /** 计价口径：按**元/米**计（拼1次 / 拼2次 —— 用户 2026-09-21 裁定，走拼色加价那半）。 */
    public static final String BILLING_PER_METER = "per_meter";
    /** 计价口径：**未定价**（库里 `customer_unit_price IS NULL`）⇒ 计 0 + 可行动提示（不静默）。 */
    public static final String BILLING_UNPRICED = "unpriced";

    /**
     * 拼色加价的取价结果（用户 2026-09-21 裁定）—— **可审计**：金额 / 命中的拼次选项 / 米数 / 米数来源。
     *
     * @param surcharge   加价金额（元）= 单价 × 米数；不适用 / 缺米数 = 0（**≠ null**）
     * @param options     本行选中的**改按元/米计**的拼次选项（审计：它们在 {@code special_options} 里
     *                    以 {@code billing=per_meter} 列出，金额 0 —— 与这里同一份名单）
     * @param meters      加价基数（**该款面料米数**）；不适用 / 缺 = null（与 0 区分）
     * @param metersSource 米数取自哪个键（不许静默）
     */
    public record MixedColor(BigDecimal surcharge, List<String> options,
                             BigDecimal meters, String metersSource) {

        /** 不适用（非拼色款 / 非承接行）：金额 0、无基数 —— **不是**「算不出来」。 */
        public static final MixedColor NONE = new MixedColor(BigDecimal.ZERO, List.of(), null, null);
    }

    /**
     * 一行的加工费结果。
     *
     * @param amount              **组合那半**（元）= 组合单价 × 加工费米数；未定价 / 缺米数 = 0
     *                            （⚠️ **不等于行金额** —— 行金额见 {@link #lineAmount()}）
     * @param feeSource           三态：matched / unpriced / manual（**枚举不变**）
     * @param compositionKey      归一化组合键（未命中时也要记下"当时选的是什么"）
     * @param unitPrice           命中的组合单价（元/米）；未命中 = null
     * @param meters              加工费米数（= 该樘窗主布行米数）；缺 = null
     * @param specialOptions      选中特殊选项的逐项取价（**按选项名 Unicode 码点升序**，确定性）；
     *                            组合未定价时**同样取价**（选项与组合是否定价无关，issue #4594）；
     *                            ⚠️ **改按元/米计**的拼次选项（{@link #PER_METER_MIXED_OPTIONS}）
     *                            不在其中（它们走 {@code mixedColor}）
     * @param specialOptionsTotal Σ 选项价（元）；没选 = 0
     * @param mixedColor          **拼色加价**（用户 2026-09-21 裁定：拼色款另加 2.4 元/米）；
     *                            非拼色款 = {@link MixedColor#NONE}（金额 0）
     * @param detail              可审计构成（落 {@code processing_info.processingFeeDetail}，原样透传）
     * @param hint                未定价 / 缺米数时的**可行动**提示；命中且齐全 = null
     */
    public record Fee(BigDecimal amount, String feeSource, String compositionKey,
                      List<String> items, String matchedRuleId, BigDecimal unitPrice,
                      String priceSource, BigDecimal meters, String metersSource,
                      List<SpecialOption> specialOptions, BigDecimal specialOptionsTotal,
                      MixedColor mixedColor,
                      Map<String, Object> detail, String hint) {

        /**
         * **行加工费** = 组合那半 + Σ 选项价 + **拼色加价**（设计 §4.3：「唯一进订单金额的数」）。
         *
         * <p>{@code amount} 只记组合那半（与 #4406 的既有语义/键名**一字不改**），
         * 行金额由本方法合成 ⇒ 订单金额 / 试算合计都走这里，**不另拼一份口径**。</p>
         *
         * <p>⚠️ {@code fee_source='unpriced'}（组合那半 0）**不蕴含**行金额 0 ——
         * 已定价的特殊选项与拼色加价照常计入（用户裁定 2026-09-19 / issue #4594）。</p>
         */
        public BigDecimal lineAmount() {
            return nz(amount).add(nz(specialOptionsTotal))
                    .add(nz(mixedColor == null ? null : mixedColor.surcharge()));
        }

        /** 选项价合计（非空时才有值；空 = 0，不是 null —— 调用方不必判空）。 */
        private static BigDecimal nz(BigDecimal value) {
            return value == null ? BigDecimal.ZERO : value;
        }

        static Fee unpriced(String compositionKey, List<String> items, BigDecimal unitPrice,
                            String priceSource, BigDecimal meters, String metersSource,
                            List<SpecialOption> specialOptions, MixedColor mixedColor, String setKey,
                            String hint) {
            // 组合那半没有价 ⇒ **只有那一半**记 0；选项那半与拼色加价**照常计入**（用户裁定 2026-09-19 /
            // issue #4594：选项是按套的独立一笔账，与组合是否定价、米数是否齐全无关）。
            // `lineAmount()` = 0 + Σ 选项价 + 拼色加价 ⇒ 订单金额/试算合计都走它，不另拼一份口径。
            BigDecimal optionsTotal = money(optionsTotal(specialOptions));
            return new Fee(BigDecimal.ZERO, FEE_SOURCE_UNPRICED, compositionKey, items, null,
                    unitPrice, priceSource, meters, metersSource, specialOptions, optionsTotal,
                    mixedColor,
                    detail(compositionKey, items, null, unitPrice, priceSource, meters, metersSource,
                            FEE_SOURCE_UNPRICED, BigDecimal.ZERO, specialOptions, optionsTotal,
                            mixedColor, setKey, hint),
                    hint);
        }

        static Fee matched(String compositionKey, List<String> items, String matchedRuleId,
                           BigDecimal unitPrice, String priceSource, BigDecimal meters,
                           String metersSource, List<SpecialOption> specialOptions,
                           MixedColor mixedColor, String setKey, String hint) {
            // 金额按**人类可读刻度**落 detail（`8.00 × 12.30` 的裸乘积是 `98.4000`）：
            // detail 是给人与对账看的，尾随零不是信息；订单金额本身仍是精确值。
            // ⚠️ 不得用裸 `stripTrailingZeros()`：它会把 80.00 变成 `8E+1`（科学计数法进 JSON）
            // ⇒ 前端按 number 解析得到 8E1 字符串，是**新的**静默错账。
            BigDecimal amount = money(unitPrice.multiply(meters));
            BigDecimal optionsTotal = money(optionsTotal(specialOptions));
            return new Fee(amount, FEE_SOURCE_MATCHED, compositionKey, items, matchedRuleId,
                    unitPrice, priceSource, meters, metersSource, specialOptions, optionsTotal,
                    mixedColor,
                    detail(compositionKey, items, matchedRuleId, unitPrice, priceSource, meters,
                            metersSource, FEE_SOURCE_MATCHED, amount, specialOptions, optionsTotal,
                            mixedColor, setKey, hint),
                    hint);
        }

        /**
         * **人工改价**那半（issue #4872）：组合**未命中**活跃价目，商家在订单里就地改价。
         *
         * <p>与 {@link #matched} 同一把尺子：金额 = 单价 × 加工费米数（{@link #money} 去尾零）；
         * {@code unit_price} = override、{@code price_source='manual'}、{@code fee_source='manual'}
         * ⇒ 读面能回答「这个价是谁定的」（detail 键名与既有分支**逐字一致**：只填值，不加键）。</p>
         */
        static Fee manual(String compositionKey, List<String> items, BigDecimal unitPrice,
                          BigDecimal meters, String metersSource, List<SpecialOption> specialOptions,
                          MixedColor mixedColor, String setKey, String hint) {
            BigDecimal amount = money(unitPrice.multiply(meters));
            BigDecimal optionsTotal = money(optionsTotal(specialOptions));
            return new Fee(amount, FEE_SOURCE_MANUAL, compositionKey, items, null,
                    unitPrice, FEE_SOURCE_MANUAL, meters, metersSource, specialOptions, optionsTotal,
                    mixedColor,
                    detail(compositionKey, items, null, unitPrice, FEE_SOURCE_MANUAL, meters,
                            metersSource, FEE_SOURCE_MANUAL, amount, specialOptions, optionsTotal,
                            mixedColor, setKey, hint),
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
                                                  BigDecimal specialOptionsTotal, MixedColor mixedColor,
                                                  String setKey, String hint) {
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
            // ── #4725 新增（**只加不改**：既有 13 个键的语义与键名一字未动）──
            // 樘窗组键（`craftLineId`，缺省 `#<行下标>`）：套身份**可审计** ——
            // 同樘窗的多行在 detail 里 `set_key` 相同（这正是「一樘窗 = 一套」的读面凭据）。
            detail.put("set_key", setKey);
            // ── #4855 新增（**只加不改**：既有 14 个键的语义与键名一字未动）──
            // 拼色加价（用户 2026-09-21 裁定「两处都按 2.4 元/米」）：金额 / 单价 / 基数米数 /
            // 米数来源 / 命中的拼次选项 —— 前端据 `mixed_color_surcharge` 单列一行（判据 5 的三半）。
            MixedColor mc = mixedColor == null ? MixedColor.NONE : mixedColor;
            detail.put("mixed_color_surcharge", mc.surcharge());
            detail.put("mixed_color_surcharge_per_meter", MIXED_COLOR_SURCHARGE_PER_METER);
            detail.put("mixed_color_options", mc.options());
            detail.put("mixed_color_meters", mc.meters());
            detail.put("mixed_color_meters_source", mc.metersSource());
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
                // ── #4855 新增（**只加不改**：既有 5 个键的语义与键名一字未动）──
                // 计价口径三态：`per_set`（元/套）/ `per_meter`（元/米，拼色加价那半）/ `unpriced`。
                row.put("billing", option.billing());
                rows.add(row);
            }
            return rows;
        }

        /**
         * 金额刻度：去尾随零、**保留至少 2 位小数**、禁止科学计数法（{@code 80.00} 不得变 {@code 8E+1}）。
         * 值不变（{@code compareTo} 相等），只是形态可读（人看 detail / 前端按 number 解析）。
         *
         * <p>包内可见（不是 private）：拼色加价那半（{@link ProcessingFeeCalculator#mixedColor}）
         * 与这里**同一把尺子**（两处各写一份取整 = 同一张单两种尾数）。</p>
         */
        static BigDecimal money(BigDecimal value) {
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
        List<?> infos = processingInfos == null ? List.of() : processingInfos;
        // #4725（用户裁定「一樘窗 = 一套」）：**同一樘窗（`craftLineId` 组）内的同名选项只收一次**。
        // 旧口径逐行各收一次 ⇒ 一樘「布 + 纱」两行都选「加铅块」时，**1 套被收成 2 套**。
        // `charged` 记「（樘窗组键, 选项名）」⇒ 只有**第一个**选它的那行承接（顺序确定 ⇒ 两次生成逐值相同）。
        Set<String> charged = new HashSet<>();
        List<Fee> fees = new ArrayList<>();
        for (int i = 0; i < infos.size(); i++) {
            fees.add(feeFor(infos.get(i), priced, optionPrices, charged, windowKey(infos.get(i), i)));
        }
        return fees;
    }

    /**
     * 樘窗组键（#4725）：{@code processing_info.craftLineId} 优先；缺省 ⇒ **本行自成樘窗**。
     *
     * <p>缺省用 {@code "#" + 行下标}（此刻明细行还没有 id —— 见 {@code OrderService.createOrder}）；
     * 两个不同下标天然不等 ⇒ 没有 {@code craftLineId} 的行**各自成樘窗**（与
     * {@code ProcessingOrderService.craftGroupKey} 的「缺省回落本行 itemId」**同一份口径**）。</p>
     */
    static String windowKey(Object processingInfo, int index) {
        Map<String, Object> info = asMap(processingInfo);
        Object raw = info == null ? null : info.get("craftLineId");
        String craftLineId = raw == null ? null : String.valueOf(raw).trim();
        return craftLineId == null || craftLineId.isEmpty() ? "#" + index : craftLineId;
    }

    /**
     * 单行取价（**纯函数**，不碰库）：选配 → 组合键 → 匹配 → 组合单价 × 米数 + Σ 选项价 × 1。
     *
     * <p>命中但米数缺失也返回 {@code unpriced}（**组合那半** 0 元）—— 米数是**组合那半**的另一个因子，
     * 缺它就只能算 0；**不凭 {@code quantity} 猜**（猜出来的钱无人可复核）。</p>
     *
     * <p>特殊选项是**按套的独立一笔账**（用户裁定 2026-09-19 / issue #4594）：**无论组合那半是否
     * 定得下来**（未命中 / 无加工项 / 缺米数）都照常取价并计入行金额 —— 组合未定价 ⇒ 只把**组合那半**
     * 记 0，**不回落** Σ 加工项，也不吞掉已定价的选项价。</p>
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
        // 单行调用 = 该行自成樘窗 ⇒ 选项各收一次（与 #4725 之前逐值相同）
        return feeFor(processingInfo, priced, optionPrices, new HashSet<>(), windowKey(processingInfo, 0));
    }

    /**
     * 单行取价（带**樘窗去重状态**，#4725）。
     *
     * @param charged   已承接的「（樘窗组键, 选项名）」集合（{@link #feesFor} 跨行共享）——
     *                  同一樘窗内同名选项**只有第一行承接**，其余行列出但计 0（不静默）
     * @param windowKey 本行的樘窗组键（见 {@link #windowKey}）
     */
    static Fee feeFor(Object processingInfo, Map<String, ProcessingFeeCombination> priced,
                      Map<String, BigDecimal> optionPrices, Set<String> charged, String windowKey) {
        List<String> items = ProcessingFeeQueryService.featureNames(processingInfo);
        String compositionKey = ProcessingFeeCombinationCommandService.compositionKey(items);
        BigDecimal meters = meters(processingInfo);
        String metersSource = meters == null ? null : metersSource(processingInfo);
        // 选项那半**先算**（issue #4594）：它是按套的独立一笔账 ⇒ 组合那半走哪条分支都不影响它
        List<SpecialOption> specialOptions = specialOptions(processingInfo, optionPrices, charged, windowKey);
        // 拼色加价那半**也先算**（#4855，同一理由：它是独立一笔账，与组合是否定价无关）
        MixedColor mixedColor = mixedColor(processingInfo, charged, windowKey);
        String mixedHint = mixedColorHint(processingInfo, mixedColor, meters);
        if (compositionKey.isEmpty()) {
            return Fee.unpriced(compositionKey, List.of(), null, null, meters, metersSource,
                    specialOptions, mixedColor, windowKey,
                    joinHint("本行没有选配任何加工项 ⇒ 组合那半没有可收的加工费（加工费按选配组合收）。"
                            + "若这单本该有加工费，请确认下单时是否漏选了加工项", mixedHint));
        }
        List<String> normalizedItems = ProcessingFeeQueryService.itemsOf(compositionKey);
        ProcessingFeeCombination row = priced == null ? null : priced.get(compositionKey);
        if (row == null || row.getUnitPrice() == null) {
            // ── 行级人工改价（issue #4872）────────────────────────────────────────────
            // 商家在**未定价**的行上就地改价：本行按 override 收，且建单时同步回「加工费组合」配置
            // （见 OrderService.createOrder 的同事务 upsert）。命中组合时走不到这里 ⇒ override 被忽略。
            BigDecimal override = overridePrice(processingInfo);
            if (override != null) {
                if (meters == null) {
                    // 改价也是「单价 × 米数」⇒ 缺米数同样算不出来（**不凭 quantity 猜**，同 matched 分支）
                    return Fee.unpriced(compositionKey, normalizedItems, override, FEE_SOURCE_MANUAL,
                            null, null, specialOptions, mixedColor, windowKey,
                            joinHint(String.format("本行**人工改价** ¥%s/米，但本行**缺加工费米数** ⇒ "
                                            + "**组合那半**按 0 计（未定价）。加工费米数 = 该**套**主布行米数"
                                            + "（算料侧给出，键 `processingMeters`）⇒ 请补算料米数后重下单",
                                    override.toPlainString()), mixedHint));
                }
                return Fee.manual(compositionKey, normalizedItems, override, meters, metersSource,
                        specialOptions, mixedColor, windowKey,
                        joinHint(unpricedOptionsHint(specialOptions), mixedHint));
            }
            return Fee.unpriced(compositionKey, normalizedItems,
                    null, null, meters, metersSource, specialOptions, mixedColor, windowKey,
                    joinHint(String.format("选配组合「%s」在「加工费组合」里没有价 ⇒ 本行**组合那半**按 0 计（未定价），"
                                    + "**不套任何默认价**。请去「加工费管理」(%s) 为该组合定价，"
                                    + "或确认这些加工项不该组合收费",
                            compositionKey, PRICING_ENTRY), mixedHint));
        }
        if (meters == null) {
            return Fee.unpriced(compositionKey, normalizedItems, row.getUnitPrice(), row.getSource(),
                    null, null, specialOptions, mixedColor, windowKey,
                    joinHint(String.format("选配组合「%s」已定价 ¥%s/米，但本行**缺加工费米数** ⇒ **组合那半**按 0 计。"
                                    + "加工费米数 = 该樘窗主布行米数（算料侧给出，键 `processingMeters`）"
                                    + "⇒ 请补算料米数后重下单",
                            compositionKey, row.getUnitPrice().toPlainString()), mixedHint));
        }
        return Fee.matched(compositionKey, normalizedItems, row.getId(), row.getUnitPrice(),
                row.getSource(), meters, metersSource, specialOptions, mixedColor, windowKey,
                joinHint(unpricedOptionsHint(specialOptions), mixedHint));
    }

    /** 两条提示拼接（空串 / null 不参与；**不吞**任何一条）。 */
    private static String joinHint(String first, String second) {
        if (first == null || first.isBlank()) {
            return second == null || second.isBlank() ? null : second;
        }
        return second == null || second.isBlank() ? first : first + " " + second;
    }

    /**
     * **拼色加价**那半（用户 2026-09-21 裁定：拼色款另加 {@link #MIXED_COLOR_SURCHARGE_PER_METER} 元/米）。
     *
     * <p>三条口径（与报价侧 {@code curtain_calc.build_quote} 逐条对齐 —— 这是「同源同价」的落点）：</p>
     * <ol>
     *   <li><b>只看款式</b>：{@code processing_info.style == 拼色}（与报价侧 `style` 入参同一键、同一值域）；
     *       非拼色款 ⇒ 不适用（金额 0，**不是**「算不出来」）；</li>
     *   <li><b>基数 = 该款面料米数</b>（{@link #MIXED_COLOR_METER_KEYS}，优先 {@code fabric_meters}，
     *       与报价侧 {@code build_quote.fabric_meters} 同源）；<b>缺米数 ⇒ 0 + 显式 hint</b>（不猜米数）；</li>
     *   <li><b>一樘窗只收一次</b>（与 #4725「一樘窗 = 一套」同口径）：报价侧一扇窗一次报价 ⇒
     *       订单侧同一 {@code craftLineId} 组只由**第一行**承接（否则「布 + 纱」两行会各收一次 = 多收）。</li>
     * </ol>
     */
    static MixedColor mixedColor(Object processingInfo, Set<String> charged, String windowKey) {
        List<String> options = perMeterMixedOptions(processingInfo);
        if (!STYLE_MIXED.equals(style(processingInfo))) {
            return MixedColor.NONE;
        }
        if (charged != null && !charged.add(windowKey + MIXED_COLOR_CHARGE_KEY)) {
            // 同樘窗已有承接行 ⇒ 本行不承接（加价 0；承接行在 detail 里可见，不静默）
            return new MixedColor(BigDecimal.ZERO, options, null, null);
        }
        BigDecimal meters = mixedColorMeters(processingInfo);
        if (meters == null) {
            return new MixedColor(BigDecimal.ZERO, options, null, null);
        }
        return new MixedColor(Fee.money(MIXED_COLOR_SURCHARGE_PER_METER.multiply(meters)),
                options, meters, mixedColorMetersSource(processingInfo));
    }

    /**
     * 拼色加价的**可行动**提示：款式=拼色但**缺面料米数** ⇒ 显式说明（不猜米数、不静默按 0 收）。
     *
     * <p>与「组合那半缺米数」的提示**同族**（缺因子 ⇒ 只把该半记 0 + 说清补什么）。</p>
     */
    private static String mixedColorHint(Object processingInfo, MixedColor mixedColor, BigDecimal meters) {
        if (!STYLE_MIXED.equals(style(processingInfo)) || meters != null) {
            return null;
        }
        return String.format("本行款式=拼色，但**缺面料米数**（键 %s）⇒ **拼色加价**（¥%s/米）按 0 计、"
                        + "**不猜米数**。请补算料米数后重下单",
                MIXED_COLOR_METER_KEYS, MIXED_COLOR_SURCHARGE_PER_METER.toPlainString());
    }

    /** 款式（{@code processing_info.style}；缺失 / 空 ⇒ null = 不判断款式）。 */
    private static String style(Object processingInfo) {
        Map<String, Object> info = asMap(processingInfo);
        Object raw = info == null ? null : info.get("style");
        String value = raw == null ? null : String.valueOf(raw).trim();
        return value == null || value.isEmpty() ? null : value;
    }

    /**
     * 本行选中的**改按元/米计**的拼次选项（{@link #PER_METER_MIXED_OPTIONS}；审计用）。
     *
     * <p>精确相等匹配（**不得**用 {@code contains}：错一个字 ⇒ 静默少收/多收钱，同族 #4389）。</p>
     */
    static List<String> perMeterMixedOptions(Object processingInfo) {
        List<String> hit = new ArrayList<>();
        for (String name : specialOptionNames(processingInfo)) {
            if (PER_METER_MIXED_OPTIONS.contains(name)) {
                hit.add(name);
            }
        }
        return hit;
    }

    /** 拼色加价的**基数米数**（该款面料米数）：{@link #MIXED_COLOR_METER_KEYS} 逐键取第一个可解析值。 */
    private static BigDecimal mixedColorMeters(Object processingInfo) {
        Map<String, Object> info = asMap(processingInfo);
        if (info == null) {
            return null;
        }
        for (String key : MIXED_COLOR_METER_KEYS) {
            BigDecimal value = decimal(info.get(key));
            if (value != null) {
                return value;
            }
        }
        return null;
    }

    /** 加价基数取自哪个键（可审计：与工序实例 `qty_source` 同族，不许静默）。 */
    private static String mixedColorMetersSource(Object processingInfo) {
        Map<String, Object> info = asMap(processingInfo);
        if (info == null) {
            return null;
        }
        for (String key : MIXED_COLOR_METER_KEYS) {
            if (decimal(info.get(key)) != null) {
                return key;
            }
        }
        return null;
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
        // 单行调用 = 该行自成樘窗（选项各收一次）
        return specialOptions(processingInfo, optionPrices, new HashSet<>(), windowKey(processingInfo, 0));
    }

    /**
     * 选中特殊选项的逐项取价（带**樘窗去重**，#4725）。
     *
     * <p>「一樘窗 = 一套」（用户裁定 2026-09-20）：同一樘窗（{@code craftLineId} 组）里**同名选项
     * 只收一次** —— 承接的那一行 {@code sets = 1}，同樘窗其它行 {@code sets = 0} 且金额 0
     * （**选项照列**：名称 / 单价 / 定价态可见 ⇒ 不静默吞掉商家的选择）。</p>
     */
    static List<SpecialOption> specialOptions(Object processingInfo, Map<String, BigDecimal> optionPrices,
                                              Set<String> charged, String windowKey) {
        List<String> names = specialOptionNames(processingInfo);
        List<SpecialOption> options = new ArrayList<>();
        for (String name : names) {
            // ⚠️ **改按元/米计**的拼次选项（#4855，用户 2026-09-21 裁定「订单侧撤掉元/套」）：
            // 仍**照列**（金额 0、`billing=per_meter`、`priced=true`）—— 商家勾的选择**不静默吞掉**；
            // 但它**不走按套那半**（走了就是同一件事收两笔 = 双算），改由 `mixedColor`（元/米 × 面料米数）计。
            // 🔴 **不是**「未定价」：库里那笔 `customer_unit_price` **一字未动**（V82 已发布、不可改），
            //    本选项也**不会**进「未定价」提示（`priced=true` ⇒ `unpricedOptionsHint` 不收它）。
            if (PER_METER_MIXED_OPTIONS.contains(name)) {
                BigDecimal listed = optionPrices == null ? null : optionPrices.get(name);
                options.add(new SpecialOption(name, listed, 1, BigDecimal.ZERO, true, BILLING_PER_METER));
                continue;
            }
            // 精确相等匹配（**不得**用 contains：错一个字 ⇒ 静默少收/多收钱）
            BigDecimal unitPrice = optionPrices == null ? null : optionPrices.get(name);
            boolean priced = unitPrice != null;
            // 承接判据 = 「（樘窗组键, 选项名）」首次出现；同樘窗内重复 ⇒ 本行不承接（sets 0、金额 0）
            boolean chargedHere = charged.add(windowKey + '\u0000' + name);
            options.add(new SpecialOption(name, unitPrice, chargedHere ? 1 : 0,
                    priced && chargedHere ? unitPrice : BigDecimal.ZERO, priced,
                    priced ? BILLING_PER_SET : BILLING_UNPRICED));
        }
        // 按**全名**的 Unicode 码点升序（`String` 自然序 = UTF-16 码元序；本域全是 BMP 字符
        // ⇒ 与码点序逐值一致）—— 与 `compositionKey` 的 `TreeSet<String>` **同源**，不自造第二种口径。
        // ⚠️ **不得**用 `codePointAt(0)`（只比首字符）：`加铅块` / `加花边` / `加logo条` / `加立边`
        // 首字符相同 ⇒ 并列 ⇒ 稳定排序退化成**商家勾选顺序** ⇒ 同一笔选择产出两种明细顺序
        // （违反设计 §4.3 的确定性契约；实证：本类测试用首字符相同的两项才照得出）。
        options.sort(Comparator.comparing(SpecialOption::name));
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
                storedMixedColor(detailMap),
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
                    Boolean.TRUE.equals(row.get("priced")),
                    // 存量单（#4855 之前落库）没有 `billing` 键 ⇒ 按当时的**唯一**口径「元/套」读
                    // （那时确实全是按套收的；补一个别的默认值就是给历史单编口径）。
                    row.get("billing") == null ? BILLING_PER_SET : String.valueOf(row.get("billing"))));
        }
        return options;
    }

    /**
     * 落库的拼色加价（**读面与写面同源**：键名只有 {@code detail(...)} 一处定义）。
     *
     * <p>存量单（#4855 之前生成）没有 {@code mixed_color_surcharge} 键 ⇒ 返回
     * {@link MixedColor#NONE}（金额 0）—— 当时确实没有这一笔，**不是**「漏读」，也**不重算**
     * （R13：已生成订单一字不变）。</p>
     */
    private static MixedColor storedMixedColor(Map<String, Object> detailMap) {
        if (!detailMap.containsKey("mixed_color_surcharge")) {
            return MixedColor.NONE;
        }
        return new MixedColor(
                nzStatic(decimal(detailMap.get("mixed_color_surcharge"))),
                stringList(detailMap.get("mixed_color_options")),
                decimal(detailMap.get("mixed_color_meters")),
                text(detailMap.get("mixed_color_meters_source")));
    }

    private static BigDecimal nzStatic(BigDecimal value) {
        return value == null ? BigDecimal.ZERO : value;
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

    /**
     * 行级**人工改价**单价（元/米）：{@code processing_info.processingFeeOverride}（issue #4872）。
     *
     * <p>只认**正数**：缺键 / 非数值 / {@code ≤ 0} 一律返回 {@code null}（= 没有改价）。
     * 为什么 0 与负数不算改价：「0 元改价」与「没改价」在金额上不可区分，而前者会把一行加工费
     * **静默算成 0**（同 #4308「静默回落」纪律：静默 = 算错钱且无人知道）⇒ 视为未改价，
     * 走既有的 {@code unpriced} 路径（金额 0 + 可行动提示，**显式可见**）。</p>
     */
    private static BigDecimal overridePrice(Object processingInfo) {
        Map<String, Object> info = asMap(processingInfo);
        BigDecimal value = info == null ? null : decimal(info.get(OVERRIDE_KEY));
        return value != null && value.compareTo(BigDecimal.ZERO) > 0 ? value : null;
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
