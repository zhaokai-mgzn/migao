package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingOrderSet;
import com.migao.admin.entity.ProductAttribute;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingOrderSetMapper;
import com.migao.admin.mapper.ProductAttributeMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * 一体机（机台旁那块屏 + 一把有线扫码枪）的**只读**裁高读面（母单 #5161；设计
 * {@code docs/design/cutting-height-config-and-terminal.md} §2.5 工人面那一行 + §2.6 屏一/屏二）。
 *
 * <p><b>本类只搬三件东西</b>：① 用**既有** {@link ProductionScanService#resolve} 把码定位到
 * （套 × 部位）；② 把订单侧取值（成品高 / 安装工艺 / 特殊选项 / 加工项 / 是否定型）**逐字**取库，
 * 交给**既有** {@link CuttingHeightConfigService#preview} 算；③ 把结果与详情面字段拼成一屏。</p>
 *
 * <p>🔴 <b>不写机器</b>（用户 2026-09-29 裁定①「下发先不做」）：本类**不开串口、不发 Modbus、
 * 不写寄存器**，也不产出任何下发用的 token —— 页面的终点是「请在机器屏输入 X.XXX 米」。
 * 判据 = {@code WorkerProductionCuttingHeightTest} 的源码面守卫（出现 serial / modbus / register
 * 之类 ⇒ 红）＋ worker-h5 侧「机台流程零写请求」判据。</p>
 *
 * <p>🔴 <b>不造第二份口径</b>：命中判定与取整**只有** {@code CuttingHeightCalculator} 一处、
 * 默认种子**只有** {@code CuttingHeightDefaults} 一处、码解析**只有** {@code ProductionScanService}
 * 一处、取整三位小数由配置决定（{@code rounding.digits}）—— 本类只搬运取值与拼装响应。
 * 缺值一律如实回 {@code null}（页面显示「—」）+ 进 {@code missing}，**不猜、不按 0 算**。</p>
 *
 * <p><b>权限</b>：本类**不**持有任何商家权限判据；准入 = 调用方（
 * {@code WorkerProductionController}）校验的「有效工人 session」。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class WorkerCuttingHeightService {

    /** 一体机只认部位级码（水洗唛）：旧码到加工单级 ⇒ 不知道是哪个部位，显式拒绝（绝不猜）。 */
    public static final String GRANULARITY_SET_POSITION = "set_position";

    /** 缺项判据名（进 {@code positions[].missing}，页面据此**指名**报缺，不静默显示 0）。 */
    static final String MISSING_POSITION = "position";
    static final String MISSING_FINISHED_HEIGHT = "finished_height";
    static final String MISSING_CUTTING_HEIGHT = "cutting_height";

    /** 商品品牌落在 {@code product_attributes.attr_key}（与 {@code ProductService.ATTR_KEY_BRAND} 同值）。 */
    private static final String ATTR_KEY_BRAND = "brand";

    private final ProductionScanService productionScanService;
    private final CuttingHeightConfigService cuttingHeightConfigService;
    private final OrderItemMapper orderItemMapper;
    private final OrderMapper orderMapper;
    private final ProcessingOrderMapper processingOrderMapper;
    private final ProcessingOrderSetMapper processingOrderSetMapper;
    private final ProductAttributeMapper productAttributeMapper;

    /**
     * 扫一次部位级水洗唛 ⇒ 一屏（详情 + 逐部位裁剪高度）。
     *
     * @param token    扫码内容（短码 / 裸 token / 整条印刷 URL —— 归一由 {@code ProductionScanService} 做）
     * @param tenantId 当前租户
     * @return {@code {granularity, scanned, order, positions[]}}；每个部位行见 {@link #positionRow}
     */
    public Map<String, Object> read(String token, Long tenantId) {
        if (!StringUtils.hasText(token)) {
            throw BusinessException.validationError("扫码内容不能为空");
        }
        Map<String, Object> scan = productionScanService.resolve(token.trim(), null, tenantId);
        if (!needsSelection(scan).isEmpty()) {
            // 旧码（加工单级）能定位到单、定位不到部位 ⇒「这套是布帘还是纱帘」无解。
            // 默认取第 1 个部位 = 把裁高算到错的帘上（裁短 = 事故）⇒ 显式拒绝，给可行动出口。
            throw BusinessException.validationError(
                    "这个码只能定位到加工单（旧码），不是水洗唛的部位级码 ⇒ 一体机不知道算哪个部位；"
                            + "请扫部位级水洗唛（" + "/s/<短码>" + "）");
        }
        List<Map<String, Object>> overview = asMapList(asMap(scan.get("set_overview")).get("positions"));
        if (overview.isEmpty()) {
            throw BusinessException.validationError(
                    "这次扫码没有解析出任何部位（本套的部位清单为空）⇒ 无法算裁剪高度");
        }

        String orderId = text(scan.get("order_id"));
        Order order = orderOf(orderId, tenantId);
        Map<String, OrderItem> items = itemsOf(orderId, tenantId);
        Map<String, BigDecimal> fabric = fabricMeters(scan);
        Map<String, String> brands = brands(items.values(), tenantId);
        String scannedItemId = text(asMap(scan.get("position")).get("order_item_id"));

        List<Map<String, Object>> rows = new ArrayList<>(overview.size());
        for (Map<String, Object> entry : overview) {
            rows.add(positionRow(entry, items, brands, fabric, tenantId, scannedItemId));
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("granularity", GRANULARITY_SET_POSITION);
        Map<String, Object> scanned = new LinkedHashMap<>();
        scanned.put("order_item_id", scannedItemId);
        scanned.put("position_kind", text(asMap(scan.get("position")).get("position_kind")));
        out.put("scanned", scanned);

        Map<String, Object> header = new LinkedHashMap<>();
        header.put("order_id", orderId);
        header.put("order_no", order == null ? null : order.getOrderNo());
        header.put("customer_name", order == null ? null : order.getCustomerName());
        header.put("processing_order_no", scan.get("processing_order_no"));
        header.put("set_no", scan.get("set_no"));
        header.put("set_index", scan.get("set_index"));
        header.put("set_count", setCount(orderId, tenantId));
        out.put("order", header);
        out.put("positions", rows);
        return out;
    }

    /**
     * 一个部位行：详情面字段（缺 ⇒ {@code null}，**不猜**）+ 该部位的裁剪高度。
     *
     * <p>缺成品高 / 缺部位名 ⇒ 该行**不进**计算、进 {@code missing}（页面显示「—」并指名报缺）；
     * 预览被服务端拒（越界等）⇒ {@code missing=[cutting_height]} + {@code missing_reason} 逐字带出
     * 服务端理由 —— 三条失败路径都**显式**，没有一条静默按 0。</p>
     */
    private Map<String, Object> positionRow(Map<String, Object> entry, Map<String, OrderItem> items,
                                            Map<String, String> brands, Map<String, BigDecimal> fabric,
                                            Long tenantId, String scannedItemId) {
        String itemId = text(entry.get("order_item_id"));
        OrderItem item = itemId == null ? null : items.get(itemId);
        Map<String, Object> info = item == null ? Map.of() : normalize(item.getProcessingInfo());

        Map<String, Object> row = new LinkedHashMap<>();
        row.put("order_item_id", itemId);
        row.put("position_kind", text(entry.get("position_kind")));
        row.put("position_name", text(entry.get("position_name")));
        row.put("scanned", itemId != null && itemId.equals(scannedItemId));
        // 🔴 `product_id` **可为空**（存量明细，同 `processing_info` 可为 NULL 一族 ⇒ issue #6219）：
        // `brands.get(null)` 在**不可变表**上抛 NPE（`Map.of().get(null)` / `Map.of("k","v").get(null)`
        // 实跑均 NPE；`LinkedHashMap.get(null)` 返 null）—— 空键必须显式短路，别交给 `Map` 的语义。
        String productId = item == null ? null : item.getProductId();
        row.put("brand", productId == null ? null : brands.get(productId));
        row.put("product_name", item == null ? null : item.getProductName());
        row.put("width", item == null ? null : item.getWidth());
        row.put("height", item == null ? null : item.getHeight());
        row.put("craft", item == null ? null : item.getCraft());
        row.put("curtain_type", item == null ? null : item.getCurtainType());
        row.put("open_count", item == null ? null : item.getOpenCount());
        row.put("cutting_mode", item == null ? null : item.getCuttingMode());
        row.put("fullness", item == null ? null : item.getFullness());
        row.put("position_remark", text(entry.get("remark")));
        row.put("fabric_meters", fabric.get(itemId));

        String position = text(entry.get("position_kind"));
        BigDecimal finishedHeight = item == null ? null : item.getHeight();
        List<String> missing = new ArrayList<>();
        if (position == null) {
            missing.add(MISSING_POSITION);
        }
        if (finishedHeight == null) {
            missing.add(MISSING_FINISHED_HEIGHT);
        }
        if (!missing.isEmpty()) {
            // 缺成品高 / 缺部位名：**不算**（不按 0、不按部位默认值猜），如实报缺
            row.put("base", null);
            row.put("cutting_height", null);
            row.put("rounding", null);
            row.put("hits", List.of());
            row.put("misses", List.of());
            row.put("missing", missing);
            row.put("missing_reason", "缺少" + String.join(" / ", missing) + "，无法计算裁剪高度");
            return row;
        }

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("position", position);
        body.put("finished_height", finishedHeight);
        body.put("craft", item.getCraft());
        body.put("cutting_mode", item.getCuttingMode());
        body.put("special_options", strings(info.get("specialOptions")));
        body.put("processing_items", itemNames(info.get("processingItems")));
        body.put("is_shaped", item.getIsShaped());
        Map<String, Object> calc;
        try {
            calc = cuttingHeightConfigService.preview(tenantId, body);
        } catch (BusinessException rejected) {
            // 取值越界一类（服务端的范围判据是**唯一**一份）⇒ 逐字带出理由，不让整屏 4xx
            row.put("base", null);
            row.put("cutting_height", null);
            row.put("rounding", null);
            row.put("hits", List.of());
            row.put("misses", List.of());
            row.put("missing", List.of(MISSING_CUTTING_HEIGHT));
            row.put("missing_reason", rejected.getMessage());
            return row;
        }
        row.put("base", calc.get("base"));
        row.put("cutting_height", calc.get("cutting_height"));
        row.put("rounding", calc.get("rounding"));
        // hits = 命中且已配置取值（页面预勾，可手改本次显示）；misses = 命中但未配置取值
        // （如「画线」）—— 前端**必须**标黄且**不计入**合计（口径见 CuttingHeightCalculator）
        row.put("hits", calc.get("hits"));
        row.put("misses", calc.get("misses"));
        row.put("missing", List.of());
        row.put("missing_reason", null);
        return row;
    }

    /** 本单订单行（复用既有 {@code selectByOrderId}：它显式绑 autoResultMap ⇒ {@code processing_info} 是 Map）。 */
    private Map<String, OrderItem> itemsOf(String orderId, Long tenantId) {
        if (orderId == null) {
            return Map.of();
        }
        List<OrderItem> rows = orderItemMapper.selectByOrderId(orderId, tenantId);
        Map<String, OrderItem> out = new LinkedHashMap<>();
        if (rows != null) {
            for (OrderItem row : rows) {
                if (row.getId() != null) {
                    out.put(row.getId(), row);
                }
            }
        }
        return out;
    }

    private Order orderOf(String orderId, Long tenantId) {
        if (orderId == null) {
            return null;
        }
        return orderMapper.selectOne(new LambdaQueryWrapper<Order>()
                .eq(Order::getId, orderId)
                .eq(Order::getTenantId, tenantId)
                .eq(Order::getDeleted, 0)
                .last("LIMIT 1"));
    }

    /**
     * 本单的**套数**（屏一显示「套数」；取不到 ⇒ {@code null}，页面显示「—」—— 不猜成 1）。
     */
    private Long setCount(String orderId, Long tenantId) {
        if (orderId == null) {
            return null;
        }
        List<ProcessingOrder> orders = processingOrderMapper.selectList(new LambdaQueryWrapper<ProcessingOrder>()
                .eq(ProcessingOrder::getOrderId, orderId)
                .eq(ProcessingOrder::getTenantId, tenantId)
                .eq(ProcessingOrder::getDeleted, 0));
        if (orders == null || orders.isEmpty()) {
            return null;
        }
        List<String> ids = orders.stream().map(ProcessingOrder::getId).filter(Objects::nonNull).toList();
        if (ids.isEmpty()) {
            return null;
        }
        return processingOrderSetMapper.selectCount(new LambdaQueryWrapper<ProcessingOrderSet>()
                .in(ProcessingOrderSet::getProcessingOrderId, ids)
                .eq(ProcessingOrderSet::getTenantId, tenantId)
                .eq(ProcessingOrderSet::getDeleted, 0));
    }

    /** 品牌（{@code product_attributes.attr_key='brand'}）；查不到 ⇒ 该商品没有品牌行，页面显示「—」。 */
    private Map<String, String> brands(Collection<OrderItem> items, Long tenantId) {
        List<String> productIds = items.stream()
                .map(OrderItem::getProductId)
                .filter(StringUtils::hasText)
                .distinct()
                .toList();
        if (productIds.isEmpty()) {
            // 同族坑（issue #6219）：这里曾 `return Map.of();`（**不可变空表**）⇒ 调用方一旦用
            // 空键索引就抛 NPE（`Map.of().get(null)` 实跑 = NPE），把「缺值」变成 500。
            // 空集也返回**可变**表：本方法的契约是「查不到 ⇒ 没有这一项」，不是「不许索引」。
            return new LinkedHashMap<>();
        }
        List<ProductAttribute> rows = productAttributeMapper.selectList(new LambdaQueryWrapper<ProductAttribute>()
                .in(ProductAttribute::getProductId, productIds)
                .eq(ProductAttribute::getTenantId, tenantId)
                .eq(ProductAttribute::getAttrKey, ATTR_KEY_BRAND));
        Map<String, String> out = new LinkedHashMap<>();
        if (rows != null) {
            for (ProductAttribute row : rows) {
                if (row.getProductId() != null && StringUtils.hasText(row.getAttrValue())) {
                    out.putIfAbsent(row.getProductId(), row.getAttrValue());
                }
            }
        }
        return out;
    }

    /**
     * 用料米数（{@code set_overview.cut_plan[].fabric_meters}）—— **逐字**取既有算料读面，
     * 本类**不重算**（算料是另一套公式，见设计 §2.4；在两处各写一份必然漂移）。
     */
    private Map<String, BigDecimal> fabricMeters(Map<String, Object> scan) {
        Map<String, BigDecimal> out = new LinkedHashMap<>();
        for (Map<String, Object> row : asMapList(asMap(scan.get("set_overview")).get("cut_plan"))) {
            String itemId = text(row.get("order_item_id"));
            Object meters = row.get("fabric_meters");
            if (itemId != null && meters instanceof BigDecimal value) {
                out.put(itemId, value);
            }
        }
        return out;
    }

    // ============================================================ 取值（逐字取库，不重算）

    /**
     * 订单行要素归一（复用 {@code OrderLineCraftFields.normalize}：Map 直接用 / JSON 字符串解析），
     * 拿不到 ⇒ 空表（下面一律按**缺键**读，不造值）。
     */
    private static Map<String, Object> normalize(Object processingInfo) {
        Map<String, Object> info = OrderLineCraftFields.normalize(processingInfo);
        return info == null ? Map.of() : info;
    }

    /** 字符串数组归一（空白项丢弃、去重保序 —— 与 {@code ProcessingOrderService.specialOptions} 同口径）。 */
    private static List<String> strings(Object raw) {
        if (!(raw instanceof List<?> list)) {
            return List.of();
        }
        List<String> out = new ArrayList<>(list.size());
        for (Object element : list) {
            String value = text(element);
            if (value != null && !out.contains(value)) {
                out.add(value);
            }
        }
        return out;
    }

    /**
     * 加工项名（{@code processingInfo.processingItems[].name}）—— 判据域与
     * {@code ProcessingOrderService.processingItemNames} **同口径**（只认 Map 元素 + 非空名字）。
     */
    private static List<String> itemNames(Object raw) {
        if (!(raw instanceof List<?> list)) {
            return List.of();
        }
        List<String> out = new ArrayList<>(list.size());
        for (Object element : list) {
            if (element instanceof Map<?, ?> map) {
                String name = text(map.get("name"));
                if (name != null && !out.contains(name)) {
                    out.add(name);
                }
            }
        }
        return out;
    }

    private static List<String> needsSelection(Map<String, Object> scan) {
        return scan.get("needs_selection") instanceof List<?> list
                ? list.stream().map(String::valueOf).toList()
                : List.of();
    }

    private static String text(Object raw) {
        if (raw == null) {
            return null;
        }
        String value = String.valueOf(raw).trim();
        return value.isEmpty() ? null : value;
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> asMap(Object raw) {
        return raw instanceof Map<?, ?> map ? (Map<String, Object>) map : Map.of();
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> asMapList(Object raw) {
        if (!(raw instanceof List<?> list)) {
            return List.of();
        }
        List<Map<String, Object>> out = new ArrayList<>(list.size());
        for (Object element : list) {
            if (element instanceof Map<?, ?> map) {
                out.add((Map<String, Object>) map);
            }
        }
        return out;
    }
}
