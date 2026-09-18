package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.UpdateWrapper;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.entity.ProductionWorkLog;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
import com.migao.admin.mapper.ProductionWorkLogMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.YearMonth;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import java.util.stream.Collectors;

/**
 * 生产报工服务（issue #3995，M4-G-2）
 *
 * 工序实例化（扫码报工入口 + 加工单二维码 token）→ 扫码报工推进进度 → 必完工序全绿自动完工
 * → 计件（Σ 合格数量 × 单价 × 系数，单工序一人制）。
 *
 * 真值源：docs/curtain-production-rules.md §2 工序库 / §4 计件 / §5 扫码报工闭环；
 * 确定性核心语义与 ai-agent-service app/production/{routing,piecework}.py（M4-G-1，issue #3993）一致：
 * 报工三态 normal/rework/scrap —— 返工/报废既不累加进度也不计件；
 * 必完工序（is_must_finish）全绿（done_qty ≥ qty）→ **加工单置 completed**（issue #4117：
 * 订单留在 producing，见 {@link #report} 的完工语义 —— 写订单 completed 会让发货链断掉）。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ProductionService {

    /** 报工三态：normal 正常 / rework 返工 / scrap 报废（M4-G-1 WORK_TYPES 同口径） */
    public static final Set<String> WORK_TYPES = Set.of("normal", "rework", "scrap");

    /**
     * 报工端点标识（幂等诊断用：同键跨端点复用会在 {@code client_request_keys.endpoint} 留证）。
     * 与 Controller 的路径逐字一致 —— 改动路径必须同改此处，否则诊断列表会指错端点。
     */
    public static final String ENDPOINT_REPORT =
            "POST /api/admin/production/orders/{orderId}/operations/{operationId}/report";

    /**
     * 回放标记键名（与既有 {@code ClientRequestIdService.replayedMarker} 同口径，
     * {@code OrderDetailResponse}/{@code AfterSalesDetailResponse} 的 {@code replayed} 字段同源）。
     * 有它 ⇒ 本次**没有**新落库，前端不该把它当成一次新报工（进度/完工提示会因此错位）。
     */
    public static final String REPLAYED_KEY = "replayed";

    private static final Map<String, String> ORDER_STATUS_LABELS = Map.of(
            "pending", "待付款",
            "confirmed", "已确认",
            "producing", "生产中",
            "shipped", "已发货",
            "completed", "已完成",
            "cancelled", "已取消");

    private final ProcessingOrderMapper processingOrderMapper;
    private final ProcessingPositionOperationMapper positionOperationMapper;
    private final ProductionWorkLogMapper workLogMapper;
    private final OrderMapper orderMapper;
    private final ClientRequestIdService clientRequestIdService;

    // ============================================================ 实例化

    /**
     * 实例化工序（加工单 × 部位 × 工序）+ 生成加工单二维码 token。
     *
     * 幂等（issue #4116）：**同一工序配置**的重复调用是空操作 —— 不重插行、不软删旧实例、
     * 不清零已有报工的 done_qty，已有 token 复用（已打印的码不失效）。
     * 仅当传入配置与已有实例不同（工艺变更 → 真·重新实例化）才软删旧实例并重插
     * （软删保留审计，历史报工仍按实例快照可追溯）。
     */
    @Transactional(rollbackFor = Exception.class)
    @SuppressWarnings("unchecked")
    public Map<String, Object> instantiate(String orderId, Map<String, Object> body, Long tenantId) {
        Object rawPositions = body == null ? null : body.get("positions");
        if (!(rawPositions instanceof List<?> positions) || positions.isEmpty()) {
            throw BusinessException.validationError("positions 不能为空");
        }
        Order order = resolveOrder(orderId, tenantId);
        ProcessingOrder po = processingOrderMapper.selectActiveByOrderId(order.getId(), tenantId);
        if (po == null) {
            throw BusinessException.validationError(
                    "订单 " + order.getOrderNo() + " 尚无加工单，请先生成加工单再实例化工序");
        }
        List<OpSpec> specs = parseSpecs(positions);
        String qrToken = ensureQrToken(po);

        // 幂等：配置与已有活跃实例一致 ⇒ 一行都不碰（重复调用不得重插行/不得清零报工进度）
        List<ProcessingPositionOperation> existing = listOperations(po.getId(), tenantId);
        if (!existing.isEmpty() && signatures(specsOf(existing)).equals(signatures(specs))) {
            log.info("工序已实例化，重复调用跳过（幂等）: po={}, orderId={}, operations={}, qrToken={}",
                    po.getProcessingOrderNo(), order.getId(), existing.size(), qrToken);
            return instantiateResult(qrToken, existing.size());
        }

        // 首次实例化 / 工序序列随工艺变更 → 旧实例软删
        // 用字符串列名而非 Lambda 列名：LambdaUpdateWrapper.set 会立即求值列名，Standalone
        // MockMvc 单测环境没有 MyBatis-Plus TableInfo 缓存（同 SettingsController 的既有做法）。
        if (!existing.isEmpty()) {
            log.info("工序配置变更，重新实例化（旧实例软删 {} 条）: po={}", existing.size(), po.getProcessingOrderNo());
            positionOperationMapper.update(null, new UpdateWrapper<ProcessingPositionOperation>()
                    .eq("processing_order_id", po.getId())
                    .eq("tenant_id", tenantId)
                    .eq("deleted", 0)
                    .set("deleted", 1)
                    .set("updated_at", OffsetDateTime.now()));
        }

        for (OpSpec spec : specs) {
            positionOperationMapper.insert(ProcessingPositionOperation.builder()
                    .tenantId(tenantId)
                    .processingOrderId(po.getId())
                    .positionName(spec.positionName())
                    .seq(spec.seq())
                    .operationName(spec.operationName())
                    .groupName(spec.groupName())
                    .unit(spec.unit())
                    .qty(spec.qty())
                    .unitPrice(spec.unitPrice())
                    .factor(spec.factor())
                    .qtySource(spec.qtySource())
                    .isMustFinish(spec.mustFinish())
                    .isStartMarker(spec.startMarker())
                    .status("pending")
                    .doneQty(BigDecimal.ZERO)
                    .createdAt(OffsetDateTime.now())
                    .updatedAt(OffsetDateTime.now())
                    .deleted(0)
                    .build());
        }
        log.info("实例化工序: po={}, orderId={}, operations={}, qrToken={}",
                po.getProcessingOrderNo(), order.getId(), specs.size(), qrToken);
        return instantiateResult(qrToken, specs.size());
    }

    /** 复用已有 token（已打印的码不失效）；缺失时生成 32 位 token 并落库。 */
    private String ensureQrToken(ProcessingOrder po) {
        if (StringUtils.hasText(po.getQrToken())) {
            return po.getQrToken();
        }
        String qrToken = UUID.randomUUID().toString().replace("-", "");
        processingOrderMapper.updateById(ProcessingOrder.builder().id(po.getId()).qrToken(qrToken).build());
        return qrToken;
    }

    /**
     * 撤销加工单二维码 token（issue #4202；真值源 §1「token 化、可撤销」）。
     *
     * <p>撤销 = 置空 {@code qr_token}：已打印的码立即失效（{@link #resolveOrder} 的 qr_token
     * 形态解析不到订单 ⇒ 扫码报工 404），再次 {@link #instantiate} 时由 {@link #ensureQrToken}
     * 重新生成新码。这是**安全相关写操作**（旧纸件作废），端点声明 {@code processing:manage}。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> revokeQrToken(String orderId, Long tenantId) {
        Order order = resolveOrder(orderId, tenantId);
        ProcessingOrder po = processingOrderMapper.selectActiveByOrderId(order.getId(), tenantId);
        if (po == null) {
            throw BusinessException.validationError(
                    "订单 " + order.getOrderNo() + " 尚无加工单，没有可撤销的二维码");
        }
        boolean revoked = processingOrderMapper.revokeQrToken(po.getId(), tenantId, OffsetDateTime.now()) > 0;
        log.info("撤销加工单二维码: orderNo={}, po={}, revoked={}", order.getOrderNo(), po.getProcessingOrderNo(), revoked);
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("order_id", order.getId());
        result.put("qr_token", null);
        result.put("revoked", revoked);
        return result;
    }

    private Map<String, Object> instantiateResult(String qrToken, int operationCount) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("qr_token", qrToken);
        result.put("operation_count", operationCount);
        return result;
    }

    /**
     * 请求工序归一化（幂等比较与落库**共用同一解析口径**，避免「比较一套、落库一套」漂移）。
     * 缺省值与既有口径一致：seq = 部位内自然序，qty/单价 0，系数 1，标记 false。
     */
    @SuppressWarnings("unchecked")
    private List<OpSpec> parseSpecs(List<?> positions) {
        List<OpSpec> specs = new ArrayList<>();
        for (Object rawPosition : positions) {
            if (!(rawPosition instanceof Map<?, ?> positionMap)) {
                continue;
            }
            Map<String, Object> position = (Map<String, Object>) positionMap;
            String positionName = str(position.get("position_name"), "未命名部位");
            Object rawOps = position.get("operations");
            if (!(rawOps instanceof List<?> opList)) {
                continue;
            }
            int seq = 1;
            for (Object rawOp : opList) {
                if (!(rawOp instanceof Map<?, ?> opMap)) {
                    continue;
                }
                Map<String, Object> op = (Map<String, Object>) opMap;
                String operationName = str(op.get("operation"));
                if (!StringUtils.hasText(operationName)) {
                    throw BusinessException.validationError("工序名（operation）不能为空");
                }
                specs.add(new OpSpec(positionName,
                        op.get("seq") == null ? seq : bd(op.get("seq"), BigDecimal.valueOf(seq)).intValue(),
                        operationName,
                        str(op.get("group")),
                        str(op.get("unit")),
                        bd(op.get("qty"), BigDecimal.ZERO),
                        bd(op.get("unit_price"), BigDecimal.ZERO),
                        bd(op.get("factor"), BigDecimal.ONE),
                        str(op.get("qty_source")),
                        flag(op.get("is_must_finish")),
                        flag(op.get("is_start_marker"))));
                seq++;
            }
        }
        return specs;
    }

    /** 已落库实例 → 同一归一化形态（幂等比较用）。 */
    private List<OpSpec> specsOf(List<ProcessingPositionOperation> operations) {
        List<OpSpec> specs = new ArrayList<>();
        for (ProcessingPositionOperation op : operations) {
            specs.add(new OpSpec(op.getPositionName(), op.getSeq() == null ? 0 : op.getSeq(),
                    op.getOperationName(), op.getGroupName(), op.getUnit(),
                    op.getQty(), op.getUnitPrice(), op.getFactor(), op.getQtySource(),
                    Boolean.TRUE.equals(op.getIsMustFinish()), Boolean.TRUE.equals(op.getIsStartMarker())));
        }
        return specs;
    }

    /** 规范化签名（排序 ⇒ 与部位/工序书写顺序无关；数值去尾零 ⇒ 2 与 2.00 视为同一配置）。 */
    private static List<String> signatures(List<OpSpec> specs) {
        List<String> signatures = new ArrayList<>(specs.size());
        for (OpSpec spec : specs) {
            signatures.add(spec.signature());
        }
        Collections.sort(signatures);
        return signatures;
    }

    /** 工序实例归一化形态：字段集 = 落库字段集（比较用的最小充分集）。 */
    private record OpSpec(String positionName, int seq, String operationName, String groupName, String unit,
                          BigDecimal qty, BigDecimal unitPrice, BigDecimal factor, String qtySource,
                          boolean mustFinish, boolean startMarker) {

        String signature() {
            return String.join("\u0001",
                    orDash(positionName), String.valueOf(seq), orDash(operationName), orDash(groupName),
                    orDash(unit), num(qty), num(unitPrice), num(factor), orDash(qtySource),
                    String.valueOf(mustFinish), String.valueOf(startMarker));
        }

        private static String orDash(String value) {
            return value == null ? "-" : value;
        }

        private static String num(BigDecimal value) {
            return nz(value).stripTrailingZeros().toPlainString();
        }
    }

    // ============================================================ 查询

    /** 加工单工序树 + 进度（扫工页/后台加工单详情用） */
    public Map<String, Object> getOperations(String orderId, Long tenantId) {
        Order order = resolveOrder(orderId, tenantId);
        ProcessingOrder po = processingOrderMapper.selectActiveByOrderId(order.getId(), tenantId);
        List<ProcessingPositionOperation> operations = po == null
                ? List.of()
                : listOperations(po.getId(), tenantId);

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("order_id", order.getId());
        result.put("qr_token", po == null ? null : po.getQrToken());
        result.put("positions", buildPositions(operations));
        result.put("progress", progressOf(operations));
        return result;
    }

    /**
     * 米宝生产进度（冻结契约，并行包消费）：{order_no, status, status_text, progress_percent,
     * current_operation, pending_operations, total_operations, done_operations, expected_delivery_date}。
     * 无加工单/无实例时为「未开始」态而不是错误态（current_operation 为空串，交期为 null）。
     *
     * 订单解析与报工链路同口径（issue #4007）：复用 {@link #resolveOrder} 的
     * order_id → order_no → qr_token → processing_order_no 四形态，**不得只认 order_no** —— agent 侧拿到的是
     * 内部 order_id（CH-039/CH-040 的 `no_success(production_progress_query)` 病灶）。
     */
    public Map<String, Object> progress(String orderNo, Long tenantId) {
        if (!StringUtils.hasText(orderNo)) {
            throw BusinessException.validationError("order_no 不能为空");
        }
        Order order = resolveOrder(orderNo.trim(), tenantId);
        ProcessingOrder po = processingOrderMapper.selectActiveByOrderId(order.getId(), tenantId);
        List<ProcessingPositionOperation> operations = po == null
                ? List.of()
                : listOperations(po.getId(), tenantId);

        List<String> pending = new ArrayList<>();
        String current = "";
        for (ProcessingPositionOperation op : operations) {
            if (!isDone(op)) {
                pending.add(op.getOperationName());
                if (current.isEmpty()) {
                    current = op.getOperationName();
                }
            }
        }
        Map<String, Object> progress = progressOf(operations);

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("order_no", order.getOrderNo());
        result.put("status", order.getStatus());
        result.put("status_text", ORDER_STATUS_LABELS.getOrDefault(order.getStatus(), order.getStatus()));
        result.put("progress_percent", progress.get("percent"));
        result.put("current_operation", current);
        result.put("pending_operations", pending);
        result.put("total_operations", progress.get("total"));
        result.put("done_operations", progress.get("done"));
        result.put("expected_delivery_date",
                po == null || po.getExpectedDeliveryDate() == null
                        ? null
                        : po.getExpectedDeliveryDate().toString());
        return result;
    }

    // ============================================================ 报工

    /**
     * 扫码报工：幂等占位 → 四项防呆 →（落报工明细 → 原子推进 done_qty → 必完全绿则加工单置 completed）。
     *
     * <p><b>§5 四项防呆（issue #4116，逐项对应一次真实误报工的形态）：</b></p>
     * <ol>
     *   <li><b>重复报工幂等</b>（{@code X-Client-Request-Id} 同键 ⇒ 不执行、回放首次结果）：
     *       工人连点两次 / 网络重试 ⇒ 同一笔报工落两条明细、{@code done_qty} 翻倍。
     *       复用既有 {@link ClientRequestIdService}（与下单/建工单**同一套**实现与同一张表）。
     *       接线放在本方法（Controller 只透传请求头）：本方法**不加** {@code @Transactional}，
     *       占位与快照的提交边界才是既有的「先占位 → 执行 → 落快照」同款（见方法内注释）。</li>
     *   <li><b>越站</b>（前道未完成不得报后续工序）：判据来自既有语义 —— 工序实例的
     *       {@code seq}（部位内顺序，V49 注释）+ {@link #isDone}（{@code done_qty ≥ qty}）；
     *       {@code is_start_marker} 只影响订单状态推进，**不参与**顺序判据（避免第二套口径）。</li>
     *   <li><b>数量上限</b>（{@code done_qty + 本次合格数 ≤ qty}）：见方法内注释（选择**拒绝**的理由）。</li>
     *   <li><b>非本部位</b>（报工必须落在该加工单**实际存在且活跃**的工序实例上）：
     *       {@code selectById} 命中后按 tenant_id / deleted=0（fail-closed，含 NULL）/ 加工单归属三重校验，
     *       三重任一不成立即 404；且此处**只**认库里的实例 id —— 请求体里的工序名不参与定位，
     *       无法凭空造出工序名。</li>
     * </ol>
     *
     * <p>并发（不同键/无键的并发请求）：由 {@code advanceDoneQtyIfUnchanged} 的 CAS 谓词关闭
     * 丢更新窗口（见该 Mapper 方法注释），影响行数 0 ⇒ fail-closed 而不是静默覆盖。</p>
     *
     * @param clientRequestId 幂等键（{@code X-Client-Request-Id}）；缺失/空白 ⇒ 原路径逐字不变
     */
    public Map<String, Object> report(String orderId, String operationId,
                                      Map<String, Object> body, Long tenantId,
                                      String clientRequestId) {
        // ① 先占位：同键重复请求**不执行**（不落明细、不累加、不推进完工判定）
        if (!clientRequestIdService.claim(tenantId, clientRequestId, ENDPOINT_REPORT)) {
            // ② 回放首次成功结果；无快照（占位在飞/已失败）⇒ replay fail-closed 抛错，不返回空结果
            Map<String, Object> replayed = replayReport(tenantId, clientRequestId);
            log.info("[报工幂等] 同键重复请求：跳过执行，回放首次结果 tenantId={}, operationId={}",
                    tenantId, operationId);
            return replayed;
        }
        try {
            Map<String, Object> result = doReport(orderId, operationId, body, tenantId);
            // ③ 落结果快照（同键后续请求回放它）。放在 try 之外：快照写失败时**不得**释放占位
            //    —— 报工已经落库，宁可让同键请求 fail-closed 报错，也不能退化成「再报一次」
            clientRequestIdService.complete(tenantId, clientRequestId, result);
            return result;
        } catch (RuntimeException e) {
            // ④ 执行失败（校验/越站/超上限/串行冲突/DB 错误）⇒ 释放占位：否则一次失败就把该键
            //    永久占死，工人改用同键重试（小程序重试）会被误判为「重复」而永远进不来
            clientRequestIdService.discard(tenantId, clientRequestId);
            throw e; // 原样抛出，不吞（失败必须对工人可见）
        }
    }

    /**
     * 回放首次成功结果并打上 {@link #REPLAYED_KEY} 标记。
     *
     * <p>为什么必须有标记：没有它，调用方分不出「首次执行成功」与「同键回放」——
     * 小程序无法告知工人"这次没有新增报工"、也无法解释 {@code done_qty} 为什么没变。</p>
     *
     * <p>回放内容 = 首次那份快照（{@code done_qty}/{@code status} 是**首次执行时**的取值）：
     * 幂等的定义就是「同键拿到同一结果」，不得用当前库值替换（那会让两次响应不同 ⇒ 非幂等）。</p>
     */
    @SuppressWarnings({"unchecked", "rawtypes"})
    private Map<String, Object> replayReport(Long tenantId, String clientRequestId) {
        Optional<Map> stale = clientRequestIdService.replay(tenantId, clientRequestId, Map.class);
        Map<String, Object> snapshot = (Map<String, Object>) stale.orElseThrow(
                () -> new BusinessException("REQUEST_IN_PROGRESS",
                        "同一 X-Client-Request-Id 的报工请求正在处理中，本次未重复报工",
                        409,
                        "请勿重复提交；请稍后下拉刷新本加工单工序进度确认是否已报工"
                                + "（换新幂等键重试会重复报工）"));
        snapshot.put(REPLAYED_KEY, Boolean.TRUE);
        return snapshot;
    }

    /**
     * 报工主体（占位成功后才执行；**不加** {@code @Transactional} —— 见 {@link #report} 的接线注释）。
     */
    private Map<String, Object> doReport(String orderId, String operationId,
                                         Map<String, Object> body, Long tenantId) {
        Order order = resolveOrder(orderId, tenantId);
        ProcessingOrder po = processingOrderMapper.selectActiveByOrderId(order.getId(), tenantId);
        if (po == null) {
            throw BusinessException.validationError(
                    "订单 " + order.getOrderNo() + " 尚无加工单，无法报工");
        }
        // 防呆④ 非本部位：活跃性判据用 `deleted=0` 的**正向**相等（fail-closed）——
        // 旧写法 `Integer.valueOf(1).equals(deleted)` 在 deleted 为 NULL 时判为「未软删」而放行，
        // 而软删实例（工艺变更后重新实例化，V49 `deleted INTEGER DEFAULT 0` 可空）
        // 正是**不该**再被报工的那批（进度会记到废弃实例上，工件永远做不完）。
        ProcessingPositionOperation op = positionOperationMapper.selectById(operationId);
        if (op == null || !tenantId.equals(op.getTenantId())
                || !Integer.valueOf(0).equals(op.getDeleted())
                || !po.getId().equals(op.getProcessingOrderId())) {
            throw BusinessException.notFound("工序");
        }

        String workType = str(body == null ? null : body.get("work_type"), "normal");
        if (!WORK_TYPES.contains(workType)) {
            throw BusinessException.validationError("work_type 仅支持 normal/rework/scrap");
        }
        BigDecimal qty = bd(body == null ? null : body.get("qty"), null);
        if (qty == null || qty.signum() <= 0) {
            throw BusinessException.validationError("qty 必须大于 0");
        }
        Object rawQualified = body.get("qualified_qty");
        BigDecimal qualifiedQty = rawQualified == null ? qty : bd(rawQualified, qty);
        if (qualifiedQty.signum() < 0) {
            throw BusinessException.validationError("qualified_qty 不能为负");
        }
        // 报工前的实例快照（越站判据必须看**报工前**的状态，不能看自己这次的结果）
        List<ProcessingPositionOperation> before = listOperations(po.getId(), tenantId);
        boolean advances = "normal".equals(workType) && qualifiedQty.signum() > 0;

        if (advances) {
            assertPredecessorsDone(op, before);
            assertWithinPlannedQty(op, qualifiedQty);
        }

        workLogMapper.insert(ProductionWorkLog.builder()
                .tenantId(tenantId)
                .processingOrderId(po.getId())
                .operationId(op.getId())
                .operationName(op.getOperationName())
                .workerId(str(body.get("worker_id")))
                .workerName(str(body.get("worker_name")))
                .qty(qty)
                .qualifiedQty(qualifiedQty)
                .workType(workType)
                .workDate(LocalDate.now())
                .createdAt(OffsetDateTime.now())
                .deleted(0)
                .build());

        BigDecimal doneQty = nz(op.getDoneQty());
        String status = op.getStatus() == null ? "pending" : op.getStatus();
        if (advances) {
            BigDecimal previousDoneQty = nz(op.getDoneQty());
            String previousStatus = status;
            doneQty = previousDoneQty.add(qualifiedQty);
            status = "done";
            // 原子有序推进（CAS：仅当该行仍是读到的旧值时才累加）——
            // 影响行数 0 ⇒ 并发请求已经推进过这一行：fail-closed，绝不静默覆盖别人的报工
            int rows = positionOperationMapper.advanceDoneQtyIfUnchanged(
                    op.getId(), tenantId, previousDoneQty, previousStatus, doneQty, OffsetDateTime.now());
            if (rows == 0) {
                throw new BusinessException("OPERATION_ALREADY_ADVANCED",
                        "工序「" + op.getOperationName() + "」刚被另一次报工推进（本次未重复累加）",
                        409,
                        "请下拉刷新本加工单工序进度后再确认是否仍需报工；"
                                + "若这是本人刚提交的报工，说明已成功，无需重报");
            }
        }

        boolean productionCompleted = false;
        if (advances && isMustFinishAllDone(po.getId(), tenantId)) {
            // 完工 = **加工单**置 completed（issue #4117），**不是**订单状态推进：
            // ① 订单状态机（OrderService.STATUS_TRANSITIONS）不设 producing→completed，
            //    且 completed 是终态（无任何后继）⇒ 旧实现用裸 UpdateWrapper 直写订单 completed，
            //    会让含加工项订单**既发不了货也回不去**；
            // ② 发货守卫（OrderService.assertProcessingCompletedBeforeShip）读的正是**加工单**
            //    status='completed'（processingOrderMapper.countCompletedByOrderId），
            //    而 shipOrderIfApplicable 只在订单为 confirmed/producing 时流转
            //    ⇒ 加工单置 completed、订单留在 producing，发货链才通。
            int rows = processingOrderMapper.markCompletedIfActive(po.getId(), tenantId, OffsetDateTime.now());
            productionCompleted = rows > 0;
            if (productionCompleted) {
                log.info("必完工序全绿，加工单完工: orderNo={}, po={}", order.getOrderNo(), po.getProcessingOrderNo());
            }
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("operation_id", op.getId());
        result.put("done_qty", doneQty);
        result.put("status", status);
        // 键名为**冻结契约**（bmini 扫工页 productionService.ts 消费），语义 = 加工单完工（生产完成）
        result.put("order_completed", productionCompleted);
        return result;
    }

    /**
     * 防呆② 越站：前道工序未完成（{@code done_qty < qty}）时不得报后续工序。
     *
     * <p>为什么用「立即前道」而不是「全部前道」：{@code seq} 保证顺序，若立即前道已完成，
     * 则它之前的所有工序在**同一不变式**下也已完成（每次报工都过本闸门）——
     * 逐条遍历是同一判据的冗余形式，取「seq 最大且小于本工序」的那一条即可。
     * 与 {@code listOperations} 的既有排序（部位名 / seq）同口径：同部位内比较。</p>
     *
     * <p>仅约束**推进型**报工（normal 且合格数 &gt; 0）：返工/报废（rework/scrap）是
     * 「如实记录现场」而非推进生产，把它们拦在顺序门外会逼工人不记录 —— 那是更坏的失效。</p>
     */
    private void assertPredecessorsDone(ProcessingPositionOperation op,
                                        List<ProcessingPositionOperation> before) {
        int seq = op.getSeq() == null ? 0 : op.getSeq();
        if (seq <= 0) {
            return; // 无序号（脏数据）⇒ 无顺序可判，不误伤
        }
        ProcessingPositionOperation predecessor = before.stream()
                .filter(prev -> !Objects.equals(prev.getId(), op.getId()))
                .filter(prev -> Objects.equals(prev.getPositionName(), op.getPositionName()))
                .filter(prev -> prev.getSeq() != null && prev.getSeq() > 0 && prev.getSeq() < seq)
                .max(Comparator.comparingInt(ProcessingPositionOperation::getSeq))
                .orElse(null);
        if (predecessor != null && !isDone(predecessor)) {
            throw new BusinessException("OPERATION_SEQUENCE_VIOLATION",
                    "前道工序「" + predecessor.getOperationName() + "」尚未完成"
                            + "（已报 " + nz(predecessor.getDoneQty()).stripTrailingZeros().toPlainString()
                            + "/" + nz(predecessor.getQty()).stripTrailingZeros().toPlainString() + "），"
                            + "不能越过它报「" + op.getOperationName() + "」",
                    422,
                    "请先报工完成「" + predecessor.getOperationName() + "」（本部位第 "
                            + predecessor.getSeq() + " 道工序），再回来报「" + op.getOperationName() + "」");
        }
    }

    /**
     * 防呆③ 数量上限：{@code done_qty + 本次合格数 ≤ qty}。
     *
     * <p><b>选「拒绝 + 可行动 suggestion」而不是 clamp（理由）</b>：
     * ① 报工明细（{@code production_work_logs}）是计件工资的**唯一凭证**且**不可变**（V49 注释：
     *    「明细不可变」）—— clamp 只压 {@code done_qty} 不压明细，同一笔报工会出现
     *    「明细 15 米 / 进度 10 米」的自相矛盾台账，计件金额与进度永久对不上，且**事后无法分辨**
     *    哪边才是真的；拒绝则台账内**恒**满足 {@code Σ合格数 = done_qty}（可对账的不变式）。
     * ② 超报的语义歧义只有工人自己知道（多做了？把「10 套」看成「10 米」？应做数量本身填错？）
     *    —— 静默截断替他做了决定，而**错误的那一半数据已经落库**。
     * ③ 本仓既有口径是 fail-closed + suggestion（{@code BusinessException} 的四参构造、
     *    {@code ClientRequestIdService} 的「不静默返回空 DTO」），拒绝与之一致。</p>
     *
     * <p>作业面「多做了一点」的真实诉求由 suggestion 指路（改应做数量 / 按剩余数量报工），
     * 不靠静默丢数据解决。</p>
     */
    private void assertWithinPlannedQty(ProcessingPositionOperation op, BigDecimal qualifiedQty) {
        BigDecimal planned = nz(op.getQty());
        BigDecimal done = nz(op.getDoneQty());
        BigDecimal remaining = planned.subtract(done);
        if (done.add(qualifiedQty).compareTo(planned) <= 0) {
            return;
        }
        throw new BusinessException("REPORT_QTY_EXCEEDS_PLANNED",
                "报工数量超上限：本次合格 " + qualifiedQty.stripTrailingZeros().toPlainString()
                        + " + 累计已报 " + done.stripTrailingZeros().toPlainString()
                        + " = " + done.add(qualifiedQty).stripTrailingZeros().toPlainString()
                        + " 超过应做 " + planned.stripTrailingZeros().toPlainString()
                        + "（剩余 " + (remaining.signum() < 0 ? "0" : remaining.stripTrailingZeros().toPlainString())
                        + "），本次未落库",
                422,
                "数量可疑，请核对后重报：本次最多可报 " + (remaining.signum() < 0 ? "0" : remaining.stripTrailingZeros().toPlainString())
                        + "（= 应做 " + planned.stripTrailingZeros().toPlainString()
                        + " − 已报 " + done.stripTrailingZeros().toPlainString() + "）；"
                        + "若实际应做数量就是这么多，请先由管理员在工艺路线/工序实例上修正应做数量，再报工");
    }

    /** 必完工序全绿判定（与 M4-G-1 piecework.is_production_done 同口径：无必完工序时判定为真）。 */
    private boolean isMustFinishAllDone(String processingOrderId, Long tenantId) {
        for (ProcessingPositionOperation op : listOperations(processingOrderId, tenantId)) {
            if (Boolean.TRUE.equals(op.getIsMustFinish()) && !isDone(op)) {
                return false;
            }
        }
        return true;
    }

    // ============================================================ 计件

    /**
     * 加工单计件汇总：Σ(合格数量 × 单价 × 系数)，排除返工/报废；单工序一人制。
     * 返回 {total, per_worker: {工人: 金额}, per_operation: [{operation, amount}]}。
     *
     * <p>聚合算法**只有一份**（{@link #aggregate}）：期间报表 {@link #pieceworkSummary} 与
     * 工人计件 {@link #workerPiecework} 共用它 —— 两套实现必然漂移，而验收判据要求
     * 「同一张单的 per-order 合计 = 报表里该单贡献值」。</p>
     */
    public Map<String, Object> piecework(String orderId, Long tenantId) {
        Order order = resolveOrder(orderId, tenantId);
        ProcessingOrder po = processingOrderMapper.selectActiveByOrderId(order.getId(), tenantId);
        if (po == null) {
            return emptyPiecework();
        }
        Map<String, ProcessingPositionOperation> byId = new HashMap<>();
        for (ProcessingPositionOperation op : listOperations(po.getId(), tenantId)) {
            byId.put(op.getId(), op);
        }

        PieceworkTotals totals = aggregate(listWorkLogs(po.getId(), tenantId), byId::get);

        Map<String, Object> perWorkerRounded = new LinkedHashMap<>();
        totals.workerAmount().forEach((worker, amount) -> perWorkerRounded.put(worker, money(amount)));
        List<Map<String, Object>> perOperationList = new ArrayList<>();
        totals.operationAmount().forEach((operation, amount) -> perOperationList.add(
                new LinkedHashMap<>(Map.of("operation", operation, "amount", money(amount)))));

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("total", money(totals.total()));
        result.put("per_worker", perWorkerRounded);
        result.put("per_operation", perOperationList);
        return result;
    }

    /**
     * 计件工资报表（issue #4205，冻结契约）：
     * {@code {period, total, per_worker:[{worker_name, amount, qty}], per_operation:[{operation, amount, qty}]}}。
     *
     * <p>聚合源 = {@code production_work_logs}（{@code work_date} 落在 period 内、{@code work_type=normal}，
     * 返工/报废不计件），算法与 per-order {@link #piecework} **同一份**（见 {@link #aggregate}）。
     * 真值源 §4：「工资报表 = 报工事件聚合（按人/按期/按单下钻）」。{@code worker_name} 是可选下钻维度。</p>
     *
     * <p>工序单价取**实例快照**（{@code processing_position_operations.unit_price}）：改价只影响
     * 新报工，历史报工按当时价（逐笔可追溯，见 {@link ProductionOperationCommandService}）。</p>
     *
     * @param period 必填，YYYY-MM
     */
    public Map<String, Object> pieceworkSummary(String period, String workerName, Long tenantId) {
        YearMonth month = parsePeriod(period, true);
        // 字符串列名（非 Lambda）：期间边界断言需要一个可被 Standalone 单测取 SQL 段的 wrapper
        QueryWrapper<ProductionWorkLog> wrapper = new QueryWrapper<ProductionWorkLog>()
                .eq("tenant_id", tenantId)
                .eq("deleted", 0)
                .ge("work_date", month.atDay(1))
                .le("work_date", month.atEndOfMonth())
                .orderByAsc("work_date");
        if (StringUtils.hasText(workerName)) {
            wrapper.eq("worker_name", workerName.trim());
        }

        PieceworkTotals totals = aggregate(list(wrapper), activeOperationsById(tenantId)::get);

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("period", month.toString());
        result.put("total", money(totals.total()));
        result.put("per_worker", amountAndQtyRows(totals.workerAmount(), totals.workerQty(), "worker_name"));
        result.put("per_operation", amountAndQtyRows(totals.operationAmount(), totals.operationQty(), "operation"));
        return result;
    }

    /**
     * 计件聚合（**per-order 汇总 / 期间报表 / 工人计件共用的唯一算法**）。
     *
     * <p>口径：Σ(合格数量 × 实例快照单价 × 系数)，排除 rework/scrap；实例缺失（已软删）的报工
     * 不计价（不可计价而不是抛错 —— 与既有 per-order 口径一致）。金额逐笔四舍五入到分再累加
     * （与既有实现逐字相同，避免合计出现 0.005 级漂移）。</p>
     *
     * @param operationLookup 工序实例查找（per-order 用「该加工单的活跃实例」，报表用「本租户活跃实例」；
     *                        两处都必须是**活跃**实例，否则同一笔报工在两套端点下取值不同）
     */
    private PieceworkTotals aggregate(List<ProductionWorkLog> logs,
                                      java.util.function.Function<String, ProcessingPositionOperation> operationLookup) {
        Map<String, BigDecimal> workerAmount = new LinkedHashMap<>();
        Map<String, BigDecimal> workerQty = new LinkedHashMap<>();
        Map<String, BigDecimal> operationAmount = new LinkedHashMap<>();
        Map<String, BigDecimal> operationQty = new LinkedHashMap<>();
        BigDecimal total = BigDecimal.ZERO;
        for (ProductionWorkLog log : logs) {
            if (!"normal".equals(log.getWorkType())) {
                continue; // 返工/报废不计件
            }
            ProcessingPositionOperation op = operationLookup.apply(log.getOperationId());
            if (op == null) {
                continue; // 工序实例已不存在（软删）→ 该笔不可计价，跳过而不是抛错
            }
            BigDecimal amount = money(nz(log.getQualifiedQty())
                    .multiply(nz(op.getUnitPrice()))
                    .multiply(op.getFactor() == null ? BigDecimal.ONE : op.getFactor()));
            String worker = StringUtils.hasText(log.getWorkerName()) ? log.getWorkerName() : "未分配";
            String operation = op.getOperationName();
            workerAmount.merge(worker, amount, BigDecimal::add);
            workerQty.merge(worker, nz(log.getQualifiedQty()), BigDecimal::add);
            operationAmount.merge(operation, amount, BigDecimal::add);
            operationQty.merge(operation, nz(log.getQualifiedQty()), BigDecimal::add);
            total = total.add(amount);
        }
        return new PieceworkTotals(total, workerAmount, workerQty, operationAmount, operationQty);
    }

    /** 聚合中间态（金额已逐笔取整；qty 为该维度的合格数量合计）。 */
    private record PieceworkTotals(BigDecimal total,
                                   Map<String, BigDecimal> workerAmount,
                                   Map<String, BigDecimal> workerQty,
                                   Map<String, BigDecimal> operationAmount,
                                   Map<String, BigDecimal> operationQty) {
    }

    /** {name: amount, qty} 行列表（保留首次出现顺序 = work_date 升序，报表可复现）。 */
    private static List<Map<String, Object>> amountAndQtyRows(Map<String, BigDecimal> amounts,
                                                              Map<String, BigDecimal> quantities,
                                                              String nameKey) {
        List<Map<String, Object>> rows = new ArrayList<>();
        amounts.forEach((name, amount) -> {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put(nameKey, name);
            row.put("amount", money(amount));
            row.put("qty", nz(quantities.get(name)));
            rows.add(row);
        });
        return rows;
    }

    /**
     * 全租户**活跃**工序实例按 id 索引（报表用）。
     *
     * <p>判据与 {@link #listOperations}（per-order）一致 = {@code tenant_id + deleted=0}：
     * 若改用 {@code selectById} 逐条查，已软删实例会被算进来 ⇒ 同一笔报工在报表里计价、
     * 在 per-order 里不计价（两套端点数值不等，正是 #4205 验收判据要防的漂移）。</p>
     */
    private Map<String, ProcessingPositionOperation> activeOperationsById(Long tenantId) {
        List<ProcessingPositionOperation> rows = positionOperationMapper.selectList(
                new LambdaQueryWrapper<ProcessingPositionOperation>()
                        .eq(ProcessingPositionOperation::getTenantId, tenantId)
                        .eq(ProcessingPositionOperation::getDeleted, 0));
        Map<String, ProcessingPositionOperation> byId = new HashMap<>();
        if (rows != null) {
            for (ProcessingPositionOperation op : rows) {
                byId.put(op.getId(), op);
            }
        }
        return byId;
    }

    /**
     * 工人计件（米宝查询，冻结契约）：{worker_name, period, total, details:[{operation, qty, amount}]}。
     * period=YYYY-MM 时按 work_date 当月首末（含端点）过滤；返工/报废不计件。
     */
    public Map<String, Object> workerPiecework(String workerName, String period, Long tenantId) {
        if (!StringUtils.hasText(workerName)) {
            throw BusinessException.validationError("worker_name 不能为空");
        }
        YearMonth month = parsePeriod(period, false);
        // 字符串列名（非 Lambda）：期间边界断言需要一个可被 Standalone 单测取 SQL 段的 wrapper
        QueryWrapper<ProductionWorkLog> wrapper = new QueryWrapper<ProductionWorkLog>()
                .eq("tenant_id", tenantId)
                .eq("worker_name", workerName.trim())
                .eq("deleted", 0)
                .orderByAsc("work_date");
        if (month != null) {
            wrapper.ge("work_date", month.atDay(1))
                    .le("work_date", month.atEndOfMonth());
        }

        // 与 per-order 计件 / 期间报表**同一份**聚合（{@link #aggregate}）：金额 = 合格数量 ×
        // 实例快照单价 × 系数，排除返工/报废。工序实例按 id 直查（保持既有 B 端契约口径）。
        PieceworkTotals totals = aggregate(list(wrapper), positionOperationMapper::selectById);

        List<Map<String, Object>> details = new ArrayList<>();
        totals.operationAmount().forEach((operation, amount) -> {
            Map<String, Object> detail = new LinkedHashMap<>();
            detail.put("operation", operation);
            detail.put("qty", nz(totals.operationQty().get(operation)));
            detail.put("amount", money(amount));
            details.add(detail);
        });

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("worker_name", workerName.trim());
        result.put("period", period == null ? "" : period.trim());
        result.put("total", money(totals.total()));
        result.put("details", details);
        return result;
    }

    /**
     * period 解析（YYYY-MM）——工人计件（agent 契约，period 可选）与期间报表（#4205，period 必填）
     * **共用这一份**校验：两处各写一遍必然漂移（一处收 "2026-9"、另一处不收）。
     *
     * @param required 缺失时是否报错（报表的 period 是契约必填项）
     * @return null 仅当 period 为空且 required=false
     */
    private static YearMonth parsePeriod(String period, boolean required) {
        if (!StringUtils.hasText(period)) {
            if (required) {
                throw BusinessException.validationError("period 不能为空（格式 YYYY-MM）");
            }
            return null;
        }
        if (!period.trim().matches("\\d{4}-\\d{2}")) {
            throw BusinessException.validationError("period 格式必须是 YYYY-MM");
        }
        try {
            return YearMonth.parse(period.trim());
        } catch (DateTimeParseException e) {
            throw BusinessException.validationError("period 格式必须是 YYYY-MM");
        }
    }

    // ============================================================ 内部

    private Map<String, Object> emptyPiecework() {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("total", money(BigDecimal.ZERO));
        result.put("per_worker", new LinkedHashMap<>());
        result.put("per_operation", List.of());
        return result;
    }

    /**
     * 订单解析（租户隔离：跨租户/软删视同不存在）。
     *
     * 支持四形态（issue #4005 + #4222——打印的加工单二维码内容是 {@code qr_token}，
     * 若只按内部 order_id 解析，工人扫真码会得到「订单不存在」）：
     * ① 内部 order_id；② 订单号 order_no（手输纸质单号）；③ 加工单 qr_token（打印二维码内容）；
     * ④ 加工单号 processing_order_no（工人端「手输加工单号」兜底路径 + 任务卡上唯一可抄的号，
     * issue #4222）。四级都不中才 404。
     * 用字符串列名而非 Lambda 列名：Standalone MockMvc 单测环境没有 MyBatis-Plus TableInfo 缓存
     * （同本类既有的 UpdateWrapper 做法）。
     */
    private Order resolveOrder(String key, Long tenantId) {
        Order order = orderMapper.selectById(key);
        if (!isResolvable(order, tenantId)) {
            // ② order_no 兜底
            order = orderMapper.selectOne(new QueryWrapper<Order>()
                    .eq("order_no", key)
                    .eq("tenant_id", tenantId)
                    .eq("deleted", 0)
                    .last("LIMIT 1"));
        }
        if (!isResolvable(order, tenantId)) {
            // ③ qr_token 兜底（加工单二维码内容 → 加工单 → 订单）
            ProcessingOrder po = processingOrderMapper.selectOne(new QueryWrapper<ProcessingOrder>()
                    .eq("qr_token", key)
                    .eq("tenant_id", tenantId)
                    .eq("deleted", 0)
                    .last("LIMIT 1"));
            order = po == null ? null : orderMapper.selectById(po.getOrderId());
        }
        if (!isResolvable(order, tenantId)) {
            // ④ processing_order_no 兜底（加工单号 JG-YYYYMMDD-XXXX → 加工单 → 订单，issue #4222）
            //    工人端「或手输加工单号」兜底路径、以及任务卡上唯一可抄的号（text-2xl 加工单号；
            //    qr_token 只以二维码图形呈现、无可读文本）都是**加工单号**，而 ③ 只认 qr_token
            //    ⇒ 只认 ①②③ 时这条 UI 自己要求的输入必然「未找到该加工单」。
            //    与 ③ 同构（同租户 + deleted=0 + LIMIT 1），插在 ③ **之后**：既有三形态优先级不变。
            ProcessingOrder po = processingOrderMapper.selectOne(new QueryWrapper<ProcessingOrder>()
                    .eq("processing_order_no", key)
                    .eq("tenant_id", tenantId)
                    .eq("deleted", 0)
                    .last("LIMIT 1"));
            order = po == null ? null : orderMapper.selectById(po.getOrderId());
        }
        if (!isResolvable(order, tenantId)) {
            throw BusinessException.notFound("订单");
        }
        return order;
    }

    /** 解析结果可用性（非空 + 同租户 + 未软删）。 */
    private boolean isResolvable(Order order, Long tenantId) {
        return order != null
                && tenantId.equals(order.getTenantId())
                && !Integer.valueOf(1).equals(order.getDeleted());
    }

    private List<ProcessingPositionOperation> listOperations(String processingOrderId, Long tenantId) {
        List<ProcessingPositionOperation> operations = positionOperationMapper.selectList(
                new LambdaQueryWrapper<ProcessingPositionOperation>()
                        .eq(ProcessingPositionOperation::getProcessingOrderId, processingOrderId)
                        .eq(ProcessingPositionOperation::getTenantId, tenantId)
                        .eq(ProcessingPositionOperation::getDeleted, 0)
                        .orderByAsc(ProcessingPositionOperation::getPositionName)
                        .orderByAsc(ProcessingPositionOperation::getSeq));
        return operations == null ? List.of() : operations;
    }

    private List<ProductionWorkLog> listWorkLogs(String processingOrderId, Long tenantId) {
        return list(new LambdaQueryWrapper<ProductionWorkLog>()
                .eq(ProductionWorkLog::getProcessingOrderId, processingOrderId)
                .eq(ProductionWorkLog::getTenantId, tenantId)
                .eq(ProductionWorkLog::getDeleted, 0)
                .orderByAsc(ProductionWorkLog::getCreatedAt));
    }

    private List<ProductionWorkLog> list(Wrapper<ProductionWorkLog> wrapper) {
        List<ProductionWorkLog> logs = workLogMapper.selectList(wrapper);
        return logs == null ? List.of() : logs;
    }

    /** 按部位分组的工序树（顺序 = 部位名 / seq，来自 listOperations）。 */
    private List<Map<String, Object>> buildPositions(List<ProcessingPositionOperation> operations) {
        Map<String, List<Map<String, Object>>> grouped = new LinkedHashMap<>();
        Set<String> seen = new HashSet<>();
        for (ProcessingPositionOperation op : operations) {
            String positionName = op.getPositionName() == null ? "" : op.getPositionName();
            seen.add(positionName);
            grouped.computeIfAbsent(positionName, k -> new ArrayList<>()).add(operationView(op));
        }
        List<Map<String, Object>> positions = new ArrayList<>();
        for (String positionName : seen) {
            Map<String, Object> position = new LinkedHashMap<>();
            position.put("position_name", positionName);
            position.put("operations", grouped.get(positionName));
            positions.add(position);
        }
        return positions;
    }

    private Map<String, Object> operationView(ProcessingPositionOperation op) {
        Map<String, Object> view = new LinkedHashMap<>();
        view.put("id", op.getId());
        view.put("seq", op.getSeq());
        view.put("operation", op.getOperationName());
        view.put("group", op.getGroupName());
        view.put("unit", op.getUnit());
        view.put("qty", nz(op.getQty()));
        view.put("qty_source", op.getQtySource());
        view.put("unit_price", nz(op.getUnitPrice()));
        view.put("factor", op.getFactor() == null ? BigDecimal.ONE : op.getFactor());
        view.put("is_must_finish", Boolean.TRUE.equals(op.getIsMustFinish()));
        view.put("is_start_marker", Boolean.TRUE.equals(op.getIsStartMarker()));
        view.put("status", op.getStatus() == null ? "pending" : op.getStatus());
        view.put("done_qty", nz(op.getDoneQty()));
        return view;
    }

    /** 进度：done 以「合格累计 ≥ 应做数量」判定（部分报工置 done 但不算完成）。 */
    private Map<String, Object> progressOf(List<ProcessingPositionOperation> operations) {
        int total = operations.size();
        int done = 0;
        for (ProcessingPositionOperation op : operations) {
            if (isDone(op)) {
                done++;
            }
        }
        Map<String, Object> progress = new LinkedHashMap<>();
        progress.put("total", total);
        progress.put("done", done);
        progress.put("percent", total == 0 ? 0 : (int) Math.round(done * 100.0 / total));
        return progress;
    }

    private boolean isDone(ProcessingPositionOperation op) {
        return nz(op.getDoneQty()).compareTo(nz(op.getQty())) >= 0;
    }

    private static BigDecimal nz(BigDecimal value) {
        return value == null ? BigDecimal.ZERO : value;
    }

    private static BigDecimal money(BigDecimal value) {
        return nz(value).setScale(2, RoundingMode.HALF_UP);
    }

    private static String str(Object value) {
        if (value == null) {
            return null;
        }
        String text = String.valueOf(value).trim();
        return text.isEmpty() ? null : text;
    }

    private static String str(Object value, String defaultValue) {
        String text = str(value);
        return text == null ? defaultValue : text;
    }

    private static boolean flag(Object value) {
        return Boolean.TRUE.equals(value) || "true".equalsIgnoreCase(String.valueOf(value));
    }

    private static BigDecimal bd(Object value, BigDecimal defaultValue) {
        if (value == null) {
            return defaultValue;
        }
        if (value instanceof BigDecimal decimal) {
            return decimal;
        }
        if (value instanceof Number number) {
            return new BigDecimal(number.toString());
        }
        String text = String.valueOf(value).trim();
        if (text.isEmpty()) {
            return defaultValue;
        }
        try {
            return new BigDecimal(text);
        } catch (NumberFormatException e) {
            throw BusinessException.validationError("数量/单价必须是数字: " + text);
        }
    }
}
