package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingFeeCombination;
import com.migao.admin.entity.ProcessingItem;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.ProcessingFeeCombinationMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 加工费组合定价**读面**（V68，issue #4386，P1）。
 *
 * <p><b>为什么读写分开</b>：写面（{@link ProcessingFeeCombinationCommandService}）只有它能改价；
 * 读面（列表 / 缺口）谁都能调。把两者塞进一个类会让「谁在改加工费」变得不可 grep（同 #4308 对路线库的处置）。</p>
 *
 * <p><b>缺口视图的「已存在」是什么</b>（{@code GET /production/processing-fee-gaps}）：
 * 「**订单里实际出现过、但库里查不到价**」的选配组合。这是本包范围内唯一**有数据可查**的
 * 「已存在组合」源 —— 商家穷举幂集（n 个特征 → 2ⁿ）被用户明确否掉，故缺口必须从**真实成交**
 * 反推。⚠️ 待 {@code processing_rules}（可组合性校验）落码后，应把「商品可配组合」并入本清单
 * （**本包不做**，已在 PR 登记为 follow-up）。</p>
 *
 * <p><b>解析口径与 {@code OrderService.extractProcessingItems} 同源</b>：
 * {@code order_items.processing_info = {processingItems:[{name,…},…]}}；JSON 字符串形态
 * （JacksonTypeHandler 未生效时）也要能吃下，否则缺口恒为空 = 静默失效。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ProcessingFeeQueryService {

    /**
     * 缺口扫描的订单行上限。
     *
     * <p>为什么设上限而不是全表扫：缺口是**给商家看的待办**，不是对账报表；全表扫会把
     * 「打开页面」变成一次全量 JSONB 解析。超限时响应带 {@code scanned_truncated=true}
     * —— **不静默**（商家看到的是「已扫最近 N 行」而不是「全库都齐了」）。</p>
     */
    private static final int GAP_SCAN_LIMIT = 2000;

    private final ProcessingFeeCombinationMapper combinationMapper;
    private final ProcessingItemMapper processingItemMapper;
    private final OrderItemMapper orderItemMapper;

    private static final ObjectMapper JSON = new ObjectMapper();

    // ══════════════════════════════ 列表 ══════════════════════════════

    /**
     * 组合定价列表（{@code GET /production/processing-fee-combinations}）。
     *
     * <p>只回**活跃**行（{@code status=active} + 未软删 + 同租户），按 {@code sort_order, composition_key}
     * 稳定排序 —— 顺序不稳定会让商家看到的表每次刷新都换位。</p>
     */
    public Map<String, Object> combinations(Long tenantId) {
        List<ProcessingFeeCombination> rows = activeCombinations(tenantId);
        List<Map<String, Object>> views = new ArrayList<>(rows.size());
        for (ProcessingFeeCombination row : rows) {
            views.add(combinationView(row));
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("combinations", views);
        result.put("total", views.size());
        return result;
    }

    /** 单行展示形态（列表项 / 写面响应**同一份** —— 前端同一个 TS 类型渲染两者）。 */
    public Map<String, Object> combinationView(ProcessingFeeCombination row) {
        Map<String, Object> view = new LinkedHashMap<>();
        view.put("id", row.getId());
        view.put("composition_key", row.getCompositionKey());
        view.put("items", itemsOf(row.getCompositionKey()));
        view.put("unit_price", row.getUnitPrice());
        view.put("unit", "元/米");
        view.put("status", row.getStatus());
        view.put("sort_order", row.getSortOrder() == null ? 0 : row.getSortOrder());
        view.put("source", row.getSource());
        view.put("updated_at", row.getUpdatedAt() == null ? null : row.getUpdatedAt().toString());
        return view;
    }

    /** 归一化键 → 特征名有序列表（key 与 items 同源，不维护第二份口径）。 */
    public static List<String> itemsOf(String compositionKey) {
        if (compositionKey == null || compositionKey.isBlank()) {
            return List.of();
        }
        List<String> items = new ArrayList<>();
        for (String part : compositionKey.split("\\+")) {
            if (!part.isBlank()) {
                items.add(part);
            }
        }
        return items;
    }

    // ══════════════════════════════ 缺口可查 ══════════════════════════════

    /**
     * **缺口可查**（{@code GET /production/processing-fee-gaps}）：订单里出现过、库里查不到价的组合。
     *
     * <p>为什么必须有这个面：没有它，商家只能靠「顾客下单后订单金额不对」发现漏配价 ——
     * 那已经是**错价落库之后**了。有它，漏配的组合在配置阶段就可见（同 #4308 的 routing-gaps）。</p>
     *
     * <p>每条带 {@code order_count}（出现次数，商家按成交热度排序补价）与 {@code note}
     * （可行动提示）。**不发明任何默认价** —— 缺口就是缺口。</p>
     */
    public Map<String, Object> feeGaps(Long tenantId) {
        Set<String> priced = new LinkedHashSet<>();
        for (ProcessingFeeCombination row : activeCombinations(tenantId)) {
            if (row.getCompositionKey() != null) {
                priced.add(row.getCompositionKey());
            }
        }

        List<OrderItem> orderItems = orderItemMapper.selectList(
                new LambdaQueryWrapper<OrderItem>()
                        .eq(OrderItem::getTenantId, tenantId)
                        .eq(OrderItem::getDeleted, 0)
                        .orderByDesc(OrderItem::getCreatedAt)
                        .last("LIMIT " + GAP_SCAN_LIMIT));

        Map<String, int[]> counts = new LinkedHashMap<>();
        for (OrderItem orderItem : orderItems == null ? List.<OrderItem>of() : orderItems) {
            String key = ProcessingFeeCombinationCommandService.compositionKey(featureNames(orderItem.getProcessingInfo()));
            if (key.isEmpty() || priced.contains(key)) {
                continue;
            }
            counts.computeIfAbsent(key, k -> new int[1])[0]++;
        }

        List<Map<String, Object>> rows = new ArrayList<>();
        for (Map.Entry<String, int[]> entry : counts.entrySet()) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("composition_key", entry.getKey());
            row.put("items", itemsOf(entry.getKey()));
            row.put("order_count", entry.getValue()[0]);
            row.put("note", "这个选配组合在订单里出现过，但「加工费组合」里没有它的价 ⇒ 请去定价，"
                    + "或确认这些加工项不该组合收费");
            rows.add(row);
        }
        // 按成交热度降序（商家先补最常卖的），同热度按键稳定排序（顺序不得随机）
        rows.sort(Comparator.<Map<String, Object>>comparingInt(r -> -(Integer) r.get("order_count"))
                .thenComparing(r -> String.valueOf(r.get("composition_key"))));

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("unpriced_combinations", rows);
        result.put("unpriced_combination_total", rows.size());
        result.put("scanned_order_items", orderItems == null ? 0 : orderItems.size());
        result.put("scanned_truncated", orderItems != null && orderItems.size() >= GAP_SCAN_LIMIT);
        return result;
    }

    // ══════════════════════════════ 读取工具 ══════════════════════════════

    /** 活跃组合（tenant + deleted=0 + status=active，按 sort_order/composition_key 稳定返回）。 */
    List<ProcessingFeeCombination> activeCombinations(Long tenantId) {
        List<ProcessingFeeCombination> rows = combinationMapper.selectList(
                new LambdaQueryWrapper<ProcessingFeeCombination>()
                        .eq(ProcessingFeeCombination::getTenantId, tenantId)
                        .eq(ProcessingFeeCombination::getDeleted, 0)
                        .eq(ProcessingFeeCombination::getStatus, "active")
                        .orderByAsc(ProcessingFeeCombination::getSortOrder)
                        .orderByAsc(ProcessingFeeCombination::getCompositionKey));
        return rows == null ? List.of() : rows;
    }

    /**
     * 活跃加工项目录按名索引（护栏用：组合里的特征名必须是**存在且活跃**的加工项）。
     * 与 {@link ProcessingFeeCombinationCommandService} 共用**同一份**读取口径（不复制第二份）。
     */
    Map<String, ProcessingItem> activeItemsByName(Long tenantId) {
        List<ProcessingItem> rows = processingItemMapper.selectList(
                new LambdaQueryWrapper<ProcessingItem>()
                        .eq(ProcessingItem::getTenantId, tenantId)
                        .eq(ProcessingItem::getDeleted, 0)
                        .eq(ProcessingItem::getStatus, "active"));
        Map<String, ProcessingItem> byName = new LinkedHashMap<>();
        if (rows != null) {
            for (ProcessingItem row : rows) {
                byName.put(row.getName(), row);
            }
        }
        return byName;
    }

    /**
     * 从 {@code order_items.processing_info} 里取加工项**名**列表
     * （口径 = {@code OrderService.extractProcessingItems} 的 {@code processingItems[].name}）。
     */
    static List<String> featureNames(Object processingInfo) {
        Object normalized = processingInfo;
        if (normalized instanceof String s && !s.isBlank()) {
            try {
                normalized = JSON.readValue(s, Map.class);
            } catch (Exception e) {
                log.warn("processingInfo JSON 字符串解析失败（缺口扫描跳过该行）: {}", e.getMessage());
                return List.of();
            }
        }
        if (!(normalized instanceof Map<?, ?> info)) {
            return List.of();
        }
        Object raw = info.get("processingItems");
        if (!(raw instanceof List<?> list)) {
            return List.of();
        }
        List<String> names = new ArrayList<>();
        for (Object element : list) {
            if (element instanceof Map<?, ?> entry && entry.get("name") != null) {
                names.add(String.valueOf(entry.get("name")));
            }
        }
        return names;
    }

    /** 供写面复用的单价解析（null = 该字段缺失；非数值/负数由调用方转成 422 逐条理由）。 */
    static BigDecimal toDecimal(Object value) {
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
}
