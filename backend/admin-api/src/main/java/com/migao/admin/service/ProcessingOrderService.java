package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.dto.ProcessingOrderGenerateRequest;
import com.migao.admin.dto.ProcessingOrderResponse;
import com.migao.admin.dto.ProcessingOrderUpdateRequest;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ThreadLocalRandom;

/**
 * 加工单服务（issue #3340，设计文档 docs/design/processing-order-design.md）
 *
 * 核心职责：
 * 1. 生成加工单（快照固化五要素 + options，不含销售价）+ 订单 confirmed→producing 联动；
 * 2. 加工单状态机（generated→issued→in_processing→completed | cancelled），非法迁移拒绝；
 * 3. 取消联动（generated 取消 → 订单 producing→confirmed 回退）；
 * 4. 订单侧联动（shipped 守卫 / 订单取消自动作废）由 OrderService 完成。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ProcessingOrderService {

    private final ProcessingOrderMapper processingOrderMapper;
    private final OrderMapper orderMapper;
    private final OrderItemMapper orderItemMapper;
    private final ProcessingItemMapper processingItemMapper;
    private final OrderService orderService;
    private final ObjectMapper objectMapper;

    /** 加工单状态机（与 OrderService.STATUS_TRANSITIONS 同模式） */
    private static final Map<String, Set<String>> STATUS_TRANSITIONS = Map.of(
            "generated", Set.of("issued", "cancelled"),
            "issued", Set.of("in_processing", "cancelled"),
            "in_processing", Set.of("completed", "cancelled"),
            "completed", Set.of(),
            "cancelled", Set.of()
    );

    private static final Map<String, String> STATUS_LABELS = Map.of(
            "generated", "已生成",
            "issued", "已发加工",
            "in_processing", "加工中",
            "completed", "加工完成",
            "cancelled", "已取消"
    );

    /** 加工单号序号（JG-YYYYMMDD-XXXX） */
    private static final java.util.concurrent.atomic.AtomicInteger PO_SEQ =
            new java.util.concurrent.atomic.AtomicInteger(ThreadLocalRandom.current().nextInt(1000, 9999));

    private static final DateTimeFormatter PO_DATE_FMT = DateTimeFormatter.ofPattern("yyyyMMdd");

    // ============================================================ 生成

    /**
     * 批量生成加工单（全事务；单个失败不影响已成功项结果返回，但整体回滚）。
     * 返回逐单结果（success/processingOrderNo/message）。
     */
    @Transactional(rollbackFor = Exception.class)
    public List<GenerateResult> generate(List<String> orderIds, Long tenantId, String operator) {
        if (orderIds == null || orderIds.isEmpty()) {
            throw BusinessException.validationError("orderIds 不能为空");
        }
        List<GenerateResult> results = new ArrayList<>();
        for (String rawId : orderIds) {
            try {
                results.add(generateOne(rawId, tenantId, operator));
            } catch (BusinessException e) {
                results.add(GenerateResult.fail(rawId, e.getMessage()));
            }
        }
        return results;
    }

    private GenerateResult generateOne(String rawId, Long tenantId, String operator) {
        Order order = resolveOrder(rawId, tenantId);
        if (order == null) {
            throw new BusinessException("ORDER_NOT_FOUND", "无法找到订单：" + rawId, 404);
        }
        // 仅已确认订单可生成加工单（pending 未付款 / 已取消不允许）
        if (!"confirmed".equals(order.getStatus())) {
            throw BusinessException.validationError(
                    String.format("订单 %s 当前状态 [%s] 不允许生成加工单，须为已确认", order.getOrderNo(), order.getStatus()));
        }
        List<OrderItem> items = orderItemMapper.selectByOrderId(order.getId(), tenantId);
        List<Map<String, Object>> snapshot = buildSnapshot(items, tenantId);
        if (snapshot.isEmpty()) {
            throw BusinessException.validationError("订单 " + order.getOrderNo() + " 无加工项，无需生成加工单");
        }
        // 幂等：同一订单最多一个非取消态加工单（DB 层另有 partial unique index 兜底）
        ProcessingOrder existing = processingOrderMapper.selectActiveByOrderId(order.getId(), tenantId);
        if (existing != null) {
            throw BusinessException.validationError(
                    "订单 " + order.getOrderNo() + " 已有加工单 " + existing.getProcessingOrderNo() + "，请勿重复生成");
        }

        ProcessingOrder po = ProcessingOrder.builder()
                .tenantId(tenantId)
                .orderId(order.getId())
                .processingOrderNo(generateOrderNo())
                .status("generated")
                .itemsSnapshot(snapshot)
                .templateVersion(1)
                .generatedBy(operator)
                .generatedAt(OffsetDateTime.now())
                .printCount(0)
                .deleted(0)
                .build();

        // 联动先行（验收复核 #3345 P2②）：先推进订单 confirmed→producing，再落加工单。
        // 落库失败时回退订单状态，杜绝「producing 无加工单」孤儿态；
        // 并发重复生成由 partial unique index 兜底 → 转幂等错误（P2①）。
        orderService.updateOrderStatus(order.getId(), "producing");
        try {
            processingOrderMapper.insert(po);
        } catch (org.springframework.dao.DuplicateKeyException e) {
            orderService.revertProducingToConfirmed(order.getId(), "加工单并发重复生成，订单状态回退");
            throw BusinessException.validationError(
                    "订单 " + order.getOrderNo() + " 加工单已生成（并发操作），请刷新后重试");
        } catch (Exception e) {
            try {
                orderService.revertProducingToConfirmed(order.getId(), "加工单生成失败，订单状态回退");
            } catch (Exception revertErr) {
                log.warn("加工单生成失败且状态回退失败: orderId={}, err={}", order.getId(), revertErr.getMessage());
            }
            throw e;
        }
        log.info("生成加工单: no={}, orderId={}, tenantId={}, operator={}",
                po.getProcessingOrderNo(), order.getId(), tenantId, operator);
        return GenerateResult.ok(rawId, po.getProcessingOrderNo());
    }

    /**
     * 快照构建（五要素 + options；不含销售价——决策 2）。
     * 加工项 options 下单时未落库，此处从加工项目录补齐（设计文档查漏点 1）。
     */
    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> buildSnapshot(List<OrderItem> items, Long tenantId) {
        List<Map<String, Object>> snapshot = new ArrayList<>();
        for (OrderItem item : items) {
            Object pi = item.getProcessingInfo();
            List<Map<String, Object>> procs = extractProcessingItems(pi);
            if (procs.isEmpty()) {
                continue;
            }
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("productName", item.getProductName());
            entry.put("quantity", item.getQuantity());
            entry.put("width", item.getWidth());
            entry.put("height", item.getHeight());
            // 销售信息（与加工项同存 processing_info，前端写入）
            if (pi instanceof Map) {
                Map<String, Object> info = (Map<String, Object>) pi;
                copyIfPresent(info, entry, "sku");
                copyIfPresent(info, entry, "skuCode", "sku");
                copyIfPresent(info, entry, "colorName");
                copyIfPresent(info, entry, "sellingMethod");
                copyIfPresent(info, entry, "doorWidth");
                copyIfPresent(info, entry, "unit");
            }
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

    private void copyIfPresent(Map<String, Object> from, Map<String, Object> to, String fromKey, String toKey) {
        Object v = from.get(fromKey);
        if (v != null) {
            to.put(toKey, v);
        }
    }

    /** 解析 processing_info 的加工项列表（与 OrderService.extractProcessingItems 同语义） */
    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> extractProcessingItems(Object processingInfo) {
        if (!(processingInfo instanceof Map)) {
            return java.util.Collections.emptyList();
        }
        try {
            Object raw = ((Map<String, Object>) processingInfo).get("processingItems");
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

    private Order resolveOrder(String rawId, Long tenantId) {
        Order byId = orderMapper.selectById(rawId);
        if (byId != null && tenantId.equals(byId.getTenantId())) {
            return byId;
        }
        return orderMapper.selectOne(new LambdaQueryWrapper<Order>()
                .eq(Order::getTenantId, tenantId)
                .eq(Order::getOrderNo, rawId)
                .eq(Order::getDeleted, 0)
                .last("LIMIT 1"));
    }

    private String generateOrderNo() {
        String base = "JG-" + LocalDate.now().format(PO_DATE_FMT) + "-";
        // DB 唯一约束兜底；此处随机化降低同秒碰撞概率
        return base + String.format("%04d", PO_SEQ.incrementAndGet());
    }

    // ============================================================ 状态更新

    /**
     * 加工单状态更新（action: issue/start/complete/cancel）。
     * 状态机校验 + 订单联动（cancel → producing→confirmed 回退）。
     */
    @Transactional(rollbackFor = Exception.class)
    public ProcessingOrderResponse updateStatus(String rawId, ProcessingOrderUpdateRequest req,
                                                Long tenantId, String operator) {
        if (req == null || !StringUtils.hasText(req.getAction())) {
            throw BusinessException.validationError("action 不能为空");
        }
        ProcessingOrder po = resolveProcessingOrder(rawId, tenantId);
        if (po == null) {
            throw BusinessException.notFound("加工单");
        }
        String action = req.getAction();
        String target;
        switch (action) {
            case "issue": target = "issued"; break;
            case "start": target = "in_processing"; break;
            case "complete": target = "completed"; break;
            case "cancel": target = "cancelled"; break;
            default: throw BusinessException.validationError("无效的加工单操作: " + action);
        }
        String current = po.getStatus();
        if (!STATUS_TRANSITIONS.getOrDefault(current, Set.of()).contains(target)) {
            throw BusinessException.validationError(String.format(
                    "加工单状态不允许从 [%s] 变更为 [%s]", label(current), label(target)));
        }
        if ("cancel".equals(action) && !StringUtils.hasText(req.getReason())) {
            throw BusinessException.validationError("取消加工单必须填写原因");
        }

        ProcessingOrder upd = ProcessingOrder.builder().id(po.getId()).status(target).build();
        OffsetDateTime now = OffsetDateTime.now();
        switch (action) {
            case "issue":
                upd.setIssuedAt(now);
                upd.setProcessor(req.getProcessor());
                upd.setExpectedDeliveryDate(req.getExpectedDeliveryDate());
                break;
            case "start":
                upd.setInProcessingAt(now);
                break;
            case "complete":
                upd.setCompletedAt(now);
                break;
            case "cancel":
                upd.setCancelledAt(now);
                upd.setCancelledReason(req.getReason());
                break;
            default:
                break;
        }
        processingOrderMapper.updateById(upd);

        // 联动：加工单取消（未发货）→ 订单 producing→confirmed 回退（重新可生成加工单）
        if ("cancel".equals(action)) {
            Order order = orderMapper.selectById(po.getOrderId());
            if (order != null && "producing".equals(order.getStatus())) {
                orderService.revertProducingToConfirmed(order.getId(),
                        "加工单 " + po.getProcessingOrderNo() + " 取消，订单回退已确认");
                log.info("加工单取消联动回退订单: po={}, orderId={}", po.getProcessingOrderNo(), order.getId());
            }
        }
        log.info("加工单状态变更: no={}, {} -> {}, operator={}", po.getProcessingOrderNo(), current, target, operator);
        return getDetail(po.getId(), tenantId);
    }

    private String label(String status) {
        return STATUS_LABELS.getOrDefault(status, status);
    }

    private ProcessingOrder resolveProcessingOrder(String rawId, Long tenantId) {
        return processingOrderMapper.selectOne(new LambdaQueryWrapper<ProcessingOrder>()
                .eq(ProcessingOrder::getTenantId, tenantId)
                .eq(ProcessingOrder::getDeleted, 0)
                .and(w -> w.eq(ProcessingOrder::getId, rawId)
                        .or().eq(ProcessingOrder::getProcessingOrderNo, rawId)
                        .or().eq(ProcessingOrder::getOrderId, rawId))
                .last("LIMIT 1"));
    }

    // ============================================================ 查询

    public List<ProcessingOrderResponse> list(String keyword, String status, Long tenantId) {
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
        List<ProcessingOrderResponse> result = new ArrayList<>();
        for (ProcessingOrder po : list) {
            result.add(toResponse(po, tenantId));
        }
        return result;
    }

    public ProcessingOrderResponse getDetail(String rawId, Long tenantId) {
        ProcessingOrder po = resolveProcessingOrder(rawId, tenantId);
        if (po == null) {
            throw BusinessException.notFound("加工单");
        }
        return toResponse(po, tenantId);
    }

    @SuppressWarnings("unchecked")
    private ProcessingOrderResponse toResponse(ProcessingOrder po, Long tenantId) {
        ProcessingOrderResponse resp = new ProcessingOrderResponse();
        resp.setId(po.getId());
        resp.setTenantId(String.valueOf(po.getTenantId()));
        resp.setOrderId(po.getOrderId());
        resp.setProcessingOrderNo(po.getProcessingOrderNo());
        resp.setProcessor(po.getProcessor());
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
        // 订单信息
        Order order = orderMapper.selectById(po.getOrderId());
        if (order != null) {
            resp.setOrderNo(order.getOrderNo());
            resp.setCustomerName(order.getCustomerName());
            resp.setCustomerPhone(order.getCustomerPhone());
        }
        // 快照解析
        if (po.getItemsSnapshot() != null) {
            try {
                resp.setItems(objectMapper.convertValue(po.getItemsSnapshot(),
                        objectMapper.getTypeFactory().constructCollectionType(List.class,
                                ProcessingOrderResponse.ProcessingOrderItemBrief.class)));
            } catch (Exception e) {
                log.warn("加工单快照解析失败: po={}, err={}", po.getProcessingOrderNo(), e.getMessage());
            }
        }
        return resp;
    }

    // ============================================================ 生成结果

    @lombok.Data
    public static class GenerateResult {
        private final String orderRef;
        private final boolean success;
        private final String message;
        private final String processingOrderNo;

        public static GenerateResult ok(String orderRef, String no) {
            return new GenerateResult(orderRef, true, null, no);
        }

        public static GenerateResult fail(String orderRef, String message) {
            return new GenerateResult(orderRef, false, message, null);
        }
    }
}
