package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.entity.ProcessingFeeCombination;
import com.migao.admin.mapper.ProcessingFeeCombinationMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 加工费**消费面**（V68 表的取价点；issue #4406，P1；用户裁定 2026-09-19）。
 *
 * <h2>它替换了什么</h2>
 * 旧口径 = <b>Σ 加工项单价 × 数量</b>（{@code OrderService.sumProcessingFee} 的 {@code extractProcessingItems} 求和）
 * ⇒ #4386 让商家能配「组合 → 元/米」，但**配了组合费用订单金额一分不变**（消费面未接）。
 * 新口径 = <b>选配 → 归一化组合键 → 匹配 {@code processing_fee_combinations} → 单价 × 加工费米数</b>。
 *
 * <h2>口径（用户裁定，不得自行放宽）</h2>
 * 「**未定价组合 ⇒ 加工费 = 0（unpriced），直接切，不回落 Σ 加工项**」
 * ⇒ 未命中**绝不**静默套任何默认价（#4308「静默回落」同族纪律：静默 = 算错钱且无人知道）。
 * 代价已知并接受：商家必须先配组合，否则加工费为 0。
 *
 * <h2>为什么单独一个类（而不是塞回 OrderService）</h2>
 * ① 取价是**纯函数**（{@code processing_info} + 价目表 → 一个数 + 可审计构成），
 *    与订单生命周期无关 ⇒ 可单测、可被下单页/Agent 侧共用（单一真值源 R10 的前提）；
 * ② {@code OrderService} 已 13 个依赖，再塞取价逻辑会让「谁在算加工费」不可 grep
 *    （同 #4386 对写面/读面的处置）。
 *
 * <h2>三条不许违反的纪律</h2>
 * <ul>
 *   <li><b>组合键归一化只有一份</b>：复用
 *       {@link ProcessingFeeCombinationCommandService#compositionKey}（写面冻结的口径：
 *       trim → 丢空 → 去重 → 按 Unicode 码点升序 → {@code +} 连接）——
 *       自己拼一份 ⇒ 商家录入与下单匹配可以不一致，且**不会变红**；</li>
 *   <li><b>加工费米数 = 该樘窗主布行米数</b>（裁定 R-b）：{@code processingMeters}（算料侧主布行米数），
 *       兼容键 {@code fabric_meters}；纱**不另按米收**（已含在组合档位单价里）。缺米数 = 算不出钱 ⇒
 *       **不凭 {@code quantity} 猜**，同样记 {@code unpriced}；</li>
 *   <li><b>两套账不互读</b>（真值源 §4 / R9）：本类**只**读 {@code processing_fee_combinations}
 *       （对顾客收的售价），**绝不**读 {@code production_operations.unit_price} / 加工项目录单价
 *       （给工人付的成本）—— 互读 = 把内部计件单价泄漏成对客售价。</li>
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

    /** JSON 字符串形态的 {@code processing_info} 解析（自定义 {@code @Select} 路径不经 TypeHandler）。 */
    private static final com.fasterxml.jackson.databind.ObjectMapper JSON =
            new com.fasterxml.jackson.databind.ObjectMapper();

    private final ProcessingFeeCombinationMapper combinationMapper;

    // ══════════════════════════════ 对外结果 ══════════════════════════════

    /**
     * 一行的加工费结果。
     *
     * @param amount        加工费金额（**唯一进订单金额的数**）；未定价 / 缺米数 = 0
     * @param feeSource     三态：matched / unpriced / manual
     * @param compositionKey 归一化组合键（未命中时也要记下"当时选的是什么"）
     * @param unitPrice     命中的组合单价（元/米）；未命中 = null
     * @param meters        加工费米数（= 该樘窗主布行米数）；缺 = null
     * @param detail        可审计构成（落 {@code processing_info.processingFeeDetail}，原样透传）
     * @param hint          未定价 / 缺米数时的**可行动**提示；命中且齐全 = null
     */
    public record Fee(BigDecimal amount, String feeSource, String compositionKey,
                      List<String> items, String matchedRuleId, BigDecimal unitPrice,
                      String priceSource, BigDecimal meters, String metersSource,
                      Map<String, Object> detail, String hint) {

        static Fee unpriced(String compositionKey, List<String> items, BigDecimal unitPrice,
                            String priceSource, BigDecimal meters, String metersSource, String hint) {
            return new Fee(BigDecimal.ZERO, FEE_SOURCE_UNPRICED, compositionKey, items, null,
                    unitPrice, priceSource, meters, metersSource,
                    detail(compositionKey, items, null, unitPrice, priceSource, meters, metersSource,
                            FEE_SOURCE_UNPRICED, BigDecimal.ZERO, hint),
                    hint);
        }

        static Fee matched(String compositionKey, List<String> items, String matchedRuleId,
                           BigDecimal unitPrice, String priceSource, BigDecimal meters,
                           String metersSource) {
            // 金额按**人类可读刻度**落 detail（`8.00 × 12.30` 的裸乘积是 `98.4000`）：
            // detail 是给人与对账看的，尾随零不是信息；订单金额本身仍是精确值。
            // ⚠️ 不得用裸 `stripTrailingZeros()`：它会把 80.00 变成 `8E+1`（科学计数法进 JSON）
            // ⇒ 前端按 number 解析得到 8E1 字符串，是**新的**静默错账。
            BigDecimal amount = money(unitPrice.multiply(meters));
            return new Fee(amount, FEE_SOURCE_MATCHED, compositionKey, items, matchedRuleId,
                    unitPrice, priceSource, meters, metersSource,
                    detail(compositionKey, items, matchedRuleId, unitPrice, priceSource, meters,
                            metersSource, FEE_SOURCE_MATCHED, amount, null),
                    null);
        }

        /** 可审计构成的**唯一**构造点（键名冻结：新增键只在这里加，读面不另拼一份）。 */        private static Map<String, Object> detail(String compositionKey, List<String> items,
                                                  String matchedRuleId, BigDecimal unitPrice,
                                                  String priceSource, BigDecimal meters,
                                                  String metersSource, String feeSource,
                                                  BigDecimal amount, String hint) {
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
            detail.put("hint", hint);
            return detail;
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
        List<Fee> fees = new ArrayList<>();
        for (Object info : processingInfos == null ? List.<Object>of() : processingInfos) {
            fees.add(feeFor(info, priced));
        }
        return fees;
    }

    /**
     * 单行取价（**纯函数**，不碰库）：选配 → 组合键 → 匹配 → 单价 × 米数。
     *
     * <p>命中但米数缺失也返回 {@code unpriced}（0 元）—— 米数是金额的另一个因子，
     * 缺它就只能算 0；**不凭 {@code quantity} 猜**（猜出来的钱无人可复核）。</p>
     */
    public static Fee feeFor(Object processingInfo, Map<String, ProcessingFeeCombination> priced) {
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
        return Fee.matched(compositionKey, normalizedItems, row.getId(), row.getUnitPrice(),
                row.getSource(), meters, metersSource);
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
                text(detailMap.get("meters_source")), detailMap, text(detailMap.get("hint")));
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
