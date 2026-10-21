package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.migao.admin.dto.ApprovalRequest;
import com.migao.admin.dto.ApprovalView;
import com.migao.admin.entity.Approval;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ApprovalMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;

/**
 * 具名审批（issue #7374，P1-2 段 1）：申请 / 通过 / 驳回 / 撤回 / **单次消费**。
 *
 * <h3>三条纪律</h3>
 * <ol>
 *   <li><b>状态流转走 CAS</b>：更新语句带 {@code status = 'pending'} 条件，按影响行数判成败 ——
 *       两个人同时点「通过」不会都成功（否则同一条审批会留两个裁决人）；</li>
 *   <li><b>业务对象不存结论副本</b>：需要审批的一方按 {@code objectType + objectRef} 读本表；</li>
 *   <li><b>批一次用一次</b>：{@link #consume} 也是 CAS（{@code consumed_at IS NULL} 才更新），
 *       并发下只有一个请求能吃到这条审批。</li>
 * </ol>
 *
 * <h3>谁能批</h3>
 * <p>本段只要求「有权限码 + 不是自己批自己」：申请人不能批自己提交的那条（`requestedBy == 决策人` ⇒ 拒）。
 * 多级会签 / 金额分级授权是 issue 明列的非目标。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ApprovalService {

    private final ApprovalMapper approvalMapper;

    /**
     * 提交申请。
     *
     * @param request 类型 + 对象 + 金额 + 理由（{@code objectType} 必须是五类之一，表上还有 CHECK 兜底）
     * @param operator 申请人（id / 显示名）
     */
    @Transactional
    public ApprovalView submit(ApprovalRequest request, Operator operator) {
        requireKnownType(request.getObjectType());
        if (request.getObjectRef() == null || request.getObjectRef().isBlank()) {
            throw BusinessException.validationError("审批必须指明对象（objectRef 不能为空）");
        }
        // 同一对象同一类型只允许一个待审（部分唯一索引兜底；这里先给出可读提示）
        Approval pending = findPending(request.getObjectType(), request.getObjectRef());
        if (pending != null) {
            throw BusinessException.validationError(String.format(
                    "这个对象已经有一条待审申请（%s），请先等裁决或撤回它", pending.getId()));
        }

        // 金额精度准入（issue #6228）：审批金额是「批了多少钱」的凭据，超精度不静默四舍五入
        BigDecimal approvedAmount = MoneyScale.requireTwoDecimalsOrNull(request.getAmount(), "审批金额");

        Approval approval = Approval.builder()
                .tenantId(request.getTenantId())
                .objectType(request.getObjectType())
                .objectRef(request.getObjectRef().trim())
                .objectLabel(request.getObjectLabel())
                .amount(approvedAmount)
                .payload(request.getPayload())
                .reason(request.getReason())
                .status(ApprovalState.initialStatus())
                .requestedBy(operator == null ? null : operator.userId())
                .requestedByName(operator == null ? null : operator.displayName())
                .requestedAt(OffsetDateTime.now())
                .build();
        try {
            approvalMapper.insert(approval);
        } catch (org.springframework.dao.DuplicateKeyException duplicate) {
            // 并发下两个请求同时提交同一对象（部分唯一索引 uk_approvals_pending 兜住）
            // ⇒ 映射成可读冲突，而不是把 5xx 冒给申请人（台账 unique_write_ledger 记这一处）
            throw BusinessException.validationError(
                    "这个对象刚有另一条待审申请被提交，请刷新后处理那一条");
        }
        log.info("[approval] 提交 | type={} ref={} amount={} by={}",
                approval.getObjectType(), approval.getObjectRef(), approval.getAmount(),
                approval.getRequestedBy());
        return ApprovalView.of(approval);
    }

    /** 通过 / 驳回（只对待审生效；申请人不能批自己的单）。 */
    @Transactional
    public ApprovalView decide(String approvalId, boolean approve, String note, Operator operator) {
        Approval approval = require(approvalId);
        if (!ApprovalState.canDecide(approval.getStatus())) {
            throw BusinessException.validationError(String.format(
                    "这条审批已经是「%s」，不能再裁决", statusLabel(approval.getStatus())));
        }
        if (operator != null && operator.userId() != null
                && operator.userId().equals(approval.getRequestedBy())) {
            throw BusinessException.validationError("不能审批自己提交的申请（换一个有审批权的人）");
        }
        String status = approve ? ApprovalState.APPROVED : ApprovalState.REJECTED;
        int updated = approvalMapper.update(null, new LambdaUpdateWrapper<Approval>()
                .eq(Approval::getId, approvalId)
                .eq(Approval::getStatus, ApprovalState.PENDING)   // CAS：并发下只一个能成功
                .set(Approval::getStatus, status)
                .set(Approval::getDecidedBy, operator == null ? null : operator.userId())
                .set(Approval::getDecidedByName, operator == null ? null : operator.displayName())
                .set(Approval::getDecidedAt, OffsetDateTime.now())
                .set(Approval::getDecisionNote, note)
                .set(Approval::getUpdatedAt, OffsetDateTime.now()));
        if (updated == 0) {
            // 走到这里说明并发下别人先裁决了（CAS 落空）⇒ 409 语义，不覆盖别人的结论
            throw BusinessException.validationError("这条审批刚刚被别人裁决了，请刷新后查看结果");
        }
        log.info("[approval] 裁决 | id={} status={} by={}", approvalId, status,
                operator == null ? null : operator.userId());
        return ApprovalView.of(require(approvalId));
    }

    /** 撤回（只有申请人本人、且仍是待审）。 */
    @Transactional
    public ApprovalView withdraw(String approvalId, Operator operator) {
        Approval approval = require(approvalId);
        if (!ApprovalState.canWithdraw(approval.getStatus())) {
            throw BusinessException.validationError(String.format(
                    "这条审批已经是「%s」，不能撤回", statusLabel(approval.getStatus())));
        }
        if (operator != null && operator.userId() != null
                && !operator.userId().equals(approval.getRequestedBy())) {
            throw BusinessException.validationError("只有申请人本人能撤回自己的申请");
        }
        int updated = approvalMapper.update(null, new LambdaUpdateWrapper<Approval>()
                .eq(Approval::getId, approvalId)
                .eq(Approval::getStatus, ApprovalState.PENDING)
                .set(Approval::getStatus, ApprovalState.WITHDRAWN)
                .set(Approval::getUpdatedAt, OffsetDateTime.now()));
        if (updated == 0) {
            throw BusinessException.validationError("这条审批刚刚被裁决了，不能撤回");
        }
        return ApprovalView.of(require(approvalId));
    }

    /**
     * **单次消费**：找到「该对象 + 该类型 + 已通过 + 未用掉 + 金额足够」的那条并标记已用。
     *
     * @return 被消费的审批 id；{@code null} = 没有可用的审批（调用方据此拒绝）
     */
    @Transactional
    public String consume(String objectType, String objectRef, BigDecimal requiredAmount,
                          String consumedRef) {
        List<Approval> candidates = approvalMapper.selectList(new LambdaQueryWrapper<Approval>()
                .eq(Approval::getObjectType, objectType)
                .eq(Approval::getObjectRef, objectRef)
                .eq(Approval::getStatus, ApprovalState.APPROVED)
                .isNull(Approval::getConsumedAt)
                .orderByAsc(Approval::getDecidedAt));
        for (Approval candidate : candidates) {
            // 金额必须覆盖本次动作（批了 5000 不能用来过 8000 的单）；没写金额的审批视为不限额
            if (candidate.getAmount() != null && requiredAmount != null
                    && candidate.getAmount().compareTo(requiredAmount) < 0) {
                continue;
            }
            int updated = approvalMapper.update(null, new LambdaUpdateWrapper<Approval>()
                    .eq(Approval::getId, candidate.getId())
                    .isNull(Approval::getConsumedAt)          // CAS：并发下只一个能吃到
                    .set(Approval::getConsumedAt, OffsetDateTime.now())
                    .set(Approval::getConsumedRef, consumedRef)
                    .set(Approval::getUpdatedAt, OffsetDateTime.now()));
            if (updated > 0) {
                log.info("[approval] 消费 | id={} type={} ref={} amount={} used_for={}",
                        candidate.getId(), objectType, objectRef, requiredAmount, consumedRef);
                return candidate.getId();
            }
        }
        return null;
    }

    /**
     * 回填「这条审批用在哪」（消费时业务对象可能还没 id —— 下单闸门在下单**之前**跑）。
     *
     * <p>只更新 {@code consumed_ref}，不动状态：消费已经发生，这里只是把去向补齐（留痕完整性）。</p>
     */
    @Transactional
    public void attachConsumedRef(String approvalId, String consumedRef) {
        if (approvalId == null || consumedRef == null) {
            return;
        }
        approvalMapper.update(null, new LambdaUpdateWrapper<Approval>()
                .eq(Approval::getId, approvalId)
                .isNotNull(Approval::getConsumedAt)
                .set(Approval::getConsumedRef, consumedRef)
                .set(Approval::getUpdatedAt, OffsetDateTime.now()));
    }

    /** 列表（按类型 / 状态过滤；最新在前）。 */
    public List<ApprovalView> list(String objectType, String status) {
        LambdaQueryWrapper<Approval> wrapper = new LambdaQueryWrapper<Approval>()
                .orderByDesc(Approval::getRequestedAt);
        if (objectType != null && !objectType.isBlank()) {
            wrapper.eq(Approval::getObjectType, objectType);
        }
        if (status != null && !status.isBlank()) {
            wrapper.eq(Approval::getStatus, status);
        }
        return approvalMapper.selectList(wrapper).stream().map(ApprovalView::of).toList();
    }

    /** 单条（详情面 / 争论时看「谁在什么时候改成了什么」）。 */
    public ApprovalView view(String approvalId) {
        return ApprovalView.of(require(approvalId));
    }

    /** 供闸门反查：「这个对象有没有待审申请」——有则错误提示要能指路。 */
    public Approval findPending(String objectType, String objectRef) {
        List<Approval> rows = approvalMapper.selectList(new LambdaQueryWrapper<Approval>()
                .eq(Approval::getObjectType, objectType)
                .eq(Approval::getObjectRef, objectRef)
                .eq(Approval::getStatus, ApprovalState.PENDING));
        return rows.isEmpty() ? null : rows.get(0);
    }

    private Approval require(String approvalId) {
        Approval approval = approvalMapper.selectById(approvalId);
        if (approval == null) {
            throw BusinessException.notFound("审批");
        }
        return approval;
    }

    private static void requireKnownType(String objectType) {
        if (!List.of(Approval.TYPE_CREDIT_OVERRIDE, Approval.TYPE_PRICE_CHANGE, Approval.TYPE_REFUND,
                Approval.TYPE_PURCHASE_OVER, Approval.TYPE_STOCKTAKE_DIFF).contains(objectType)) {
            throw BusinessException.validationError(
                    "审批类型必须是 credit_override / price_change / refund / purchase_over / stocktake_diff 之一");
        }
    }

    private static String statusLabel(String status) {
        return switch (status) {
            case ApprovalState.PENDING -> "待审";
            case ApprovalState.APPROVED -> "已通过";
            case ApprovalState.REJECTED -> "已驳回";
            case ApprovalState.WITHDRAWN -> "已撤回";
            default -> status;
        };
    }

    /** 操作人（id + 显示名）：只从服务端安全上下文取，不接受客户端递交。 */
    public record Operator(String userId, String displayName) {
    }
}
