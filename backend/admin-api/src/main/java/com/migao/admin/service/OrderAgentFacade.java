package com.migao.admin.service;

import com.migao.admin.dto.agent.AgentOrderUpdateRequest;
import com.migao.admin.exception.BusinessException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

/**
 * 订单 <b>Agent BFF 编排</b>（issue #8681，P2-1e 第八批）：{@code PATCH /api/admin/agent/orders/{id}}
 * 的 action 路由（status / logistics / payment / cancel / refund）的唯一实现点。
 *
 * <p><b>为什么单开一个类</b>：它是门面里 <b>最后一块真正干活</b>的编排 —— 方法体逐字节搬过来
 * （除下面三条具名的跨类限定），门面 1,142 行随之跌破 800 线的存量豁免带
 * （{@code tests/unit_ci_workflows/loc_ratchet_exemptions.json} 只许缩短 ⇒ 同批销账）。
 * 并回 {@link OrderEntityWriteService}（557 行）或 {@link OrderLifecycleService}（719 行）都会把
 * 承载类推过 <b>800 行</b>的新类登记阈值，而该阈值只许收紧 ⇒ 单开。</p>
 *
 * <h3>搬运口径（行为 diff = 0）</h3>
 * <ul>
 *   <li><b>方法体逐字节搬运</b>，只有三处<b>具名</b>跨类限定：① 解析口径单点在
 *       {@link OrderQueryService#resolveOrderIdToUuid}（本类直连，不再经门面的私有死委托）；
 *       ② 生命周期族直连 {@link OrderLifecycleService}（六个 action 目标）；③ 生命周期入口的
 *       <b>第三参</b>仍是<b>门面实例</b>（建单 / 改单共用的明细装配、取价、库存前置与
 *       {@code batchStock()} 的唯一实现点留 {@code OrderService}，与第五批
 *       {@code createOrder(request, tenantId, orderService)} 同一条既有口径，不重搭第二份）。</li>
 *   <li><b>事务注解逐字跟随</b>：{@code @Transactional(rollbackFor = Exception.class)} 原样随方法搬入 ——
 *       注解只对「经代理的调用」生效，调用方 {@code AgentOrderController} 依赖的正是本 bean 的代理，
 *       事务边界与搬家前同一个（不是「加了嵌套传播」）。</li>
 *   <li><b>不改业务口径</b>：action 白名单、缺参话术、404 文案、发货语义（记物流后流转 shipped）
 *       逐字不变；HTTP 路径 / 入参 / 响应类型一律不变。</li>
 * </ul>
 *
 * <p><b>不搬（有意）</b>：{@code createOrderForAgent} 的实现体本就在
 * {@link OrderCreationService#createOrderForAgent}（本批只退休门面的同名转发，调用方直连实现点，
 * 与第五批 {@code createOrder} 同一条口径）；{@code applyRollAllocation} /
 * {@code batchStock()} 访问器一字未动（前者被 {@code OrderRollAllocationAuthorityTest} 钉在门面，
 * 后者取消路径在用）。</p>
 *
 * <p><b>看管</b>：本类的入口不许被改回门面、{@code src/test} 全树也不许再经门面驱动它 ——
 * 判据 = {@code OrderFacadeForwarderRetirementTest}。复算：
 * {@code cd backend/admin-api && ./mvnw -Dtest=OrderFacadeForwarderRetirementTest test}。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class OrderAgentFacade {

    /**
     * 共享部件的<b>唯一实现点</b>（明细装配 / 取价 / 总额 / 库存前置 / 批次台账访问器）：
     * 本类只把它当成生命周期入口的第三参转手，绝不复制口径（见类注释第 ③ 条）。
     */
    private final OrderService orderService;
    /** 生命周期族唯一实现点（六个 action 的落地处）。 */
    private final OrderLifecycleService orderLifecycleService;
    /** 查询 / 单号解析的唯一实现点（{@code resolveOrderIdToUuid} + 每次 action 后的回读）。 */
    private final OrderQueryService orderQueryService;

    /**
     * Agent 专用统一订单更新。
     * ID 可传 UUID 或订单号（ORD-xxx），服务端自动解析。
     * 通过 action 字段路由到具体的操作方法。
     */
    @Transactional(rollbackFor = Exception.class)
    public Object updateOrderForAgent(String rawId, AgentOrderUpdateRequest request, Long tenantId) {
        // 解析订单 ID
        String resolvedId = orderQueryService.resolveOrderIdToUuid(rawId, tenantId);
        if (resolvedId == null) {
            throw new BusinessException("ORDER_NOT_FOUND",
                    "无法找到订单：" + rawId + "。请使用 order_query 查询正确的订单号后重试。", 404);
        }

        String action = request.getAction();
        if (!StringUtils.hasText(action)) {
            throw BusinessException.validationError("action 不能为空");
        }

        return switch (action) {
            case "update_status" -> {
                if (!StringUtils.hasText(request.getStatus())) {
                    throw BusinessException.validationError("status 不能为空");
                }
                orderLifecycleService.updateOrderStatus(resolvedId, request.getStatus(), orderService);
                yield orderQueryService.getOrderById(resolvedId);
            }
            case "confirm_payment" -> {
                orderLifecycleService.confirmPayment(resolvedId);
                yield orderQueryService.getOrderById(resolvedId);
            }
            case "cancel" -> {
                orderLifecycleService.cancelOrder(resolvedId, request.getCancelReason(), orderService);
                yield orderQueryService.getOrderById(resolvedId);
            }
            case "refund" -> {
                orderLifecycleService.refundOrder(resolvedId, request.getRefundAmount(), request.getRefundReason());
                yield orderQueryService.getOrderById(resolvedId);
            }
            case "update_logistics" -> {
                if (!StringUtils.hasText(request.getLogisticsCompany())) {
                    throw BusinessException.validationError("logisticsCompany 不能为空");
                }
                if (!StringUtils.hasText(request.getTrackingNumber())) {
                    throw BusinessException.validationError("trackingNumber 不能为空");
                }
                orderLifecycleService.upsertLogistics(resolvedId, request.getLogisticsCompany().trim(),
                        request.getTrackingNumber().trim(), null, request.getLogisticsType());
                // 发货语义：记录物流后将订单流转为 shipped（与契约 order_manage(update_logistics) 可发货一致）
                orderLifecycleService.shipOrderIfApplicable(resolvedId);
                yield orderQueryService.getOrderById(resolvedId);
            }
            default -> throw BusinessException.validationError(
                    "不支持的操作类型: " + action + "，可选: update_status/update_logistics/confirm_payment/cancel/refund");
        };
    }
}
