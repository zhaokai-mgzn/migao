package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.migao.admin.dto.ReworkOrderView;
import com.migao.admin.entity.AfterSalesTicket;
import com.migao.admin.entity.ReworkOrder;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.AfterSalesTicketMapper;
import com.migao.admin.mapper.ReworkOrderMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.util.List;

/**
 * 返工单（issue #7377，P1-5 段 2）：售后 → 返工 → 完成回写。
 *
 * <h3>闭环唯一（issue 判据）</h3>
 * <p>「不得出现『已闭环但返工单还在做』」靠三道闸：</p>
 * <ol>
 *   <li>开单时售后单**未完结**（closed/resolved/rejected 一律拒）；</li>
 *   <li>同一售后单**同时只有一个未完结返工单**（部分唯一索引 + 服务层先查给可读提示）；</li>
 *   <li>完成后**只从 processing 推进到 resolved**（其它状态不动 —— 回写不得覆盖别人的结论）。</li>
 * </ol>
 *
 * <h3>状态流转走 CAS</h3>
 * <p>start / complete / cancel 都以「当前状态」为条件更新，按影响行数判成败 ——
 * 两个人同时点「完成」不会都成功。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ReworkOrderService {

    /** 来源词表（与迁移 V199 的 CHECK 约束逐字同名）。 */
    public static final String SOURCE_AFTER_SALES = "after_sales";
    public static final String SOURCE_WORKER = "worker";

    private final ReworkOrderMapper reworkOrderMapper;
    private final AfterSalesTicketMapper afterSalesTicketMapper;
    private final com.migao.admin.time.BusinessClock businessClock;

    /**
     * 读面补「加工单号 / 订单号」（issue #7860）—— 用字段注入而**不加**构造参数：
     * {@code @RequiredArgsConstructor} 的构造签名被既有单测直接装配，加参数会让那些测试红；
     * 而这两个 mapper 只喂**展示字段**，缺接线时降级成「不显示编号」比让整条读面炸掉更合理
     * （读面零业务副作用，编号不是任何判据的输入）。
     */
    @org.springframework.beans.factory.annotation.Autowired(required = false)
    private com.migao.admin.mapper.ProcessingOrderMapper processingOrderMapper;

    @org.springframework.beans.factory.annotation.Autowired(required = false)
    private com.migao.admin.mapper.OrderMapper orderMapper;

    /**
     * 站内通知（issue #7860 用户追加要求：「新增返工单需要产生通知消息」）。
     *
     * <p>🔴 <b>fail-soft</b>（与入库通知同一取舍）：通知是「事实之后的追加」，不是事实的一部分 ——
     * 未注入（切片单测 / 老上下文）或发送异常都只留痕，**绝不**把已经落库的返工单回滚，
     * 也不改调用方返回值。幂等由 `NotificationService` 的 `eventType:bizId:recipientId` 去重键兜住。</p>
     */
    @org.springframework.beans.factory.annotation.Autowired(required = false)
    NotificationService notificationService;

    /** 从售后单开返工单。 */
    @Transactional
    public ReworkOrderView create(String afterSalesTicketId, String reason, String processingOrderId,
                                  ApprovalService.Operator operator) {
        if (afterSalesTicketId == null || afterSalesTicketId.isBlank()) {
            throw BusinessException.validationError("必须指定售后工单");
        }
        AfterSalesTicket ticket = afterSalesTicketMapper.selectById(afterSalesTicketId);
        if (ticket == null) {
            throw BusinessException.notFound("售后工单");
        }
        if (!ReworkState.canOpenFor(ticket.getStatus())) {
            throw BusinessException.validationError(String.format(
                    "售后工单当前是「%s」，已闭环/已驳回的工单不能再开返工", ticket.getStatus()));
        }
        ReworkOrder open = findOpenForTicket(afterSalesTicketId);
        if (open != null) {
            throw BusinessException.validationError(String.format(
                    "这张售后单已有未完结的返工单（%s），请先完成或取消它", open.getReworkNo()));
        }

        ReworkOrder order = ReworkOrder.builder()
                .tenantId(ticket.getTenantId())
                .reworkNo(nextReworkNo())
                .afterSalesTicketId(afterSalesTicketId)
                .source(SOURCE_AFTER_SALES)
                .orderId(ticket.getOrderId())
                .processingOrderId(processingOrderId)
                .status(ReworkState.DRAFT)
                .reason(reason)
                .createdBy(operator == null ? null : operator.userId())
                .createdByName(operator == null ? null : operator.displayName())
                .build();
        try {
            reworkOrderMapper.insert(order);
        } catch (org.springframework.dao.DuplicateKeyException duplicate) {
            // 并发下两张单同时开（部分唯一索引兜住）⇒ 可读冲突，不是 5xx
            throw BusinessException.validationError("这张售后单刚有另一个返工单被开出来，请刷新后处理那一个");
        }
        log.info("[rework] 开单 | no={} ticket={}", order.getReworkNo(), afterSalesTicketId);
        ReworkOrderView created = view(order);
        notifyCreated(order, created);
        return created;
    }

    /** 开工（draft → in_progress）。 */
    @Transactional
    public ReworkOrderView start(String reworkId) {
        ReworkOrder order = require(reworkId);
        if (!ReworkState.canStart(order.getStatus())) {
            throw BusinessException.validationError(String.format(
                    "返工单当前是「%s」，不能开工", order.getStatus()));
        }
        casStatus(reworkId, ReworkState.DRAFT, ReworkState.IN_PROGRESS,
                w -> w.set(ReworkOrder::getStartedAt, OffsetDateTime.now()));
        return view(require(reworkId));
    }

    /**
     * 完成（in_progress → done）+ **回写售后状态**。
     *
     * <p>回写规则：售后单当前是 `processing` ⇒ 推进到 `resolved`；其它状态**不动**
     * （pending 还没处理完、closed 已闭环、rejected 已驳回 —— 覆盖它们等于替别人下结论）。</p>
     */
    @Transactional
    public ReworkOrderView complete(String reworkId) {
        ReworkOrder order = require(reworkId);
        if (!ReworkState.canComplete(order.getStatus())) {
            throw BusinessException.validationError(String.format(
                    "返工单当前是「%s」，只有进行中的才能完成（未开工就完成 = 跳过返工）", order.getStatus()));
        }
        casStatus(reworkId, ReworkState.IN_PROGRESS, ReworkState.DONE,
                w -> w.set(ReworkOrder::getCompletedAt, OffsetDateTime.now()));

        AfterSalesTicket ticket = afterSalesTicketMapper.selectById(order.getAfterSalesTicketId());
        String next = ticket == null ? null : ReworkState.writeBackTicketStatus(ticket.getStatus());
        if (next != null) {
            afterSalesTicketMapper.update(null, new LambdaUpdateWrapper<AfterSalesTicket>()
                    .eq(AfterSalesTicket::getId, ticket.getId())
                    .eq(AfterSalesTicket::getStatus, ticket.getStatus())   // CAS：别人先改过就不覆盖
                    .set(AfterSalesTicket::getStatus, next));
            log.info("[rework] 完成并回写售后 | rework={} ticket={} {} -> {}",
                    order.getReworkNo(), ticket.getId(), ticket.getStatus(), next);
        } else {
            log.info("[rework] 完成（售后状态不动） | rework={} ticketStatus={}",
                    order.getReworkNo(), ticket == null ? "missing" : ticket.getStatus());
        }
        return view(require(reworkId));
    }

    /** 取消（未完结 → cancelled）。取消**不回退**售后状态。 */
    @Transactional
    public ReworkOrderView cancel(String reworkId) {
        ReworkOrder order = require(reworkId);
        if (!ReworkState.canCancel(order.getStatus())) {
            throw BusinessException.validationError(String.format(
                    "返工单当前是「%s」，已完结的不能取消", order.getStatus()));
        }
        casStatus(reworkId, order.getStatus(), ReworkState.CANCELLED, w -> {
        });
        return view(require(reworkId));
    }

    /**
     * **车间工人报返工 ⇒ 开一张 {@code source='worker'} 的返工单**（issue #7860）。
     *
     * <p>用户 2026-10-26 逐字：「报返工的那个工序不能计件的，只报返工，生成返工单，
     * pc端的返工单列表要能看到这次的返工数据」。</p>
     *
     * <p>🔴 与 {@link #create}（售后开单）的差别只有「挂在哪」：车间返工没有售后单，
     * 所以 {@code after_sales_ticket_id} 落 {@code NULL}，责任留痕改挂
     * 「报工人 + 工序 + 数量 + 被改记的那一笔报工行」。状态机与完成回写规则**一字不动**
     * （{@code complete()} 对无售后单的行什么都不回写 —— 那条分支本就有 null 守卫）。</p>
     *
     * <p>调用方 = {@code ProductionReworkService}（同一事务：改记报工 + 回退进度 + 开单要么全成要么全不成）。</p>
     */
    @Transactional
    public ReworkOrderView createWorkerRework(Long tenantId, String orderId, String processingOrderId,
                                              String operationId, String operationName, java.math.BigDecimal qty,
                                              String reason, String workerId, String workerName, String workLogId) {
        return createWorkerRework(tenantId, orderId, processingOrderId, operationId, operationName, qty,
                reason, workerId, workerName, workLogId, null, null, null, null);
    }

    /**
     * 车间报返工开单（带**件定位键**，issue #7945）。
     *
     * @param orderItemId   部位行（一件成品帘的「部位」半边）—— {@code null} = 指不出件（不猜）
     * @param setId         套 id（件的「套」半边）
     * @param setNo         套号快照
     * @param positionName  部位展示名快照
     */
    @Transactional
    public ReworkOrderView createWorkerRework(Long tenantId, String orderId, String processingOrderId,
                                              String operationId, String operationName, java.math.BigDecimal qty,
                                              String reason, String workerId, String workerName, String workLogId,
                                              String orderItemId, String setId, String setNo, String positionName) {
        ReworkOrder order = ReworkOrder.builder()
                .tenantId(tenantId)
                .reworkNo(nextReworkNo())
                .source(SOURCE_WORKER)
                .orderId(orderId)
                .processingOrderId(processingOrderId)
                .operationId(operationId)
                .operationName(operationName)
                .orderItemId(orderItemId)
                .setId(setId)
                .setNo(setNo)
                .positionName(positionName)
                .qty(qty)
                .workerId(workerId)
                .workerName(workerName)
                .workLogId(workLogId)
                .status(ReworkState.DRAFT)
                .reason(reason)
                .createdBy(workerId)
                .createdByName(workerName)
                .build();
        try {
            reworkOrderMapper.insert(order);
        } catch (org.springframework.dao.DuplicateKeyException duplicate) {
            // 件级部分唯一索引（uk_rework_orders_open_per_piece）兜住：同一件只能有一张未完结车间返工单
            throw BusinessException.validationError(StringUtils.hasText(setNo) && StringUtils.hasText(orderItemId)
                    ? String.format("这一件（%s · 部位 %s）已有未完结的返工单，请先处理那一张",
                            setNo, StringUtils.hasText(positionName) ? positionName : orderItemId)
                    : "这一件刚有另一个返工单被开出来，请刷新后处理那一张");
        }
        log.info("[rework] 车间报返工 | no={} po={} op={} set={} item={} qty={}",
                order.getReworkNo(), processingOrderId, operationName, setNo, orderItemId, qty);
        ReworkOrderView created = view(order);
        notifyCreated(order, created);
        return created;
    }

    /** 列表（最新在前；可按售后单过滤）。 */
    public List<ReworkOrderView> list(String afterSalesTicketId) {
        LambdaQueryWrapper<ReworkOrder> wrapper = new LambdaQueryWrapper<ReworkOrder>()
                .orderByDesc(ReworkOrder::getCreatedAt);
        if (afterSalesTicketId != null && !afterSalesTicketId.isBlank()) {
            wrapper.eq(ReworkOrder::getAfterSalesTicketId, afterSalesTicketId);
        }
        return reworkOrderMapper.selectList(wrapper).stream().map(this::view).toList();
    }

    /** 详情。 */
    public ReworkOrderView detail(String reworkId) {
        return view(require(reworkId));
    }

    private ReworkOrder findOpenForTicket(String ticketId) {
        List<ReworkOrder> rows = reworkOrderMapper.selectList(new LambdaQueryWrapper<ReworkOrder>()
                .eq(ReworkOrder::getAfterSalesTicketId, ticketId)
                .in(ReworkOrder::getStatus, ReworkState.DRAFT, ReworkState.IN_PROGRESS));
        return rows.isEmpty() ? null : rows.get(0);
    }

    private void casStatus(String reworkId, String from, String to,
                           java.util.function.Consumer<LambdaUpdateWrapper<ReworkOrder>> extras) {
        LambdaUpdateWrapper<ReworkOrder> wrapper = new LambdaUpdateWrapper<ReworkOrder>()
                .eq(ReworkOrder::getId, reworkId)
                .eq(ReworkOrder::getStatus, from)
                .set(ReworkOrder::getStatus, to)
                .set(ReworkOrder::getUpdatedAt, OffsetDateTime.now());
        extras.accept(wrapper);
        if (reworkOrderMapper.update(null, wrapper) == 0) {
            throw BusinessException.validationError("这张返工单刚刚被别人改了状态，请刷新后重试");
        }
    }

    private ReworkOrder require(String reworkId) {
        ReworkOrder order = reworkOrderMapper.selectById(reworkId);
        if (order == null) {
            throw BusinessException.notFound("返工单");
        }
        return order;
    }

    /**
     * 新增返工单 ⇒ 给租户管理员的**站内通知**（issue #7860，用户逐字「新增返工单需要产生通知消息」）。
     *
     * <p>两个来源同一句话，只在 {@code sourceText} 上区分（售后判定 / 车间报返工）——
     * 收件人看到的是「哪张单、哪道工序、多少、为什么」，据此决定派谁去做。</p>
     *
     * <p>🔴 落地页 = `/rework-orders`（PC「返工单」列表，本单新增的来源/工序/数量列就在那一页）。</p>
     */
    private void notifyCreated(ReworkOrder order, ReworkOrderView created) {
        if (notificationService == null) {
            return;
        }
        try {
            java.util.Map<String, String> vars = new java.util.HashMap<>();
            vars.put("reworkNo", created.getReworkNo() == null ? "" : created.getReworkNo());
            vars.put("processingOrderNo", created.getProcessingOrderNo() == null
                    ? "（未关联加工单）" : created.getProcessingOrderNo());
            vars.put("operationName", created.getOperationName() == null ? "（未指定工序）" : created.getOperationName());
            vars.put("qtyText", created.getQty() == null
                    ? "" : "返工数量 " + created.getQty().stripTrailingZeros().toPlainString());
            vars.put("reason", created.getReason() == null ? "（未填原因）" : created.getReason());
            vars.put("sourceText", SOURCE_WORKER.equals(order.getSource()) ? "车间报返工" : "售后判定要返工");
            notificationService.triggerForTenantAdmins(order.getTenantId(), "rework_order_created", vars,
                    com.migao.admin.dto.NotificationEvent.builder()
                            .bizType("rework_order")
                            .bizId(order.getId())
                            .bizNo(created.getReworkNo())
                            .targetPath("/rework-orders")
                            .severity("warn")
                            .occurredAt(OffsetDateTime.now())
                            .build());
        } catch (Exception e) {
            log.warn("[rework] 返工单通知发送失败（已忽略，不影响单据事实）: no={}, error={}",
                    order.getReworkNo(), e.getMessage());
        }
    }

    private ReworkOrderView view(ReworkOrder order) {
        ReworkOrderView view = ReworkOrderView.builder()
                .id(order.getId())
                .reworkNo(order.getReworkNo())
                .afterSalesTicketId(order.getAfterSalesTicketId())
                .orderId(order.getOrderId())
                .processingOrderId(order.getProcessingOrderId())
                .source(order.getSource() == null ? SOURCE_AFTER_SALES : order.getSource())
                .operationName(order.getOperationName())
                .orderItemId(order.getOrderItemId())
                .setId(order.getSetId())
                .setNo(order.getSetNo())
                .positionName(order.getPositionName())
                .qty(order.getQty())
                .workerName(order.getWorkerName())
                .status(order.getStatus())
                .reason(order.getReason())
                .createdByName(order.getCreatedByName())
                .startedAt(order.getStartedAt())
                .completedAt(order.getCompletedAt())
                .build();
        enrichNos(view, order);
        return view;
    }

    /** 展示用编号（issue #7860）：取不到 ⇒ 保持 null（界面渲染 —）。逐行单查：本读面是**单页列表**。 */
    private void enrichNos(ReworkOrderView view, ReworkOrder order) {
        if (processingOrderMapper != null && order.getProcessingOrderId() != null) {
            com.migao.admin.entity.ProcessingOrder po =
                    processingOrderMapper.selectById(order.getProcessingOrderId());
            view.setProcessingOrderNo(po == null ? null : po.getProcessingOrderNo());
        }
        if (orderMapper != null && order.getOrderId() != null) {
            com.migao.admin.entity.Order salesOrder = orderMapper.selectById(order.getOrderId());
            view.setOrderNo(salesOrder == null ? null : salesOrder.getOrderNo());
        }
    }

    /** 单号：RG + 业务日期 + 4 位随机（同租户唯一索引兜底）。 */
    private String nextReworkNo() {
        String day = businessClock.today().format(DateTimeFormatter.ofPattern("yyyyMMdd"));
        int suffix = (int) (Math.random() * 9000) + 1000;
        return "RG" + day + suffix;
    }
}
