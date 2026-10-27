package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.entity.ProductionWorkLog;
import com.migao.admin.entity.ReworkOrder;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
import com.migao.admin.mapper.ProductionWorkLogMapper;
import com.migao.admin.mapper.ReworkOrderMapper;
import com.migao.admin.worker.WorkerIdentity;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 工人报返工（issue #7860，用户 2026-10-26 裁定）。
 *
 * <h3>口径（用户逐字）</h3>
 * <ul>
 *   <li>「质检不能绑定死打包工序，需要允许任一工序工人报返工」——报返工**不看**打包工序、
 *       也**不看**工人档案里的 {@code inspect} 页；准入 = 有效工人 session；</li>
 *   <li>「报返工的那个工序不能计件的，只报返工，生成返工单」——这一笔**不计件**；</li>
 *   <li>「把刚自动记的那一笔改记为返工（回退进度与计件）」——用户在同日追问里明确选了「改记」
 *       而不是「另记一笔」。</li>
 * </ul>
 *
 * <h3>一次报返工做的四件事（同一事务：要么全成，要么全不成）</h3>
 * <ol>
 *   <li><b>改记报工明细</b>：把这件这道工序、这位工人**最近一笔 {@code normal}** 报工改成
 *       {@code work_type='rework'} 且 {@code qualified_qty=0}。计件聚合只算 {@code normal}
 *       （{@code ProductionService.aggregate} 的既有口径）⇒ 这一笔**自然不再计件**，不需要另算一次钱。
 *       明细**不删**（连同单价快照一起留痕，改的是分类而不是事实）；</li>
 *   <li><b>回退进度</b>：{@code done_qty} 减掉该笔的合格数、{@code done_at} 清空、状态回 {@code pending}
 *       （CAS：读到的旧值不成立 ⇒ 409，绝不静默覆盖别人的提交）；</li>
 *   <li><b>重开加工单</b>：回退后若不再全绿，{@code completed → in_processing}
 *       （否则「单子已完工、工序却没做满」自相矛盾）；</li>
 *   <li><b>生成返工单</b>：{@code source='worker'} 的一行（PC「返工单」列表可见）。</li>
 * </ol>
 *
 * <h3>🔴 为什么改记是「最近一笔 normal」而不是让客户端传 id</h3>
 * <p>工人是「扫完码发现这件不对」——手上没有报工流水号。服务端按
 * (租户, 加工单, 工序, 工人) 取本人最近一笔 {@code normal}：这是**唯一**能自动化的、又不会改到别人账上的锚点
 * （工人只可能改记自己刚报的那一笔；别人的报工一行都碰不到）。每次改记消费一笔 {@code normal}
 * ⇒ 同一笔不会被改两次（第二道保险 = {@code UPDATE ... WHERE work_type='normal'} 的 CAS）。</p>
 *
 * <h3>边界（照实登记）</h3>
 * <ul>
 *   <li><b>成品入库不因返工自动回退</b>：打包已生成的成品入库单是库存事实，回退属「撤销入库」动线
 *       （商家侧），本服务一个字都不碰库存；</li>
 *   <li>被改记的那一笔如果是「领活」时写的（{@code started_at} / {@code worker_id} 已落），
 *       这两列**保留** —— 返工改的是「这块布算不算做出来了」，不是「谁领的活」；</li>
 *   <li>报工明细「不可变」在本仓出现**唯一**例外：同日用户裁定「改记」。可改的列只有
 *       {@code work_type} / {@code qualified_qty}，数量、单价快照、报工人一律不动。</li>
 * </ul>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ProductionReworkService {

    /**
     * 幂等端点标识（诊断用；与 Controller 路径逐字一致 —— 改路径必须同改此处）。
     * 与 {@code ProductionScanCompleteService.ENDPOINT_SCAN_COMPLETE} 是**两个**端点
     * ⇒ 同键跨端点复用会在 {@code client_request_keys.endpoint} 留证。
     */
    public static final String ENDPOINT_REWORK = "POST /api/worker/production/rework";

    /** 返工原因长度上限（与迁移 V199 的 {@code reason VARCHAR(500)} 同宽）。 */
    private static final int REASON_MAX = 500;

    private final ProductionScanService scanService;
    private final ProductionService productionService;
    private final WorkerAdminService workerAdminService;
    private final ProductionWorkLogMapper workLogMapper;
    private final ProcessingPositionOperationMapper positionOperationMapper;
    private final ProcessingOrderMapper processingOrderMapper;
    private final ReworkOrderMapper reworkOrderMapper;
    private final OrderMapper orderMapper;
    private final ReworkOrderService reworkOrderService;
    private final ClientRequestIdService clientRequestIdService;

    /**
     * 报返工（唯一写入口）：幂等占位 → 同一事务改记 + 回退 + 开单 → 结果快照。
     *
     * <p>🔴 {@code @Transactional} 覆盖幂等占位/快照（与扫码报工的差别，刻意）：
     * 那里「报工已落库但快照写失败」必须 fail-closed 占住键；这里整笔是一个事务
     * ⇒ 失败时占位与改记一起回滚，客户端换键重试是**合法**的（什么都没发生）。</p>
     *
     * @param body            {@code token}（必填）+ {@code reason}（必填）+ 可选 {@code operation_id} / {@code qty}
     * @param identity        🔴 服务端从工人 session 解（body 里的 worker_id 一个字节都不读）
     * @param clientRequestId {@code X-Client-Request-Id}（缺失 ⇒ 不去重，与既有端点同口径）
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> report(Map<String, Object> body, Long tenantId,
                                      String clientRequestId, WorkerIdentity identity) {
        if (!clientRequestIdService.claim(tenantId, clientRequestId, ENDPOINT_REWORK)) {
            Map<String, Object> replayed = productionService.replayFirstResult(tenantId, clientRequestId);
            log.info("[报返工幂等] 同键重复请求：跳过执行，回放首次结果 tenantId={}", tenantId);
            return replayed;
        }
        return doReport(body, tenantId, identity);
    }

    /** 解析 → 定位 → 改记 + 回退 + 开单（占位成功后执行）。 */
    private Map<String, Object> doReport(Map<String, Object> body, Long tenantId, WorkerIdentity identity) {
        String token = ProductionService.str(body == null ? null : body.get("token"));
        if (!StringUtils.hasText(token)) {
            throw BusinessException.validationError("扫码内容不能为空（token 缺失）");
        }
        String reason = ProductionService.str(body == null ? null : body.get("reason"));
        if (!StringUtils.hasText(reason)) {
            throw BusinessException.validationError(
                    "报返工必须写明原因（哪件、什么问题）—— 这行字是返工单上唯一的问题线索");
        }
        if (reason.trim().length() > REASON_MAX) {
            throw BusinessException.validationError("返工原因最多 " + REASON_MAX + " 个字，请精简后再提交");
        }

        // 解析 + 推断：与扫码报工**同一份**实现（绑定工人 ⇒ 只看他那道工序）
        Map<String, Object> scan = scanService.resolve(token,
                ProductionService.str(body.get("operation_id")), null, null, tenantId, boundOperationOf(identity));
        if (ProductionScanService.GRANULARITY_ORDER.equals(scan.get("granularity"))) {
            throw new BusinessException("SCAN_NEEDS_SELECTION",
                    "这是加工单级旧码（不含套号/部位），无法确定返工的是哪一件 ⇒ 拒绝记账",
                    422,
                    "请扫部位级水洗唛（码上带套号 + 部位）；旧码不默认取第 1 套，那会把返工记到错的窗上");
        }
        Order order = productionService.resolveOrder(String.valueOf(scan.get("order_id")), tenantId);
        ProcessingOrder po = productionService.requireActiveProcessingOrder(order, tenantId);

        // ① 锚点 = 「这件的这道活、本人最近一笔『正常』报工」。
        //    先按解析面给的待做工序找；找不到走回退路径 —— 典型形态正是本单要治的那一个：
        //    **师傅刚扫完码被自动报了工 ⇒ 他那道已经做完，解析面的 operation 是 null**，
        //    这时若直接拒，工人就永远改记不了「刚记的那一笔」。
        AmendTarget target = resolveAmendTarget(tenantId, po.getId(), scan, identity);
        if (target == null) {
            throw new BusinessException("REWORK_NO_REPORT_TO_AMEND",
                    "这项工作还没有可改记的报工（本次未记账）",
                    422,
                    "先扫这张水洗唛完成报工，再来报返工；如果刚报过工，刷新后重扫同一张码再试");
        }
        ProcessingPositionOperation op = target.op();
        ProductionWorkLog normalLog = target.log();
        // 「质检」工序照旧没有报工动作（issue #7186）：与扫码报工同一份判据
        DocumentOperationLinkage.rejectManualReport(op);
        BigDecimal revertQty = nz(normalLog.getQualifiedQty());
        if (revertQty.signum() <= 0) {
            throw new BusinessException("REWORK_NO_REPORT_TO_AMEND",
                    "这一笔报工没有可回退的合格数量（本次未记账）", 422,
                    "请让管理员在「生产 → 报工流水」核对这条记录后再处理");
        }
        BigDecimal qty = ProductionService.bd(body.get("qty"), normalLog.getQty());
        if (qty == null || qty.signum() <= 0) {
            throw BusinessException.validationError("返工数量必须大于 0");
        }

        // ② 回退进度（CAS：读到的旧值不成立 ⇒ 409）
        BigDecimal expectedDone = nz(op.getDoneQty());
        String expectedStatus = op.getStatus() == null ? "pending" : op.getStatus();
        BigDecimal newDone = expectedDone.subtract(revertQty);
        if (newDone.signum() < 0) {
            newDone = BigDecimal.ZERO;
        }
        String newStatus = newDone.compareTo(nz(op.getQty())) >= 0 ? "done" : "pending";
        OffsetDateTime now = OffsetDateTime.now();
        int rows = positionOperationMapper.revertDoneQtyIfUnchanged(op.getId(), tenantId,
                expectedDone, expectedStatus, newDone, newStatus, now);
        if (rows == 0) {
            throw new BusinessException("REWORK_AMEND_CONFLICT",
                    "工序「" + op.getOperationName() + "」的进度刚被另一次提交改过（本次未记账）",
                    409,
                    "下拉刷新本件工序进度后再点一次「报返工」；重复提交不会多记，服务端有幂等与条件更新兜底");
        }

        // ③ 报工明细改记为返工（CAS：只改还处在 normal 的那一笔 ⇒ 同一笔不会被改两次）
        int amended = workLogMapper.update(null, new LambdaUpdateWrapper<ProductionWorkLog>()
                .eq(ProductionWorkLog::getId, normalLog.getId())
                .eq(ProductionWorkLog::getTenantId, tenantId)
                .eq(ProductionWorkLog::getWorkType, "normal")
                .set(ProductionWorkLog::getWorkType, "rework")
                .set(ProductionWorkLog::getQualifiedQty, BigDecimal.ZERO));
        if (amended == 0) {
            throw new BusinessException("REWORK_ALREADY_AMENDED",
                    "这一笔报工刚被改记过（本次未重复改记）", 409,
                    "刷新后到「返工记录」列表确认；同一笔报工只会被改记一次");
        }

        // ④ 加工单若因此不再全绿 ⇒ 回到加工中（completed 是终态的唯一补偿路径，见 mapper 注释）
        boolean reopened = "completed".equals(po.getStatus())
                && processingOrderMapper.reopenCompletedIfAny(po.getId(), tenantId, now) > 0;
        if (reopened) {
            log.info("[报返工] 加工单由已完成回到加工中: po={}", po.getProcessingOrderNo());
        }

        // ⑤ 生成返工单（source='worker'）
        var rework = reworkOrderService.createWorkerRework(tenantId, order.getId(), po.getId(),
                op.getId(), op.getOperationName(), qty, reason.trim(),
                identity.workerId(), identity.workerName(), normalLog.getId(),
                // 件键（issue #7945）：套号 × 部位 = 一张水洗唛码；为 null 说明这行是存量实例（不猜）
                op.getOrderItemId(), op.getSetId(), op.getSetNo(), op.getPositionName());

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("rework_no", rework.getReworkNo());
        result.put("operation_id", op.getId());
        // 件键回执（issue #7945）：界面据此确认「返的是哪一件」；null = 未定位，不编值
        result.put("order_item_id", rework.getOrderItemId());
        result.put("set_no", rework.getSetNo());
        result.put("position_name", rework.getPositionName());
        // 读面成对给出逻辑工序名（守卫 `test_op_name_registry_guard` ③）：`operation_name` 是工人端
        // **快照名**（可能是变体名，如 `精裁-布`）；只给快照名 ⇒ 消费面拼不出统一显示名。
        result.put("operation_name", op.getOperationName());
        result.put("logical_name", ProductionOperationQueryService.logicalOperationName(op.getOperationName()));
        result.put("qty", qty);
        result.put("done_qty", newDone);
        result.put("status", newStatus);
        result.put("order_completed", false);
        result.put("amended_work_log_id", normalLog.getId());
        return result;
    }

    /**
     * 「报返工的加工单列表」（工人端「返工记录」页的数据面，issue #7860）。
     *
     * <p>口径：一行 = 一张加工单，来源 = {@code production_work_logs.work_type='rework'} 的**全部**明细
     * （不只本服务开出来的那些：工人用报工三态「返工」记的也算）⇒ 车间看到的就是「谁报过返工」这件事本身。
     * 行内给：加工单号 / 订单号 / 加工单状态 / 返工笔数 / 返工数量合计 / 最近返工时间 / 提示原因 /
     * 涉及工序（同名合并，数量累加）。</p>
     *
     * <p>🔴 不重算任何计件金额、不改写任何报工行：这是**只读聚合**，金额口径仍在
     * {@code ProductionService.aggregate}（返工/报废不计件）。</p>
     */
    public Map<String, Object> reworkOrders(Long tenantId) {
        List<ProductionWorkLog> logs = workLogMapper.selectList(new LambdaQueryWrapper<ProductionWorkLog>()
                .eq(ProductionWorkLog::getTenantId, tenantId)
                .eq(ProductionWorkLog::getWorkType, "rework")
                .eq(ProductionWorkLog::getDeleted, 0)
                .orderByDesc(ProductionWorkLog::getCreatedAt));
        Map<String, Map<String, Object>> byOrder = new LinkedHashMap<>();
        Map<String, Map<String, Map<String, Object>>> opsByOrder = new LinkedHashMap<>();
        for (ProductionWorkLog logRow : logs) {
            String poId = logRow.getProcessingOrderId();
            if (!StringUtils.hasText(poId)) {
                continue;
            }
            Map<String, Object> row = byOrder.computeIfAbsent(poId, k -> {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("processing_order_id", k);
                m.put("processing_order_no", null);
                m.put("order_no", null);
                m.put("processing_status", null);
                m.put("rework_count", 0);
                m.put("rework_qty", BigDecimal.ZERO);
                m.put("latest_rework_at", null);
                m.put("latest_reason", null);
                return m;
            });
            row.put("rework_count", (Integer) row.get("rework_count") + 1);
            row.put("rework_qty", ((BigDecimal) row.get("rework_qty")).add(nz(logRow.getQty())));
            if (row.get("latest_rework_at") == null) {
                row.put("latest_rework_at", logRow.getCreatedAt());
            }
            String name = StringUtils.hasText(logRow.getOperationName()) ? logRow.getOperationName() : "未记工序";
            Map<String, Map<String, Object>> ops =
                    opsByOrder.computeIfAbsent(poId, k -> new LinkedHashMap<>());
            Map<String, Object> opRow = ops.computeIfAbsent(name, k -> {
                Map<String, Object> m = new LinkedHashMap<>();
                // 成对给出逻辑名（同上报酬：快照名可能是变体名，消费面只认逻辑名）
                m.put("operation_name", k);
                m.put("logical_name", ProductionOperationQueryService.logicalOperationName(k));
                m.put("qty", BigDecimal.ZERO);
                m.put("count", 0);
                return m;
            });
            opRow.put("qty", ((BigDecimal) opRow.get("qty")).add(nz(logRow.getQty())));
            opRow.put("count", (Integer) opRow.get("count") + 1);
        }
        // 加工单号 / 订单号 / 状态（取不到 ⇒ 保持 null，界面渲染 —）
        for (Map.Entry<String, Map<String, Object>> entry : byOrder.entrySet()) {
            ProcessingOrder po = processingOrderMapper.selectById(entry.getKey());
            if (po == null) {
                continue;
            }
            entry.getValue().put("processing_order_no", po.getProcessingOrderNo());
            entry.getValue().put("processing_status", po.getStatus());
            Order salesOrder = po.getOrderId() == null ? null : orderMapper.selectById(po.getOrderId());
            entry.getValue().put("order_no", salesOrder == null ? null : salesOrder.getOrderNo());
        }
        // 提示原因 = 该加工单**最新**一张车间返工单的 reason（没有 ⇒ null，界面不摆占位）
        if (!byOrder.isEmpty()) {
            List<ReworkOrder> reworks = reworkOrderMapper.selectList(new LambdaQueryWrapper<ReworkOrder>()
                    .eq(ReworkOrder::getTenantId, tenantId)
                    .eq(ReworkOrder::getSource, ReworkOrderService.SOURCE_WORKER)
                    .eq(ReworkOrder::getDeleted, 0)
                    .in(ReworkOrder::getProcessingOrderId, byOrder.keySet())
                    .orderByDesc(ReworkOrder::getCreatedAt));
            for (ReworkOrder rework : reworks) {
                byOrder.get(rework.getProcessingOrderId()).putIfAbsent("latest_reason", rework.getReason());
            }
        }
        List<Map<String, Object>> rows = new ArrayList<>();
        for (Map.Entry<String, Map<String, Object>> entry : byOrder.entrySet()) {
            Map<String, Object> row = entry.getValue();
            row.put("operations", new ArrayList<>(opsByOrder.get(entry.getKey()).values()));
            rows.add(row);
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("orders", rows);
        return out;
    }

    /** 改记目标 = 工序实例 + 那一笔要改记的报工（同一对，拆开传必漂）。 */
    private record AmendTarget(ProcessingPositionOperation op, ProductionWorkLog log) {
    }

    /**
     * 找出「这件的这道活、本人最近一笔『正常』报工」。
     *
     * <p>🔴 两条路径（顺序即优先级）：</p>
     * <ol>
     *   <li><b>解析面给的待做工序</b>（与报工写面同一份口径）：这道还没做完 ⇒ 直接看它；</li>
     *   <li><b>回退路径</b>（本单真正的现场形态）：工人扫码即自动报工 ⇒ 他那道**已经做完**，
     *       解析面给的 {@code operation} 是 {@code null}。此时按
     *       「本加工单 + 本工人 + 绑定工序 + **同一部位**」反查最近一笔 normal
     *       —— 部位必须对上，否则会改到同一单里**另一樘窗**的账。</li>
     * </ol>
     *
     * <p>绑定工序（{@code users.worker_operation}）非空时只认这道：不绑定就没有「哪道是你的活」的唯一答案，
     * 改记别人的工序是改工资账（与扫码报工同一条纪律）。</p>
     */
    private AmendTarget resolveAmendTarget(Long tenantId, String processingOrderId,
                                           Map<String, Object> scan, WorkerIdentity identity) {
        @SuppressWarnings("unchecked")
        Map<String, Object> operationView = (Map<String, Object>) scan.get("operation");
        if (operationView != null) {
            ProcessingPositionOperation op = productionService.requireActiveOperation(
                    processingOrderId, String.valueOf(operationView.get("operation_id")), tenantId);
            ProductionWorkLog logRow = latestNormalLog(tenantId, processingOrderId, op.getId(), identity.workerId());
            if (logRow != null) {
                return new AmendTarget(op, logRow);
            }
        }
        String itemId = itemIdOf(scan);
        String workerOperation = boundOperationOf(identity);
        List<ProductionWorkLog> logs = workLogMapper.selectList(new LambdaQueryWrapper<ProductionWorkLog>()
                .eq(ProductionWorkLog::getTenantId, tenantId)
                .eq(ProductionWorkLog::getProcessingOrderId, processingOrderId)
                .eq(ProductionWorkLog::getWorkerId, identity.workerId())
                .eq(ProductionWorkLog::getWorkType, "normal")
                .eq(ProductionWorkLog::getDeleted, 0)
                .orderByDesc(ProductionWorkLog::getCreatedAt));
        if (logs.isEmpty()) {
            return null;
        }
        Map<String, ProcessingPositionOperation> opById = new LinkedHashMap<>();
        for (ProcessingPositionOperation row : positionOperationMapper.selectList(
                new LambdaQueryWrapper<ProcessingPositionOperation>()
                        .eq(ProcessingPositionOperation::getTenantId, tenantId)
                        .eq(ProcessingPositionOperation::getProcessingOrderId, processingOrderId)
                        .eq(ProcessingPositionOperation::getDeleted, 0))) {
            opById.put(row.getId(), row);
        }
        for (ProductionWorkLog logRow : logs) {
            ProcessingPositionOperation op = opById.get(logRow.getOperationId());
            if (op == null) {
                continue;                       // 工序实例已软删（重新实例化过）⇒ 不能改它
            }
            if (itemId != null && !itemId.equals(op.getOrderItemId())) {
                continue;                       // 同一单里的另一樘窗 ⇒ 不是这件
            }
            if (workerOperation != null && !workerOperation.equals(
                    ProductionOperationQueryService.logicalOperationName(op.getOperationName()))) {
                continue;                       // 不是这位工人的活
            }
            return new AmendTarget(op, logRow);
        }
        return null;
    }

    /** 扫码结果里的「这一件」= {@code position.order_item_id}（旧码 / 缺键 ⇒ null，不猜）。 */
    private static String itemIdOf(Map<String, Object> scan) {
        Object position = scan.get("position");
        if (!(position instanceof Map<?, ?> map)) {
            return null;
        }
        Object itemId = map.get("order_item_id");
        return itemId == null || String.valueOf(itemId).isBlank() ? null : String.valueOf(itemId);
    }

    /**
     * 这位工人在本件本工序**最近一笔「正常」报工**（可改记的锚点）；没有 ⇒ {@code null}。
     *
     * <p>🔴 只认 {@code work_type='normal'}：返工/报废那两种本来就不计件，改记它们没有意义；
     * 且每次改记会把一笔 normal 变成 rework ⇒ 同一笔不会被二次改记（CAS 是第二道保险）。</p>
     */
    private ProductionWorkLog latestNormalLog(Long tenantId, String processingOrderId,
                                              String operationId, String workerId) {
        List<ProductionWorkLog> rows = workLogMapper.selectList(new LambdaQueryWrapper<ProductionWorkLog>()
                .eq(ProductionWorkLog::getTenantId, tenantId)
                .eq(ProductionWorkLog::getProcessingOrderId, processingOrderId)
                .eq(ProductionWorkLog::getOperationId, operationId)
                .eq(ProductionWorkLog::getWorkerId, workerId)
                .eq(ProductionWorkLog::getWorkType, "normal")
                .eq(ProductionWorkLog::getDeleted, 0)
                .orderByDesc(ProductionWorkLog::getCreatedAt)
                .last("LIMIT 1"));
        return rows.isEmpty() ? null : rows.get(0);
    }

    /** 工人档案上绑定的逻辑工序（issue #7749）；未绑定 / 读不到 ⇒ {@code null}（旧行为）。 */
    private String boundOperationOf(WorkerIdentity identity) {
        if (identity == null) {
            return null;
        }
        var worker = workerAdminService.findOwnedWorker(identity.workerId());
        return worker == null ? null : worker.getWorkerOperation();
    }

    private static BigDecimal nz(BigDecimal value) {
        return value == null ? BigDecimal.ZERO : value;
    }
}
