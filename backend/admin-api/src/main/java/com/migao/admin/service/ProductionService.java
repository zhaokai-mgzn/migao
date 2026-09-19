package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.UpdateWrapper;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.entity.ProductionWorkLog;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
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
import java.util.LinkedHashSet;
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

    /** 报工人姓名缺省文案（issue #4309）：与工人端报工明细 `log.worker_name || '未署名'` 同文案 */
    private static final String UNSIGNED_WORKER = "未署名";

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
    /**
     * 订单行（工人端规格可见面用，issue #4459 §3.1）：扫码端要显示宽高/工艺/加工类型/用料，
     * 而工序实例只存工序维度（`position_name`/`order_item_id`）⇒ 按 `order_item_id` 回查订单行。
     * **只读**（本类不写订单行）。
     */
    private final OrderItemMapper orderItemMapper;
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
                    // 主定位键（V69，issue #4388）：来自 payload；派生路径（无快照行）缺键 ⇒ null
                    .orderItemId(spec.orderItemId())
                    .positionKind(spec.positionKind())
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
                        // 主定位键（issue #4388）：缺键 ⇒ null（存量/派生 payload 不编值）
                        str(position.get("order_item_id")),
                        str(position.get("position_kind")),
                        op.get("seq") == null ? seq : bd(op.get("seq"), BigDecimal.valueOf(seq)).intValue(),
                        operationName,
                        str(op.get("group")),
                        str(op.get("unit")),
                        bd(op.get("qty"), BigDecimal.ZERO),
                        bd(op.get("unit_price"), BigDecimal.ZERO),
                        // `factor` 列**保留**但自 #4589 起无人写它：实例化 payload 不再带该键
                        // （ProcessingOrderService 已删 applyFactors）⇒ 恒取默认 1。历史实例的
                        // 旧值原样留着（那是当时工资的证据），签名比较也照旧参与 ⇒ 不回溯。
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
            specs.add(new OpSpec(op.getPositionName(),
                    op.getOrderItemId(), op.getPositionKind(),
                    op.getSeq() == null ? 0 : op.getSeq(),
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

    /**
     * 工序实例归一化形态：字段集 = 落库字段集（比较用的最小充分集）。
     *
     * <p>🔴 <b>{@code orderItemId} / {@code positionKind}（V69，issue #4388）刻意<u>不进</u> {@link #signature()}</b>
     * —— 实测依据：把它们算进签名后，`ProductionControllerTest#instantiateDerivedIsIdempotentWhenInstancesAlreadyExist`
     * 立刻变红（`NeverWantedButInvoked`：对**存量实例集**（`order_item_id` 为 NULL）重新实例化时，
     * 新 payload 带行标识 ⇒ 签名不等 ⇒ 判为「工序配置变更」⇒ **软删重插、报工进度清零**）。</p>
     *
     * <p>语义上也应如此：签名比较的是**工序配置**（部位名/序号/工序/单位/数量/单价/系数/标记），
     * 而 {@code order_item_id} 是**定位元数据**（这条实例属于哪一行）—— 存量行补不补行标识
     * 不该让「同一套工序」被当成另一套（#4116 的幂等保证：重复实例化不重插、进度不清零）。</p>
     */
    private record OpSpec(String positionName, String orderItemId, String positionKind,
                          int seq, String operationName, String groupName, String unit,
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
        // 报工人（issue #4309）：**一次**取回报工记录再内存分组 —— 按工序逐个查是 N+1（#4304 同族）
        List<ProductionWorkLog> logs = po == null
                ? List.of()
                : listWorkLogs(po.getId(), tenantId);
        Map<String, List<String>> workers = po == null ? Map.of() : workersByOperation(logs);

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("order_id", order.getId());
        result.put("qr_token", po == null ? null : po.getQrToken());
        result.put("positions", buildPositions(operations, workers, orderSpecByItemId(order, tenantId)));
        result.put("progress", progressOf(operations));
        // 操作记录（issue #4347 §3.2）：**服务端**报工流水，不是本机缓存。
        // 工人端原来只显示本机 storage 里的报工（换设备就没了，也看不到别人做的工序）；
        // 而截图里的「操作记录」是**全单流水**（谁、哪道、多少、何时）。
        result.put("work_logs", workLogViews(logs, positionKindByOperationName(operations)));
        return result;
    }

    /**
     * 报工流水（操作记录）的展示形态（issue #4347 §3.2）。
     *
     * <p>真值源 §5：「操作记录 = 报工明细（实证：{@code 蒋雪云-定型 11.00}… 带时间戳）」。</p>
     *
     * <p>口径：① **倒序**（最近的在最上面 —— 工人关心「我刚报的进去了没有」）；
     * ② 字段是**展示面**，不参与计价（计价只读 {@code production_work_logs} 的快照列）；
     * ③ 时间用 {@code createdAt}（落库时刻），不用 {@code workDate}（业务日期，补报会改它）。</p>
     */
    private List<Map<String, Object>> workLogViews(List<ProductionWorkLog> logs,
                                                   Map<String, String> positionKindByName) {
        List<Map<String, Object>> views = new ArrayList<>();
        if (logs == null) {
            return views;
        }
        for (int i = logs.size() - 1; i >= 0; i--) {
            ProductionWorkLog log = logs.get(i);
            Map<String, Object> view = new LinkedHashMap<>();
            String operationName = StringUtils.hasText(log.getOperationName())
                    ? log.getOperationName() : "未命名工序";
            // ⚠️ `operation_name` = **工人端快照名**（变体名 `精裁-布`）：历史数据与其它消费者仍要读它，
            // **一字不动**；**web 界面不得渲染该键**（issue #4621）—— 界面显示下面的
            // `logical_name` + `position`（读时派生、**不写库**）。
            view.put("operation_name", operationName);
            view.put("logical_name", ProductionOperationQueryService.logicalOperationName(operationName));
            view.put("position", ProductionOperationQueryService.displayPosition(
                    operationName, positionKindByName.get(operationName)));
            view.put("worker_name", StringUtils.hasText(log.getWorkerName())
                    ? log.getWorkerName() : UNSIGNED_WORKER);
            view.put("qualified_qty", nz(log.getQualifiedQty()));
            view.put("work_type", log.getWorkType());
            // 显式 ISO-8601（带秒）：`OffsetDateTime.toString()` 在秒为 0 时会**省略秒**
            // （`…T02:00Z`）⇒ 前端 `Date.parse` 与逐字断言都要处理两种形态。钉死格式更省事。
            view.put("created_at", log.getCreatedAt() == null
                    ? null : log.getCreatedAt().format(java.time.format.DateTimeFormatter.ISO_OFFSET_DATE_TIME));
            views.add(view);
        }
        return views;
    }

    /**
     * 订单行规格按 `order_items.id` 索引（工人端规格可见面，issue #4459 §3.1）。
     *
     * <p><b>为什么回查订单行而不是存在工序实例上</b>：规格是**订单侧的真值**（V63 列 + 算料输出），
     * 在工序实例上再存一份就是第二份口径（漂移的那一份不会变红）。工序实例已带
     * `order_item_id`（V69 / #4388 主定位键）⇒ 按它回查即可，**零迁移**。</p>
     *
     * <p><b>只读、不重算</b>：算料输出（`fabric_meters` / `processingMeters`）逐字取
     * `processing_info` 里已落的值 —— 算料单一真值是 ai-agent 的引擎，Java 侧不复制第二份逻辑。</p>
     */
    private Map<String, Map<String, Object>> orderSpecByItemId(Order order, Long tenantId) {
        List<OrderItem> items = orderItemMapper.selectList(new LambdaQueryWrapper<OrderItem>()
                .eq(OrderItem::getOrderId, order.getId())
                .eq(OrderItem::getTenantId, tenantId)
                .eq(OrderItem::getDeleted, 0));
        Map<String, Map<String, Object>> byId = new LinkedHashMap<>();
        if (items == null) {
            return byId;
        }
        for (OrderItem item : items) {
            Map<String, Object> spec = new LinkedHashMap<>();
            spec.put("product_name", item.getProductName());
            // 宽/高：V63 列（下单页必填，issue #4420 起真的会写）
            spec.put("width", item.getWidth());
            spec.put("height", item.getHeight());
            // 工艺规格：**唯一映射点**（OrderLineCraftFields）—— 不在此另写一份键名翻译
            spec.putAll(OrderLineCraftFields.toSnapshotKeys(item));
            // 算料输出（单一真值 = ai-agent 引擎）：逐字取 processing_info 里已落的值
            Map<String, Object> pi = OrderLineCraftFields.normalize(item.getProcessingInfo());
            if (pi != null) {
                for (String key : OrderLineCraftFields.CALC_OUTPUT_SNAPSHOT_KEYS) {
                    if (pi.containsKey(key)) {
                        spec.put(key, pi.get(key));
                    }
                }
            }
            byId.put(item.getId(), spec);
        }
        return byId;
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
                // 计件金额在**报工这一刻固化**（issue #4351，P0）：单价从工序实例取一次
                // 写进报工自己的快照 ⇒ 聚合永不回查实例。重新实例化（工艺变更/存量单补工序）
                // 会软删旧实例并重插，回查实例会让工人已做的活的钱静默消失。
                // 系数快照**不再写**（issue #4589）：计件 = 数量 × 单价，系数已从算法退场。
                .unitPrice(op.getUnitPrice())
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
        // 下钻维度（真值源 §4 的下钻链：部位 → 套）。**同一份聚合**产出 ⇒
        // 各维合计恒等于 total（判据：下钻合计 === 总额）。
        result.put("per_position", amountAndQtyRows(totals.positionAmount(), totals.positionQty(), "position_name"));
        result.put("per_set", amountAndQtyRows(totals.setAmount(), totals.setQty(), "order_item_id"));
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

        Map<String, ProcessingPositionOperation> instancesById = activeOperationsById(tenantId);
        PieceworkTotals totals = aggregate(list(wrapper), instancesById::get);

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("period", month.toString());
        result.put("total", money(totals.total()));
        result.put("per_worker", amountAndQtyRows(totals.workerAmount(), totals.workerQty(), "worker_name"));
        // 按工序明细（issue #4621）：每项**追加** `logical_name` + `position` 供 web 界面渲染
        // 「逻辑名 · 部位」；`operation`（工人端快照名 = 变体名）**一字不动**（其它消费者仍要读它）。
        // 分组口径不变：仍是「每个工序实例一行」（`精裁 · 布帘` / `精裁 · 纱帘` 各一行）。
        result.put("per_operation", operationPieceworkRows(totals.operationAmount(), totals.operationQty(),
                positionKindByOperationName(instancesById.values())));
        // 下钻维度（真值源 §4：「按人/按期/按单下钻」+ 部位 / 套）。与 per-order 汇总**同一份聚合**
        // ⇒ 报表里某维合计 = 该维在各单上的贡献之和（不会出现两套口径漂移）。
        result.put("per_position", amountAndQtyRows(totals.positionAmount(), totals.positionQty(), "position_name"));
        result.put("per_set", amountAndQtyRows(totals.setAmount(), totals.setQty(), "order_item_id"));
        return result;
    }

    /**
     * 计件聚合（**per-order 汇总 / 期间报表 / 工人计件共用的唯一算法**）。
     *
     * <p>口径：Σ(合格数量 × **报工自己的单价快照**)，排除 rework/scrap —— 系数**不参与**
     * （issue #4589 用户裁定：计件工资 = 数量 × 计件单价）。
     * 金额逐笔四舍五入到分再累加（与既有实现逐字相同，避免合计出现 0.005 级漂移）。</p>
     *
     * <p><b>金额在报工那一刻固化（issue #4351，P0）</b>：金额只读 {@code production_work_logs}
     * 的 {@code unit_price} 快照，**永不依赖工序实例是否还在**。原实现回查实例
     * （{@code operationLookup}）算金额，而重新实例化（{@code POST /production/orders/{orderId}/
     * instantiate}，工艺变更 / 存量单补工序）会**软删旧实例并重插** ⇒ 旧报工指向已软删实例 ⇒
     * 被跳过 ⇒ 工人已做的活的钱从合计里消失**且不报错**。真值源 §4 要的是「逐笔可追溯」
     * （调价只影响新报工，历史报工按当时价）——回查实例做不到这一点，快照才做得到。</p>
     *
     * <p><b>系数按「当时快照」继续算（issue #4604，用户裁定 B：不追溯）</b>：
     * {@code production_work_logs.factor} 列**保留**（历史报工上它是当时工资的证据），
     * 且**历史报工照旧乘它**（快照 {@code 1.70} 的「一分二」活仍是 1.7×）⇒ 历史金额**一字不变**；
     * #4589 起新报工**不再写** {@code factor} ⇒ 快照恒 {@code NULL} ⇒ 系数取 1 ⇒ 以后不乘。</p>
     *
     * <p>⚠️ 金额是**读时计算**的（本表没有金额列）⇒ 「落库数据没动」**不等于**「历史不回溯」：
     * 把系数从读时算法里拿掉，历史金额会立刻从 1.7× 掉到 1×（呈现/结算值变了）。
     * 「不追溯」只能靠**读时仍按快照算**来兑现，而不是靠不写回填脚本。</p>
     *
     * <p>实例回查只剩两个**展示/兜底**用途：① 工序名（快照缺失时用报工自己的
     * {@code operation_name}）；② **存量报工**（{@code unit_price} 为 {@code NULL} = V61 之前的行）
     * 仍按实例回查计价 —— 否则本列一引入，历史工资反而全部归零。
     * 「查不到就 {@code continue}」的兜底**保留**：既无快照、实例又真的不存在（脏数据）时
     * 该笔不可计价，跳过而不是抛错（整张报表不得因一条脏数据中断）。</p>
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
        // 下钻维度（真值源 §4：报工 → 工序实例 → **部位** → **套** → 加工单 → 订单）。
        // 数据取自**工序实例**（`position_name` / `order_item_id`），**不改 production_work_logs**
        // （P2b 明列「不做」；V61 快照口径已冻结）。存量报工若实例已不存在 ⇒ 归「未知部位」，
        // 不跳过（跳过会让下钻合计 ≠ 总额 —— 那正是「可核对」的判据）。
        Map<String, BigDecimal> positionAmount = new LinkedHashMap<>();
        Map<String, BigDecimal> positionQty = new LinkedHashMap<>();
        Map<String, BigDecimal> setAmount = new LinkedHashMap<>();
        Map<String, BigDecimal> setQty = new LinkedHashMap<>();
        BigDecimal total = BigDecimal.ZERO;
        for (ProductionWorkLog log : logs) {
            if (!"normal".equals(log.getWorkType())) {
                continue; // 返工/报废不计件
            }
            boolean hasSnapshot = log.getUnitPrice() != null;
            ProcessingPositionOperation op = operationLookup.apply(log.getOperationId());
            if (!hasSnapshot && op == null) {
                continue; // 既无快照、实例又真的不存在（脏数据）→ 该笔不可计价，跳过而不是抛错
            }
            BigDecimal unitPrice = hasSnapshot ? log.getUnitPrice() : op.getUnitPrice();
            // 系数取**当时快照**（issue #4604，用户裁定 B：不追溯）—— 有单价快照时读报工自己的
            // `factor`（历史报工仍 1.7×），缺快照的存量报工才回落实例；`factor` 为 NULL ⇒ 取 1。
            // #4589 起新报工不再写 `factor` ⇒ 快照恒 NULL ⇒ 新报工自然 1×（不再产生非 1 系数）。
            BigDecimal factor = hasSnapshot
                    ? (log.getFactor() == null ? BigDecimal.ONE : log.getFactor())
                    : (op.getFactor() == null ? BigDecimal.ONE : op.getFactor());
            BigDecimal amount = money(nz(log.getQualifiedQty())
                    .multiply(nz(unitPrice))
                    .multiply(factor));
            String worker = StringUtils.hasText(log.getWorkerName()) ? log.getWorkerName() : "未分配";
            // 工序名 = 展示字段：优先报工自身的快照（报工时已落库），缺失时回查实例
            String operation = StringUtils.hasText(log.getOperationName())
                    ? log.getOperationName()
                    : (op == null ? null : op.getOperationName());
            if (!StringUtils.hasText(operation)) {
                operation = "未命名工序";
            }
            // 部位维度：实例的 position_name（展示名）；无实例 ⇒ 「未知部位」（不猜、不跳过）
            String position = op == null || !StringUtils.hasText(op.getPositionName())
                    ? "未知部位" : op.getPositionName();
            // 套维度：实例的 order_item_id 即该樘窗/套的订单行（V69 / issue #4388 主定位键）
            String set = op == null || !StringUtils.hasText(op.getOrderItemId())
                    ? "未知套" : op.getOrderItemId();
            workerAmount.merge(worker, amount, BigDecimal::add);
            workerQty.merge(worker, nz(log.getQualifiedQty()), BigDecimal::add);
            operationAmount.merge(operation, amount, BigDecimal::add);
            operationQty.merge(operation, nz(log.getQualifiedQty()), BigDecimal::add);
            positionAmount.merge(position, amount, BigDecimal::add);
            positionQty.merge(position, nz(log.getQualifiedQty()), BigDecimal::add);
            setAmount.merge(set, amount, BigDecimal::add);
            setQty.merge(set, nz(log.getQualifiedQty()), BigDecimal::add);
            total = total.add(amount);
        }
        return new PieceworkTotals(total, workerAmount, workerQty, operationAmount, operationQty,
                positionAmount, positionQty, setAmount, setQty);
    }

    /** 聚合中间态（金额已逐笔取整；qty 为该维度的合格数量合计）。 */
    private record PieceworkTotals(BigDecimal total,
                                   Map<String, BigDecimal> workerAmount,
                                   Map<String, BigDecimal> workerQty,
                                   Map<String, BigDecimal> operationAmount,
                                   Map<String, BigDecimal> operationQty,
                                   Map<String, BigDecimal> positionAmount,
                                   Map<String, BigDecimal> positionQty,
                                   Map<String, BigDecimal> setAmount,
                                   Map<String, BigDecimal> setQty) {
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
     * 工序名 → 部位种类（issue #4621）：报工快照（{@code production_work_logs}）**没有部位列**
     * ⇒ 部位只能从**工序实例**带出（{@code position_kind}）。缺失即缺（**不猜**、不编值）——
     * 界面按「只有逻辑名」渲染。
     */
    private static Map<String, String> positionKindByOperationName(
            java.util.Collection<ProcessingPositionOperation> operations) {
        Map<String, String> byName = new HashMap<>();
        for (ProcessingPositionOperation op : operations) {
            if (op != null && StringUtils.hasText(op.getOperationName())
                    && StringUtils.hasText(op.getPositionKind())) {
                byName.putIfAbsent(op.getOperationName(), op.getPositionKind());
            }
        }
        return byName;
    }

    /**
     * 计件「按工序」明细行（issue #4621）：在既有 {@code {operation, qty, amount}} 上**追加**
     * {@code logical_name} + {@code position}（既有键名/含义**一字不改**）。
     *
     * <p>⚠️ {@code operation} = **工人端快照名**（变体名 {@code 精裁-布}）：它是历史快照名、
     * 其它消费者仍要读它 ⇒ 保留；但 **web 界面不得渲染该键** —— 界面显示
     * {@code logical_name} + {@code position}，两者都是**读时派生**（逻辑名走既有映射
     * {@link ProductionOperationQueryService#logicalOperationName}，部位从工序实例带出），
     * **不写库**。缺 {@code logical_name}（老数据 / 自建工序）⇒ 前端退回 {@code operation} 原文。</p>
     */
    private static List<Map<String, Object>> operationPieceworkRows(
            Map<String, BigDecimal> amount, Map<String, BigDecimal> qty,
            Map<String, String> positionKindByName) {
        List<Map<String, Object>> rows = new ArrayList<>();
        amount.forEach((operation, value) -> {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("operation", operation);
            row.put("logical_name", ProductionOperationQueryService.logicalOperationName(operation));
            row.put("position", ProductionOperationQueryService.displayPosition(
                    operation, positionKindByName.get(operation)));
            row.put("qty", nz(qty.get(operation)));
            row.put("amount", money(value));
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
        // 部位（issue #4621）：报工快照**没有部位列** ⇒ 从**同一次实例回查**里带出
        // （不额外查库、不猜）—— 只为给 web 界面拼「逻辑名 · 部位」，**不写库**。
        Map<String, String> positionKindByName = new HashMap<>();
        PieceworkTotals totals = aggregate(list(wrapper), operationId -> {
            ProcessingPositionOperation op = positionOperationMapper.selectById(operationId);
            if (op != null && StringUtils.hasText(op.getOperationName())
                    && StringUtils.hasText(op.getPositionKind())) {
                positionKindByName.putIfAbsent(op.getOperationName(), op.getPositionKind());
            }
            return op;
        });

        List<Map<String, Object>> details =
                operationPieceworkRows(totals.operationAmount(), totals.operationQty(), positionKindByName);

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
        // 空态也带齐下钻维度：键的**在场性**恒定 ⇒ 前端不必为「有没有这个键」写分支
        result.put("per_position", List.of());
        result.put("per_set", List.of());
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

    /**
     * 按部位分组的工序树（顺序 = 部位名 / seq，来自 listOperations）。
     *
     * <p><b>分组键 = 工序实例的<u>主定位键</u>（issue #4388 / #4373 裁定）</b>：
     * `order_item_id` 优先 —— {@code position_name} 是**展示名**（加工产物名[+色号]），
     * **同商品同色号的两个窗会同名** ⇒ 只按名字分组会把两个部位**并成一个**
     * （工人扫码/加工单详情看到「一个部位 22 道工序」，而实际是「两个部位各 11 道」）。</p>
     *
     * <p>⚠️ <b>存量单兼容</b>：V69 之前生成的实例行没有 {@code order_item_id}
     * ⇒ 回落 {@code position_name} 分组 ⇒ **读面行为逐字不变**（不猜、不编值）。</p>
     */
    private List<Map<String, Object>> buildPositions(List<ProcessingPositionOperation> operations,
                                                     Map<String, List<String>> workersByOperation,
                                                     Map<String, Map<String, Object>> specByItemId) {
        Map<String, List<Map<String, Object>>> grouped = new LinkedHashMap<>();
        Map<String, ProcessingPositionOperation> headByKey = new LinkedHashMap<>();
        Set<String> seen = new HashSet<>();
        for (ProcessingPositionOperation op : operations) {
            String key = StringUtils.hasText(op.getOrderItemId())
                    ? op.getOrderItemId()
                    : (op.getPositionName() == null ? "" : op.getPositionName());
            seen.add(key);
            headByKey.putIfAbsent(key, op);
            grouped.computeIfAbsent(key, k -> new ArrayList<>())
                    .add(operationView(op, workersByOperation.getOrDefault(op.getId(), List.of())));
        }
        List<Map<String, Object>> positions = new ArrayList<>();
        for (String key : seen) {
            ProcessingPositionOperation head = headByKey.get(key);
            Map<String, Object> position = new LinkedHashMap<>();
            position.put("position_name", head.getPositionName() == null ? "" : head.getPositionName());
            // 行标识（issue #4388）：前端据此区分**同名**部位；存量行如实 null（不编值）
            position.put("order_item_id", head.getOrderItemId());
            position.put("position_kind", head.getPositionKind());
            // 规格可见面（issue #4459 §3.1）：工人要能核对自己做的是哪一件 —— 宽高/工艺/加工类型/
            // 褶倍/部位定型/用料。**逐字取订单行**（缺键就缺，不补默认值）；订单行已不在（脏数据）
            // ⇒ 一个键都不加，前端按缺键渲染（不冒充已知）。
            Map<String, Object> spec = head.getOrderItemId() == null
                    ? null : specByItemId.get(head.getOrderItemId());
            if (spec != null) {
                position.putAll(spec);
            }
            position.put("operations", grouped.get(key));
            positions.add(position);
        }
        return positions;
    }

    /**
     * 报工人（issue #4309）：工序实例 → 报过工的人。
     *
     * <p>只取 {@code work_type='normal'}（与「已完成数量 / 计件」同源：返工/报废既不推进进度
     * 也不计件，混进来会让相邻两列不同口径）；按**首次报工时间**升序去重 —— {@link #listWorkLogs}
     * 已按 {@code created_at} 升序，故按遇到顺序去重即为首次报工序；{@code worker_name} 空/blank
     * 统一「未署名」（与工人端报工明细同文案）。无 normal 报工 ⇒ 空数组（前端渲染「—」）。
     */
    private Map<String, List<String>> workersByOperation(List<ProductionWorkLog> logs) {
        Map<String, LinkedHashSet<String>> grouped = new HashMap<>();
        for (ProductionWorkLog log : logs) {
            if (!"normal".equals(log.getWorkType()) || log.getOperationId() == null) {
                continue;
            }
            String name = StringUtils.hasText(log.getWorkerName())
                    ? log.getWorkerName().trim()
                    : UNSIGNED_WORKER;
            grouped.computeIfAbsent(log.getOperationId(), k -> new LinkedHashSet<>()).add(name);
        }
        Map<String, List<String>> result = new HashMap<>();
        grouped.forEach((operationId, names) -> result.put(operationId, List.copyOf(names)));
        return result;
    }

    private Map<String, Object> operationView(ProcessingPositionOperation op, List<String> workers) {
        Map<String, Object> view = new LinkedHashMap<>();
        view.put("id", op.getId());
        view.put("seq", op.getSeq());
        // ⚠️ `operation` = **工人端快照名**（变体名 `精裁-布`）：历史数据与其它消费者仍要读它，
        // **一字不动**；**web 界面不得渲染该键**（issue #4621）—— 界面显示下面的
        // `logical_name` + `position`（读时派生、**不写库**）。
        view.put("operation", op.getOperationName());
        view.put("logical_name", ProductionOperationQueryService.logicalOperationName(op.getOperationName()));
        view.put("position", ProductionOperationQueryService.displayPosition(
                op.getOperationName(), op.getPositionKind()));
        view.put("group", op.getGroupName());
        view.put("unit", op.getUnit());
        view.put("qty", nz(op.getQty()));
        view.put("qty_source", op.getQtySource());
        view.put("unit_price", nz(op.getUnitPrice()));
        // 不再返回 `factor`（issue #4589）：系数已从算法退场，回传会让界面显示一个
        // 「有值却不算钱」的数（新的静默不一致）。DB 列与历史快照保留，只是不上读面。
        view.put("is_must_finish", Boolean.TRUE.equals(op.getIsMustFinish()));
        view.put("is_start_marker", Boolean.TRUE.equals(op.getIsStartMarker()));
        view.put("status", op.getStatus() == null ? "pending" : op.getStatus());
        view.put("done_qty", nz(op.getDoneQty()));
        // 追加键（issue #4309）：既有键名/含义/顺序一字不改
        view.put("workers", workers);
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
