package com.migao.admin.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingItem;
import com.migao.admin.mapper.ProcessingItemMapper;
import lombok.extern.slf4j.Slf4j;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static com.migao.admin.service.ProcessingOrderService.*;

/**
 * 加工单**快照构建**单元（issue #8770「快照/读面」一档，从 {@link ProcessingOrderService} **纯搬运**）。
 *
 * <p><b>单一职责</b>：订单明细 → 加工单快照行（{@code processing_items} 的固化真相）。**不写库**：
 * 只有 {@code processing_item_catalog} 的只读补齐（{@code processingItemMapper.selectById}）。</p>
 *
 * <p><b>为什么快照要独立成单元</b>：它是**唯一**把 {@code order_items.processing_info} 的键族
 * （工艺规格白名单 + 算料输出 + 销售信息）翻译成「加工单纸面字段」的地方 —— 漏一个键 = 车间少一道活
 * / 少一个展示字段，而快照是生成那一刻的固化真相，事后补不回来。放在门面里时它与
 * 派单池 / 自动批次 / 生成族 / 状态机混在 2,653 行里，读改一处要防四面。</p>
 *
 * <p><b>搬运口径</b>：方法体、注释、异常语义**一字未改**。改动只有三类，逐条可复算：
 * ① 可见性 **1** 处（{@code buildSnapshot} 由 {@code private} 提升到同包可见 —— 门面留 3 行委托，
 * 三个既有调用点（{@code generate} / {@code derivePositionPayload} / 派单池 {@code Owner}）**一字未改**）；
 * ② 三个白名单常量仍是门面的 {@code static final}（**公共 API / 判据取用面，本档不动**）⇒
 * 本类经 {@code import static ...ProcessingOrderService.*} 引用，那三处引用行**逐字未改**；
 * ③ 日志器随类搬迁（{@code @Slf4j}）—— 两条 {@code log.warn} 的**文案与参数一字未改**，
 * 变的只有 logger 名（与前面两档搬出的单元同款处置）。</p>
 *
 * <p><b>为什么不搬 {@code loadOrderItems}</b>：它是**三个单元共用**的读（{@code generate} /
 * {@code derivePositionPayload} / 派单池 {@code Owner}），且快照构建只**吃** items 参数、
 * 从不自己加载 ⇒ 留在门面（搬它只会把已搬单元的调用面一起改，收益为零）。</p>
 */
@Slf4j
class ProcessingOrderSnapshotBuilder {

    private final ProcessingItemMapper processingItemMapper;
    private final ObjectMapper objectMapper;

    ProcessingOrderSnapshotBuilder(ProcessingItemMapper processingItemMapper, ObjectMapper objectMapper) {
        this.processingItemMapper = processingItemMapper;
        this.objectMapper = objectMapper;
    }

