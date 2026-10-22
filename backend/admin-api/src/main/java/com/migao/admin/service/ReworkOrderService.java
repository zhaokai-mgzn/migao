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

    private final ReworkOrderMapper reworkOrderMapper;
    private final AfterSalesTicketMapper afterSalesTicketMapper;
    private final com.migao.admin.time.BusinessClock businessClock;

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
        return view(order);
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

    private ReworkOrderView view(ReworkOrder order) {
        return ReworkOrderView.builder()
                .id(order.getId())
                .reworkNo(order.getReworkNo())
                .afterSalesTicketId(order.getAfterSalesTicketId())
                .orderId(order.getOrderId())
                .processingOrderId(order.getProcessingOrderId())
                .status(order.getStatus())
                .reason(order.getReason())
                .createdByName(order.getCreatedByName())
                .startedAt(order.getStartedAt())
                .completedAt(order.getCompletedAt())
                .build();
    }

    /** 单号：RG + 业务日期 + 4 位随机（同租户唯一索引兜底）。 */
    private String nextReworkNo() {
        String day = businessClock.today().format(DateTimeFormatter.ofPattern("yyyyMMdd"));
        int suffix = (int) (Math.random() * 9000) + 1000;
        return "RG" + day + suffix;
    }
}
