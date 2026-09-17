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
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

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

    // ============================================================ 实例化

    /**
     * 实例化工序（加工单 × 部位 × 工序）+ 生成加工单二维码 token。
     * 幂等：同一加工单重复实例化时软删旧实例（保留审计），已有 token 复用（已打印的码不失效）。
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
        // 重新实例化：旧实例软删（工序序列可能随工艺变更，历史报工仍按实例快照可追溯）
        // 用字符串列名而非 Lambda 列名：LambdaUpdateWrapper.set 会立即求值列名，Standalone
        // MockMvc 单测环境没有 MyBatis-Plus TableInfo 缓存（同 SettingsController 的既有做法）。
        positionOperationMapper.update(null, new UpdateWrapper<ProcessingPositionOperation>()
                .eq("processing_order_id", po.getId())
                .eq("tenant_id", tenantId)
                .eq("deleted", 0)
                .set("deleted", 1)
                .set("updated_at", OffsetDateTime.now()));

        int count = 0;
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
                positionOperationMapper.insert(ProcessingPositionOperation.builder()
                        .tenantId(tenantId)
                        .processingOrderId(po.getId())
                        .positionName(positionName)
                        .seq(op.get("seq") == null ? seq : bd(op.get("seq"), BigDecimal.valueOf(seq)).intValue())
                        .operationName(operationName)
                        .groupName(str(op.get("group")))
                        .unit(str(op.get("unit")))
                        .qty(bd(op.get("qty"), BigDecimal.ZERO))
                        .unitPrice(bd(op.get("unit_price"), BigDecimal.ZERO))
                        .factor(bd(op.get("factor"), BigDecimal.ONE))
                        .isMustFinish(flag(op.get("is_must_finish")))
                        .isStartMarker(flag(op.get("is_start_marker")))
                        .status("pending")
                        .doneQty(BigDecimal.ZERO)
                        .createdAt(OffsetDateTime.now())
                        .updatedAt(OffsetDateTime.now())
                        .deleted(0)
                        .build());
                count++;
                seq++;
            }
        }

        String qrToken = StringUtils.hasText(po.getQrToken())
                ? po.getQrToken()
                : UUID.randomUUID().toString().replace("-", "");
        if (!qrToken.equals(po.getQrToken())) {
            processingOrderMapper.updateById(ProcessingOrder.builder().id(po.getId()).qrToken(qrToken).build());
        }
        log.info("实例化工序: po={}, orderId={}, operations={}, qrToken={}",
                po.getProcessingOrderNo(), order.getId(), count, qrToken);

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("qr_token", qrToken);
        result.put("operation_count", count);
        return result;
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
     * order_id → order_no → qr_token 三形态，**不得只认 order_no** —— agent 侧拿到的是
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
     * 扫码报工：落报工明细（三态）→ 正常报工累加 done_qty 并置 done
     * → 必完工序全绿则**加工单**置 completed（订单状态不动，见方法内注释）。
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> report(String orderId, String operationId,
                                      Map<String, Object> body, Long tenantId) {
        Order order = resolveOrder(orderId, tenantId);
        ProcessingOrder po = processingOrderMapper.selectActiveByOrderId(order.getId(), tenantId);
        if (po == null) {
            throw BusinessException.validationError(
                    "订单 " + order.getOrderNo() + " 尚无加工单，无法报工");
        }
        ProcessingPositionOperation op = positionOperationMapper.selectById(operationId);
        if (op == null || !tenantId.equals(op.getTenantId()) || Integer.valueOf(1).equals(op.getDeleted())
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
        boolean advances = "normal".equals(workType) && qualifiedQty.signum() > 0;
        if (advances) {
            doneQty = doneQty.add(qualifiedQty);
            status = "done";
            positionOperationMapper.updateById(ProcessingPositionOperation.builder()
                    .id(op.getId())
                    .doneQty(doneQty)
                    .status(status)
                    .updatedAt(OffsetDateTime.now())
                    .build());
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

        Map<String, BigDecimal> perWorker = new LinkedHashMap<>();
        Map<String, BigDecimal> perOperation = new LinkedHashMap<>();
        BigDecimal total = BigDecimal.ZERO;
        for (ProductionWorkLog log : listWorkLogs(po.getId(), tenantId)) {
            if (!"normal".equals(log.getWorkType())) {
                continue; // 返工/报废不计件
            }
            ProcessingPositionOperation op = byId.get(log.getOperationId());
            if (op == null) {
                continue; // 工序实例已不存在（软删）→ 该笔不可计价，跳过而不是抛错
            }
            BigDecimal amount = money(nz(log.getQualifiedQty())
                    .multiply(nz(op.getUnitPrice()))
                    .multiply(op.getFactor() == null ? BigDecimal.ONE : op.getFactor()));
            perWorker.merge(StringUtils.hasText(log.getWorkerName()) ? log.getWorkerName() : "未分配",
                    amount, BigDecimal::add);
            perOperation.merge(op.getOperationName(), amount, BigDecimal::add);
            total = total.add(amount);
        }

        Map<String, Object> perWorkerRounded = new LinkedHashMap<>();
        perWorker.forEach((worker, amount) -> perWorkerRounded.put(worker, money(amount)));
        List<Map<String, Object>> perOperationList = new ArrayList<>();
        perOperation.forEach((operation, amount) -> perOperationList.add(
                new LinkedHashMap<>(Map.of("operation", operation, "amount", money(amount)))));

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("total", money(total));
        result.put("per_worker", perWorkerRounded);
        result.put("per_operation", perOperationList);
        return result;
    }

    /**
     * 工人计件（米宝查询，冻结契约）：{worker_name, period, total, details:[{operation, qty, amount}]}。
     * period=YYYY-MM 时按 work_date 当月首末（含端点）过滤；返工/报废不计件。
     */
    public Map<String, Object> workerPiecework(String workerName, String period, Long tenantId) {
        if (!StringUtils.hasText(workerName)) {
            throw BusinessException.validationError("worker_name 不能为空");
        }
        YearMonth month = null;
        if (StringUtils.hasText(period)) {
            if (!period.trim().matches("\\d{4}-\\d{2}")) {
                throw BusinessException.validationError("period 格式必须是 YYYY-MM");
            }
            try {
                month = YearMonth.parse(period.trim());
            } catch (DateTimeParseException e) {
                throw BusinessException.validationError("period 格式必须是 YYYY-MM");
            }
        }
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

        Map<String, BigDecimal> qtyByOperation = new LinkedHashMap<>();
        Map<String, BigDecimal> amountByOperation = new LinkedHashMap<>();
        BigDecimal total = BigDecimal.ZERO;
        for (ProductionWorkLog log : list(wrapper)) {
            if (!"normal".equals(log.getWorkType())) {
                continue;
            }
            ProcessingPositionOperation op = positionOperationMapper.selectById(log.getOperationId());
            if (op == null) {
                continue;
            }
            BigDecimal amount = money(nz(log.getQualifiedQty())
                    .multiply(nz(op.getUnitPrice()))
                    .multiply(op.getFactor() == null ? BigDecimal.ONE : op.getFactor()));
            String key = StringUtils.hasText(log.getOperationName()) ? log.getOperationName() : op.getOperationName();
            qtyByOperation.merge(key, nz(log.getQualifiedQty()), BigDecimal::add);
            amountByOperation.merge(key, amount, BigDecimal::add);
            total = total.add(amount);
        }

        List<Map<String, Object>> details = new ArrayList<>();
        qtyByOperation.forEach((operation, qty) -> details.add(new LinkedHashMap<>(Map.of(
                "operation", operation,
                "qty", qty,
                "amount", money(amountByOperation.getOrDefault(operation, BigDecimal.ZERO))))));

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("worker_name", workerName.trim());
        result.put("period", period == null ? "" : period.trim());
        result.put("total", money(total));
        result.put("details", details);
        return result;
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
     * 支持三形态（issue #4005——打印的加工单二维码内容是 {@code qr_token}，
     * 若只按内部 order_id 解析，工人扫真码会得到「订单不存在」）：
     * ① 内部 order_id；② 订单号 order_no（手输纸质单号）；③ 加工单 qr_token（打印二维码内容）。
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