    /**
     * 快照构建（五要素 + options；不含销售价——决策 2）。
     * 加工项 options 下单时未落库，此处从加工项目录补齐（设计文档查漏点 1）。
     *
     * <p><b>craft spec + 算料输出（issue #4354，设计文档 §4.9）</b>：订单侧自 #4346 起把工艺规格与
     * 算料输出落在 {@code processing_info} 顶层；本方法**逐键**取（{@code copyIfPresent}）——
     * 新键不加进白名单就**不会进快照**，而快照是加工单的**固化真相**（生成时的条件工序与计件系数
     * 都从它读）⇒ 漏一个键 = 车间少一道活 / 少一个展示字段，事后补不回来。
     * 逐键透传的代价是「缺键就缺」（存量单没有这些键）—— **不造值**是硬约束。</p>
     */
    @SuppressWarnings("unchecked")
    List<Map<String, Object>> buildSnapshot(List<OrderItem> items, Long tenantId) {
        List<Map<String, Object>> snapshot = new ArrayList<>();
        for (OrderItem item : items) {
            // 归一化：processingInfo 可能是 Map（BaseMapper 路径）或 JSON 字符串（自定义 @Select 路径）
            Map<String, Object> pi = normalizeProcessingInfo(item.getProcessingInfo());
            // 🔴 存量行：`order_items.processing_info` **可为 NULL**（真库实证 issue #5550：待派池里
            // 29 行有 **15 行**是 NULL）⇒ 归一化结果是**可能为 null 的缺值**，不得直接解引用
            // —— #4909 那行 `str(pi.get("saleForm"))` 踩的正是这里，智能派单因此**恒 500**
            //（读面把整池的每一行都过一遍，NULL 行必被扫到；这不是间歇故障）。
            // 缺值语义 = 既没有加工项、也没有 `saleForm` ⇒ 与「无加工项的非卖布行」走**同一条**既有语义：跳过。
            if (pi == null) {
                continue;
            }
            List<Map<String, Object>> procs = extractProcessingItems(pi);
            // 卖布行（`saleForm = 布料`）**天然没有加工项**（按米卖布，不选加工项）⇒ 旧过滤把它整行丢掉，
            // 于是 `buildPositionPayload` 的布料路线分支（`deriveRouteKey`，issue #4529）**永不执行**
            // ⇒ 整件商品零工序（真库实证：加工单 JG-20260921-8237 缺「9231 遮光窗帘」的裁剪/打包，issue #4909）。
            // 其余「无加工项」行仍按旧语义跳过（配件 / 赠品行不成部位，行为逐字不变）。
            // 卖布判据（issue #7222）：缺 `saleForm` 时按**订单行已落库的布料专属事实**兜底 ——
            // API / 米宝 / 回归脚本漏写 `saleForm` 时，这一行仍必须进快照，否则
            // `buildPositionPayload` 的布料分支永不执行 ⇒ 工人拿不到裁剪 / 打包活（#4909 的同族形态）。
            Map<String, Object> fabricEvidence = new LinkedHashMap<>(pi);
            if (item.getSellingMethod() != null) {
                fabricEvidence.put("sellingMethod", item.getSellingMethod());
            }
            if (item.getRollCount() != null) {
                fabricEvidence.put("rollCount", item.getRollCount());
            }
            if (procs.isEmpty() && !isFabricSaleLine(fabricEvidence)) {
                continue;
            }
            Map<String, Object> entry = new LinkedHashMap<>();
            // 明细行 id：拼色绑组的组键来源（§4.8 的 craftLineId 取「主布行的 order_item.id」）
            entry.put("itemId", item.getId());
            entry.put("productName", item.getProductName());
            entry.put("quantity", item.getQuantity());
            entry.put("width", item.getWidth());
            entry.put("height", item.getHeight());
            // 销售信息（与加工项同存 processing_info，前端写入）
            copyIfPresent(pi, entry, "sku");
            copyIfPresent(pi, entry, "skuCode", "sku");
            copyIfPresent(pi, entry, "colorName");
            copyIfPresent(pi, entry, "sellingMethod");
            // 布料专属事实（issue #7222）：列值 = **服务端落库的事实**，优先于 processing_info 的同名键
            // ⇒ 客户端漏写 `saleForm` 时，路线键与单据类型仍能认出这一行是卖布行。
            if (item.getSellingMethod() != null) {
                entry.put("sellingMethod", item.getSellingMethod());
            }
            if (item.getRollCount() != null) {
                entry.put("rollCount", item.getRollCount());
            }
            copyIfPresent(pi, entry, "doorWidth");
            copyIfPresent(pi, entry, "unit");
            // 特殊选项（issue #4230 v1a）：订单侧**新携带** specialOptions: string[]，
            // 落在既有 processingInfo JSONB 内（**无需迁移**）；加工单快照透传一份，
            // 生成时的条件工序/计件系数都从快照读（快照是加工单的固化真相）。
            copyIfPresent(pi, entry, "specialOptions");
            // 工艺规格 + 算料输出（issue #4354）：全键逐字透传（缺键就缺）
            for (String key : CRAFT_SPEC_SNAPSHOT_KEYS) {
                copyIfPresent(pi, entry, key);
            }
            for (String key : CALC_OUTPUT_SNAPSHOT_KEYS) {
                // 取值键名可能与落键键名不同（formula_text ← processing_info.formulaText，issue #4555）
                copyIfPresent(pi, entry, CALC_OUTPUT_SOURCE_KEY_ALIASES.getOrDefault(key, key), key);
            }
            // 显式字段覆盖（V63，issue #4362，S1）：order_items 的 craft spec **列**最后叠加 ——
            // 推导链的**最高优先级**是「显式字段」，JSONB 键是存量单的旧载体（同一事实的两种落法）。
            // 列非空即覆盖同名的 JSONB 键；列全空（存量单 / 未填）⇒ 本行是 no-op，
            // 快照与迁移前**逐字相同** ⇒ 派生路径不受影响（它是长期兜底，不退场）。
            entry.putAll(OrderLineCraftFields.toSnapshotKeys(item));
            // 加工项明细 + options 补齐
            List<Map<String, Object>> itemsWithOptions = new ArrayList<>();
            for (Map<String, Object> p : procs) {
                Map<String, Object> enriched = new LinkedHashMap<>(p);
                Object id = p.get("id");
                if (id != null) {
                    ProcessingItem piEntity = processingItemMapper.selectById(String.valueOf(id));
                    if (piEntity != null) {
                        enriched.put("options", piEntity.getOptions());
                        if (!enriched.containsKey("unit")) {
                            enriched.put("unit", piEntity.getUnit());
                        }
                        // 加工项**显式声明**的工艺（V78，issue #4452）：路线键「工艺」维的受控来源。
                        // 缺省 ⇒ 不落键（缺键就是缺键，派生链再走存量兜底 —— 不造值）。
                        if (piEntity.getCraftHint() != null && !piEntity.getCraftHint().isBlank()) {
                            enriched.put("craftHint", piEntity.getCraftHint().trim());
                        }
                    }
                }
                itemsWithOptions.add(enriched);
            }
            entry.put("processingItems", itemsWithOptions);
            snapshot.add(entry);
        }
        return snapshot;
    }

