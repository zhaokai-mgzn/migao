package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.dto.ProcessingOrderResponse;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.util.StringUtils;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 加工单**读面**单元（issue #8770「快照/读面」一档，从 {@link ProcessingOrderService} **纯搬运**）。
 *
 * <p><b>单一职责</b>：商家侧 / agent 的**唯一取数口** —— 列表（关键词 / 状态 / 只看外发）+
 * 详情 + 实体→DTO 映射 + 加工单纸上的码（{@code scan_url}）。**不写库**：只有
 * {@code selectList} / {@code selectByKeyword} / {@code selectBatchIds} / {@code selectOne} / {@code selectById}。</p>
 *
 * <p><b>搬运口径</b>：方法体、注释、异常码与文案**一字未改**。改动只有四类，逐条可复算：
 * ① 可见性 **2** 处（{@code public list} / {@code public getDetail} → 同包可见；公开入口仍在门面，
 * 门面留 3~5 行委托，签名/返回类型/语义不变）；
 * ② {@code resolveProcessingOrder} / {@code resolveOrder} 仍住门面（状态机 / 打印计数也在用）⇒
 * 本类经窄接口 {@link Owner} **回调**，那两处调用改成 {@code owner.xxx(...)}；
 * ③ 扫码域名在门面的 {@code @Value} 字段上 ⇒ 经 {@link Owner#scanBaseUrl()} **即时取值**
 * （既有判据用 {@code ReflectionTestUtils.setField} 在构造之后换域名，缓存会读到旧值）；
 * ④ 日志器随类搬迁（{@code @Slf4j}）—— 两条 {@code log.warn} 的文案与参数一字未改。</p>
 *
 * <p><b>为什么 {@code loadOrders} 搬过来</b>：它是列表路径**专属**的批量取数（#4304 的 N+1 防线），
 * 唯一调用方是 {@code list} ⇒ 与读面同生共死。⚠️ 它的「空集返回可变表」契约（#6226：
 * {@code orders.get(po.getOrderId())} 的键**未判空**）随代码逐字搬走，未改一行。</p>
 */
@Slf4j
class ProcessingOrderReadFace {

    /** 读面对门面的**只读**外呼面（单号解析 / 域名仍住门面：不复制第二份口径）。 */
    interface Owner {
        ProcessingOrder resolveProcessingOrder(String rawId, Long tenantId);

        Order resolveOrder(String rawId, Long tenantId);

        String scanBaseUrl();
    }

    private final ProcessingOrderMapper processingOrderMapper;
    private final OrderMapper orderMapper;
    private final ObjectMapper objectMapper;
    private final Owner owner;

    ProcessingOrderReadFace(ProcessingOrderMapper processingOrderMapper, OrderMapper orderMapper,
                            ObjectMapper objectMapper, Owner owner) {
        this.processingOrderMapper = processingOrderMapper;
        this.orderMapper = orderMapper;
        this.objectMapper = objectMapper;
        this.owner = owner;
    }

    /** 搬运自门面；**行为契约的权威注释仍在** {@link ProcessingOrderService#list}。 */
    List<ProcessingOrderResponse> list(String keyword, String status, Long tenantId,
                                              Boolean outsourced) {
        List<ProcessingOrder> list;
        if (StringUtils.hasText(keyword)) {
            list = processingOrderMapper.selectByKeyword(keyword.trim(), tenantId);
        } else {
            LambdaQueryWrapper<ProcessingOrder> wrapper = new LambdaQueryWrapper<ProcessingOrder>()
                    .eq(ProcessingOrder::getTenantId, tenantId)
                    .eq(ProcessingOrder::getDeleted, 0)
                    .orderByDesc(ProcessingOrder::getCreatedAt)
                    .last("LIMIT 100");
            if (StringUtils.hasText(status)) {
                wrapper.eq(ProcessingOrder::getStatus, status);
            }
            list = processingOrderMapper.selectList(wrapper);
        }
        if (Boolean.TRUE.equals(outsourced)) {
            // 过滤成**副本**：不原地改 mapper 返回的集合（那会把「被裁过的列表」留给上游/同一次请求里
            // 的第二个读面；测试里的 mock 更会当场暴露这件事）
            list = list.stream()
                    .filter(po -> StringUtils.hasText(po.getProcessorSupplierId()))
                    .toList();
        }
        Map<String, Order> orders = loadOrders(list);
        List<ProcessingOrderResponse> result = new ArrayList<>();
        for (ProcessingOrder po : list) {
            result.add(toResponse(po, tenantId, orders.get(po.getOrderId())));
        }
        return result;
    }

    /**
     * 批量取回列表所需的订单（issue #4304）。
     *
     * <p><b>为什么必须批量</b>：列表此前逐行调用 {@link #toResponse(ProcessingOrder, Long)}，
     * 而后者内部 {@code orderMapper.selectById(po.getOrderId())} 只为拿
     * orderNo/customerName/customerPhone ⇒ N 行 N 次单查。实测 31 行的列表请求里
     * {@code FROM orders} 单行查询 63 条、本地耗时 ~2.0s（云 dev DB 每跳几十毫秒）。
     * 这里一次 {@code IN} 取回（{@code selectBatchIds}），逐行按 orderId 建映射。</p>
     *
     * <p><b>租户过滤不在本方法</b>：{@code selectBatchIds} 与 {@code selectById} 同为 BaseMapper
     * 标准方法，租户条件由 {@code TenantLineInnerInterceptor} 注入、软删由 {@code Order} 的
     * {@code @TableLogic} 兜底 ⇒ 与单查同口径，不因批量而放宽。</p>
     */
    private Map<String, Order> loadOrders(List<ProcessingOrder> list) {
        Set<String> orderIds = new LinkedHashSet<>();
        for (ProcessingOrder po : list) {
            if (po.getOrderId() != null) {
                orderIds.add(po.getOrderId());
            }
        }
        if (orderIds.isEmpty()) {
            // #6226：空集分支**必须**返回容忍空键的表。此前是 `Map.of()`（不可变空表）—— 它的
            // `get(null)` 会抛 NPE，而调用点 `orders.get(po.getOrderId())` 的键**未判空**
            // ⇒ 该批加工单只要 `order_id` 全为空就整页 500。下面非空分支返回的是
            // `new HashMap<>()`（同族、`get(null)` 返 null）⇒ 这里取同一形态，两个分支契约一致。
            return new HashMap<>();
        }
        List<Order> orders = orderMapper.selectBatchIds(orderIds);
        Map<String, Order> byId = new HashMap<>();
        if (orders != null) {
            for (Order order : orders) {
                byId.put(order.getId(), order);
            }
        }
        return byId;
    }

    ProcessingOrderResponse getDetail(String rawId, Long tenantId) {
        ProcessingOrder po = owner.resolveProcessingOrder(rawId, tenantId);
        if (po == null) {
            // 订单还没有加工单是正常状态（issue #3887）：rawId 若能解析为有效订单（tenant 隔离），
            // 返回 null → ApiResponse.success(null) → 前端 ProcessingOrderBlock 走
            // res.data?.data ?? null / setNotFound(!data) 展示「生成加工单」态；
            // 订单也不存在（真无效 ID）才保持 404。
            if (owner.resolveOrder(rawId, tenantId) == null) {
                throw BusinessException.notFound("加工单");
            }
            return null;
        }
        return toResponse(po, tenantId);
    }

    /** 搬运自门面；**行为契约的权威注释仍在** {@link ProcessingOrderService#getDetail}。 */
    /**
     * 单条路径（详情/状态变更）：按 {@code po.getOrderId()} 单查订单。
     * 行为与 #4304 之前逐字相同 —— 列表路径改用 {@link #toResponse(ProcessingOrder, Long, Order)}
     * 批量取回的订单，两条路径的响应字段口径共用同一段映射。
     */
    private ProcessingOrderResponse toResponse(ProcessingOrder po, Long tenantId) {
        return toResponse(po, tenantId, orderMapper.selectById(po.getOrderId()));
    }

    /**
     * 加工单纸上的码 = {@code {稳定域名}/o/{短码}}（issue #6867 / B3；设计
     * {@code docs/design/worker-h5-scan-and-report.md} §11.3 的「后端 · 读面键」行）。
     *
     * <p><b>服务端拼装</b>（前端不拼 URL —— 拼法只有这一份），域名走上面 {@link #shortLinkBaseUrl}
     * 那条既有配置。形态与 {@code ProductionService.scanUrlOf(ProcessingSetPartToken)} **同款**
     * （设计 §11.3 明写「base + 路径段不同 ⇒ **各自一份，不许互相拼**」：{@code /s/} 解「哪一张
     * 部位纸」、{@code /o/} 解「哪一张加工单纸」，两个码空间互不命中）。</p>
     *
     * <p>🔴 <b>短码为空（存量行尚未分配）⇒ 返回 {@code null}</b>，**绝不产出 {@code /o/null}
     * 这种假码** —— 前端按「无码」处（纸面印 {@code —}），而不是把一个扫不开也输不进的串印出去。
     * 与 {@code token} 无关：撤销（{@code qr_token} 置 NULL）**不碰短码**，故本键**不因撤销变 null**
     * （那一跳 {@code /o/{短码}} 见 token 为空 ⇒ 410 Gone，归 B2）。</p>
     */
    private String scanUrlOf(ProcessingOrder po) {
        if (po == null || !StringUtils.hasText(po.getShortCode())) {
            return null;
        }
        String base = owner.scanBaseUrl() == null ? "" : owner.scanBaseUrl().trim();
        while (base.endsWith("/")) {
            base = base.substring(0, base.length() - 1);
        }
        return base + "/o/" + po.getShortCode();
    }

    @SuppressWarnings("unchecked")
    private ProcessingOrderResponse toResponse(ProcessingOrder po, Long tenantId, Order order) {
        ProcessingOrderResponse resp = new ProcessingOrderResponse();
        resp.setId(po.getId());
        resp.setTenantId(String.valueOf(po.getTenantId()));
        resp.setOrderId(po.getOrderId());
        resp.setProcessingOrderNo(po.getProcessingOrderNo());
        resp.setProcessor(po.getProcessor());
        resp.setProcessorSupplierId(po.getProcessorSupplierId());
        resp.setExpectedDeliveryDate(po.getExpectedDeliveryDate());
        resp.setStatus(po.getStatus());
        resp.setRemark(po.getRemark());
        resp.setTemplateVersion(po.getTemplateVersion());
        resp.setGeneratedAt(po.getGeneratedAt());
        resp.setIssuedAt(po.getIssuedAt());
        resp.setInProcessingAt(po.getInProcessingAt());
        resp.setCompletedAt(po.getCompletedAt());
        resp.setCancelledAt(po.getCancelledAt());
        resp.setCancelledReason(po.getCancelledReason());
        resp.setPrintCount(po.getPrintCount());
        // 路线可观测（V60，issue #4308）：详情 API 必须能查出「实际走哪条 / 想走哪条 / 怎么来的」
        resp.setRouteKey(po.getRouteKey());
        resp.setRouteRequestedKey(po.getRouteRequestedKey());
        resp.setRouteSource(po.getRouteSource());
        // 单据类型（V159，issue #7079）：同表列，随既有查询**已经带回** ⇒ 零新增查询（同 route_* 三列）。
        resp.setOrderKind(po.getOrderKind());
        // 加工单纸上的码（issue #6867 / B3；设计 §11.3「后端 · 读面键」）：**追加**两键，
        // 键**恒在**（未知 ⇒ null），既有键一字不动。
        // 🔴 **零新增查询**：`po` 由本方法的唯一入口 `resolveProcessingOrder`（详情）/
        // `selectList`/`selectByKeyword`（列表）**已经带回**（`short_code` 是同表列）⇒
        // 这里只做映射与拼串，不为这两键多查一次 DB。
        resp.setShortCode(po.getShortCode());
        resp.setScanUrl(scanUrlOf(po));
        // 订单信息（列表路径由调用方批量取回后传入，单条路径传入单查结果；null 时字段留空，同旧行为）
        if (order != null) {
            resp.setOrderNo(order.getOrderNo());
            resp.setCustomerName(order.getCustomerName());
            resp.setCustomerPhone(order.getCustomerPhone());
        }
        // 快照解析（兼容 JSON 字符串：自定义 @Select 查询路径不经过 typeHandler）
        Object snapshot = po.getItemsSnapshot();
        if (snapshot instanceof String s && !s.isBlank()) {
            try {
                snapshot = objectMapper.readValue(s, Object.class);
            } catch (Exception e) {
                log.warn("加工单快照 JSON 字符串解析失败: po={}, err={}", po.getProcessingOrderNo(), e.getMessage());
                snapshot = null;
            }
        }
        if (snapshot != null) {
            try {
                resp.setItems(objectMapper.convertValue(snapshot,
                        objectMapper.getTypeFactory().constructCollectionType(List.class,
                                ProcessingOrderResponse.ProcessingOrderItemBrief.class)));
            } catch (Exception e) {
                log.warn("加工单快照解析失败: po={}, err={}", po.getProcessingOrderNo(), e.getMessage());
            }
        }
        return resp;
    }
}
