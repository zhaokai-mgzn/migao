package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
import com.migao.admin.worker.WorkerIdentity;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Objects;

/**
 * **单据 × 工序**联动（issue #7165，用户 2026-10-17 裁定）。
 *
 * <h3>为什么需要它</h3>
 * <p>路由末道是「发货」（{@code 外帘发货}，1.0 元/套）与「质检」（1.5 元/套）。此前生成发货单 /
 * 录质检判定**只写单据**，不碰 {@code processing_position_operations} ⇒ 有这些工序的加工单永远差
 * 最后一道：工人要再扫一次码才能完工，而发货守卫（{@code OrderShipGuard}）又要求加工单已完成
 * ⇒ 顺序被卡死。本类把「单据生成」与「工序完成」接起来。</p>
 *
 * <h3>口径（唯一实现点）</h3>
 * <ul>
 *   <li><b>只匹配确实存在的工序</b>：发货 = 名称「发货 / 外帘发货」；质检 = 名称「质检」。
 *       没有这些工序的订单**一个字节不变**（不生成、不猜测）。</li>
 *   <li><b>只做未做满的</b>：{@code done_qty < qty}；已满 ⇒ 跳过（重复发货 / 重复录判定幂等）。</li>
 *   <li><b>计件</b>：有工人身份（{@link WorkerIdentity}）⇒ 走
 *       {@link ProductionService#completeByDocument} 的既有报工口径（计件）；无身份 ⇒ 只完成工序、
 *       不计件 —— 用户裁定「工人端记给发货工人；商家/生产端发货不计件」。</li>
 *   <li><b>质检只有合格才联动</b>：返工 / 报废意味着这一件还要再检，不能把「质检」工序置完成；
 *       由调用方（{@link QualityCheckService}）只在 {@code pass} 时调用。</li>
 * </ul>
 *
 * <p>本类**不重算任何数量聚合**、不新造报工口径：完成动作全部委托
 * {@link ProductionService#completeByDocument}。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class DocumentOperationLinkage {

    /** 发货工序的名称集合（路由种子：{@code op-v54-27 外帘发货}；兼容自定义叫「发货」）。 */
    public static final List<String> SHIP_OPERATION_NAMES = List.of("发货", "外帘发货");

    /** 质检工序的名称（路由种子：{@code op-v54-26 质检}）。 */
    public static final String QUALITY_OPERATION_NAME = "质检";

    private final OrderMapper orderMapper;
    private final ProcessingOrderMapper processingOrderMapper;
    private final ProcessingPositionOperationMapper positionOperationMapper;
    private final ProductionService productionService;

    /**
     * 发货单联动：完成该订单活跃加工单上**所有**未做满的发货工序。
     *
     * @param identity 工人端发货人（计件）；{@code null} = 商家/生产端（不计件）
     * @return 本次真正推进的工序数（0 = 无该工序 / 已做完 → 调用方零感知）
     */
    public int completeShippingOperations(Order order, WorkerIdentity identity, Long tenantId) {
        if (order == null || !Objects.equals(order.getTenantId(), tenantId)) {
            return 0;
        }
        return complete(order, null, identity, tenantId, SHIP_OPERATION_NAMES);
    }

    /**
     * 质检单联动：完成**该件成品帘**（{@code order_item_id}）对应的质检工序。
     *
     * <p>只在判定为 {@code pass} 时由调用方触发（返工 / 报废不完成质检工序）。</p>
     *
     * @param identity 工人端质检员（计件）；{@code null} = 观星台员工（不计件）
     * @return 本次真正推进的工序数
     */
    public int completeQualityOperation(String orderId, String orderItemId, WorkerIdentity identity,
                                        Long tenantId) {
        if (orderId == null || orderItemId == null) {
            return 0;
        }
        Order order = orderMapper.selectById(orderId);
        if (order == null || !Objects.equals(order.getTenantId(), tenantId)) {
            return 0;
        }
        return complete(order, orderItemId, identity, tenantId, List.of(QUALITY_OPERATION_NAME));
    }

    /**
     * 「质检」工序**没有报工动作** —— 判定即报工（issue #7186，用户 2026-10-18 逐字：
     * 「质检员不需要报工这个动作，只需要有一个质检动作，完成判定后自动报工，然后自动生成质检流水」）。
     *
     * <p>为什么判据必须落在**服务端写入口**、而不是只把按钮藏起来：报工与判定是两条独立写路径，
     * 先报工会让 {@link #completeQualityOperation} 的「只做未做满的」幂等判据（{@code done_qty >= qty}）
     * 把判定侧的自动报工<b>静默跳过</b> ⇒ 落出「报了工、没判过」的脏行（计件记给了一个没做的动作）；
     * 而按钮藏不藏得住取决于客户端版本（{@code frontend/bmini-app} 今天没有质检面）。
     * ⇒ 服务端 fail-closed，客户端只做体验。</p>
     *
     * <p>返工 / 报废沿用 #7165 口径：判定照落质检流水，但<b>不</b>推进本工序、不计件（还要再检）。</p>
     */
    public static void rejectManualReport(ProcessingPositionOperation op) {
        if (op == null || !QUALITY_OPERATION_NAME.equals(op.getOperationName())) {
            return;
        }
        throw BusinessException.validationError(
                "工序「质检」没有报工动作：请在质检页录入判定（合格 / 返工 / 报废），提交后自动报工并生成质检单",
                List.of(BusinessException.detail("operation_id",
                        "「质检」工序的完成由判定驱动（判定 ≠ 合格不完成，还要再检）")),
                "扫码进入这一件的质检区块 → 选判定（返工 / 报废必填原因）→ 提交；提交即完成报工");
    }

    private static java.math.BigDecimal remainingQty(ProcessingPositionOperation op) {
        java.math.BigDecimal qty = op.getQty() == null ? java.math.BigDecimal.ZERO : op.getQty();
        java.math.BigDecimal done = op.getDoneQty() == null ? java.math.BigDecimal.ZERO : op.getDoneQty();
        return qty.subtract(done);
    }

    private int complete(Order order, String orderItemId, WorkerIdentity identity, Long tenantId,
                         List<String> operationNames) {
        ProcessingOrder po = processingOrderMapper.selectActiveByOrderId(order.getId(), tenantId);
        if (po == null) {
            return 0;
        }
        // 取该加工单的活动工序，匹配/幂等判定在 Java 里做一次（工序数 = 几十条，可读且可测；
        // 不用 SQL 里的名称 IN + done<qty：那会把「匹配哪几道」藏进 SQL 片段，单测只剩 mock 断言）。
        LambdaQueryWrapper<ProcessingPositionOperation> q = new LambdaQueryWrapper<ProcessingPositionOperation>()
                .eq(ProcessingPositionOperation::getProcessingOrderId, po.getId())
                .eq(ProcessingPositionOperation::getTenantId, tenantId)
                .eq(ProcessingPositionOperation::getDeleted, 0)
                .orderByAsc(ProcessingPositionOperation::getSeq);
        int completed = 0;
        for (ProcessingPositionOperation op : positionOperationMapper.selectList(q)) {
            if (!operationNames.contains(op.getOperationName())) {
                continue;
            }
            if (orderItemId != null && !orderItemId.equals(op.getOrderItemId())) {
                continue;
            }
            // 只做「还没做满」的：已满 ⇒ 幂等跳过（重复发货 / 返工后复检都不重复记账）
            if (remainingQty(op).signum() <= 0) {
                continue;
            }
            completed += productionService.completeByDocument(order, po, op, identity, tenantId);
        }
        if (completed > 0) {
            log.info("[单据联动工序] orderNo={}, po={}, 工序={}, 完成 {} 道, 计件={}",
                    order.getOrderNo(), po.getProcessingOrderNo(), operationNames,
                    completed, identity != null ? identity.workerName() : "否（商家/生产端）");
        }
        return completed;
    }
}