    private void copyIfPresent(Map<String, Object> from, Map<String, Object> to, String key) {
        copyIfPresent(from, to, key, key);
    }

    /**
     * processing_info 归一化：Map 直接用；JSON 字符串（自定义 @Select 路径，不经过
     * JacksonTypeHandler）解析为 Map；其它形态返回 null。
     */
    @SuppressWarnings("unchecked")
    private Map<String, Object> normalizeProcessingInfo(Object processingInfo) {
        if (processingInfo instanceof Map) {
            return (Map<String, Object>) processingInfo;
        }
        if (processingInfo instanceof String s && !s.isBlank()) {
            try {
                return objectMapper.readValue(s, Map.class);
            } catch (Exception e) {
                log.warn("processingInfo JSON 字符串解析失败: {}", e.getMessage());
            }
        }
        return null;
    }

    private void copyIfPresent(Map<String, Object> from, Map<String, Object> to, String fromKey, String toKey) {
        Object v = from.get(fromKey);
        if (v != null) {
            to.put(toKey, v);
        }
    }

    /** 解析 processing_info 的加工项列表（与 OrderService.extractProcessingItems 同语义，兼容 JSON 字符串） */
    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> extractProcessingItems(Object processingInfo) {
        Map<String, Object> normalized = normalizeProcessingInfo(processingInfo);
        if (normalized == null) {
            return java.util.Collections.emptyList();
        }
        try {
            Object raw = normalized.get("processingItems");
            if (!(raw instanceof List)) {
                return java.util.Collections.emptyList();
            }
            List<Map<String, Object>> result = new ArrayList<>();
            for (Object element : (List<Object>) raw) {
                if (element instanceof Map) {
                    result.add(new LinkedHashMap<>((Map<String, Object>) element));
                }
            }
            return result;
        } catch (Exception e) {
            log.warn("解析 processingInfo 失败: {}", e.getMessage());
            return java.util.Collections.emptyList();
        }
    }
}
