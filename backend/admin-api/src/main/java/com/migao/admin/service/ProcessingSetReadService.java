package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingOrderSet;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingOrderSetMapper;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 加工套件**只读面**（issue #5247 的 admin-api 半边；设计
 * {@code docs/design/set-code-and-scan-loop.md} §2 / §4.1 / §5.3.2）。
 *
 * <h2>🔴 单一口径：本类是全仓**唯一**一份「套 → 部位 → 工序」聚合</h2>
 * <p>{@link #setOverview} 不是新写的 —— 它是 issue #4967（交付物 2）落在
 * {@code ProductionScanService} 里的那份实现，本单**原样搬到这里**，并由
 * {@code ProductionScanService} 反向依赖本类（见其构造参数 {@code processingSetReadService}）。
 * 因此：<b>改这里一处 ⇒ 工人扫码面（{@code GET /api/admin/production/scan} 与
 * {@code GET /api/worker/production/scan} 的 {@code set_overview} 键）与商家/agent 读面
 * （{@code GET /api/admin/processing-order-sets/{id}} 的 {@code set_overview} 键）同时变</b>。</p>
 * <p>为什么不各写一份：套内「哪几个部位、每个部位哪几道工序、显示名怎么取、按什么排序、算不算已完成」
 * 只要有两份实现，两处迟早不同（页面看到的「还有几道没做」与工人屏上的会打架，而工人据此领活、
 * 据此计件）。判据见 {@code ProcessingSetReadServiceTest}（同一份聚合的两消费者等价 + 注入式：
 * 单点改聚合 ⇒ 两侧同变）与 {@code ProductionScanServiceTest} / {@code ProductionScanCompleteServiceTest}
 * 的既有 {@code set_overview} 断言。</p>
 *
 * <h2>三个只读端点（issue #5247 交付物）</h2>
 * <ol>
 *   <li>{@link #listSets} —— 套件列表（按 {@code orderNo} / {@code processingOrderNo} 过滤 + 分页）；</li>
 *   <li>{@link #setDetail} —— 套件 → 部位 → 工序明细（应做数量 / 单位 / 单价 / 状态 / 已报数量）；</li>
 *   <li>{@link #scanProgress} —— 扫码循环进度（按订单 / 加工单）。</li>
 * </ol>
 * <p><b>本类只读</b>：不写库、不带 {@code @Transactional}、不触发任何扫码副作用（不占幂等键、
 * 不推进 {@code done_qty}、不发卡）。</p>
 *
 * <h2>口径（逐条与既有读面同源）</h2>
 * <ul>
 *   <li><b>进度</b>取 {@link ProductionService#progressOf}（与 {@code set_progress} /
 *       {@code GET /agent/production/progress} **同一份**实现），不另算百分比；</li>
 *   <li><b>完成时刻</b>取 {@link #completedAt}（既有实现原样搬来）= 已完成工序里最晚的
 *       {@code done_at}；⚠️ 与 #4967 的语义降级一致：{@code done_at} 今天记的是**领活**时点
 *       （名不副实，见 {@code docs/design/set-code-and-scan-loop.md} §4.1 改判块）；</li>
 *   <li><b>未定价 ≠ 0 元</b>（V90 / issue #4696）：{@code unit_price} 为 {@code null} 时
 *       <b>原样 null</b>，读面不折 0；</li>
 *   <li><b>租户 + 软删</b>：每个查询都显式带 {@code tenant_id} + {@code deleted = 0}
 *       （多租户拦截器也注入一份，这里不依赖它 —— 显式条件才是判据，见
 *       {@code ProcessingOrderSetMapper} 的 {@code lockSetsOfOrder} 同款说明）。</li>
 * </ul>
 *
 * <p><b>SQL 用字符串列名而非 Lambda 列名</b>（与 {@code ProductionService#resolveOrder} 同款纪律）：
 * Standalone MockMvc 单测环境没有 MyBatis-Plus 的 {@code TableInfo} 缓存，Lambda 列名要到
 * 生成 SQL 段时才解析；字符串列名的 wrapper 参数（{@code getParamNameValuePairs()}）可直接在
 * 测试里核验「租户 + 软删」两个条件确实在（判据见 {@code ProcessingOrderSetControllerTest}）。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ProcessingSetReadService {

    /** 分页上限（防一页拉全库；调用方给更大值按上限收敛，不报错）。 */
    private static final int MAX_PAGE_SIZE = 100;

    /** 默认分页大小（调用方不传 size 时）。 */
    private static final int DEFAULT_PAGE_SIZE = 20;

    /**
     * 「精裁」的**逻辑工序名**（车间第一道工序：把整卷布按尺寸裁开）—— 与
     * {@code ProductionSeedTemplateService.ROUTE_MAINLINE_STEPS} 首项 /
     * {@code backend/ai-agent-service/app/production/routing.py::ROUTE_MAINLINE_STEPS} 首项逐字同源。
     *
     * <p>工序实例上的名字是**变体名**（{@code 精裁-布} / {@code 精裁-纱} / {@code 精裁-帘头}）
     * ⇒ 比对前一律走 {@code ProductionOperationQueryService.logicalOperationName}（既有唯一口径，
     * 本类不另建映射表）。</p>
     */
    private static final String CUT_OPERATION = "精裁";

    /**
     * 用料米数的**唯一**口径标记：{@code qty_source} 逐字等于它 = 算料引擎**直接供数**
     * （`processing_position_operations.qty_source`，V57 / issue #4208 三态之一）。
     * 其余取值（{@code fallback} = 真兜底 1 / {@code <键名>_x6} = 每米 6 孔估算 / {@code NULL} =
     * 本列引入前的旧实例）**都不是**「这一部位要用多少米布」⇒ 读面留空，不拿兜底值当用料。
     */
    private static final String QTY_SOURCE_FABRIC_METERS = "fabric_meters";

    private final ProcessingOrderSetMapper orderSetMapper;
    private final ProcessingPositionOperationMapper positionOperationMapper;
    private final OrderItemMapper orderItemMapper;
    private final ProcessingOrderMapper processingOrderMapper;
    private final OrderMapper orderMapper;
    /**
     * 复用**既有**实现，不在本类重写：{@code progressOf}（进度的唯一算法）与
     * {@code resolveOrder}（订单四形态解析的唯一实现，issue #4005 / #4222）。
     */
    private final ProductionService productionService;

    // ============================================================ 交付物 1：套件列表

    /**
     * 套件列表（分页）。
     *
     * @param orderNo           可选：订单号（走 {@link ProductionService#resolveOrder} 的四形态；
     *                          命中该订单下**全部未删除**加工单的套，含已取消的历史单）
     * @param processingOrderNo 可选：加工单号（点名要它 ⇒ 查不到就 404，不静默给空页；两者都给时以它为准）
     * @param page              页码（1 起；非法值收敛为 1，不报错）
     * @param size              每页条数（收敛到 1~{@value #MAX_PAGE_SIZE}）
     * @return 分页信封 {@code {total, page, size, items[]}}；每行键集见
     *         {@code ProcessingOrderSetControllerTest} 的键集冻结断言（**不得删键**）
     */
    public PageResponse<Map<String, Object>> listSets(String orderNo, String processingOrderNo,
                                                     int page, int size, Long tenantId) {
        long current = Math.max(1, page);
        long limit = size <= 0 ? DEFAULT_PAGE_SIZE : Math.min(MAX_PAGE_SIZE, size);
        List<String> processingOrderIds = filterProcessingOrderIds(orderNo, processingOrderNo, tenantId);
        if (processingOrderIds != null && processingOrderIds.isEmpty()) {
            // 该订单还没有加工单 ⇒ 空页（不是错误：套只存在于加工单之下，「真的没有」）
            return PageResponse.of(0L, current, limit, List.of());
        }

        QueryWrapper<ProcessingOrderSet> wrapper = new QueryWrapper<ProcessingOrderSet>()
                .eq("tenant_id", tenantId)
                .eq("deleted", 0);
        if (processingOrderIds != null) {
            wrapper.in("processing_order_id", processingOrderIds);
        }
        wrapper.orderByAsc("set_no").orderByAsc("id"); // 稳定序：分页不跳行、不重行

        Page<ProcessingOrderSet> request = new Page<>(current, limit);
        Page<ProcessingOrderSet> result = orderSetMapper.selectPage(request, wrapper);
        List<ProcessingOrderSet> rows = result == null || result.getRecords() == null
                ? List.of()
                : result.getRecords();

        // 一页 N 套通常只挂在 1~2 张加工单上 ⇒ 工序只查「本页出现过的加工单」，不做 N+1
        Map<String, List<ProcessingPositionOperation>> operationsBySet = operationsBySet(rows, tenantId);
        Map<String, ProcessingOrder> poCache = new LinkedHashMap<>();
        Map<String, String> orderNoCache = new LinkedHashMap<>();
        List<Map<String, Object>> items = new ArrayList<>();
        for (ProcessingOrderSet set : rows) {
            items.add(setRowView(set, operationsBySet, poCache, orderNoCache, tenantId));
        }
        return PageResponse.of(result == null ? 0L : result.getTotal(), current, limit, items);
    }

    /**
     * 套件详情：套 → 部位 → 工序明细。
     *
     * <p>{@code set_overview} 键**就是** {@link #setOverview} 的输出（与工人扫码面同一形状、同一实现）
     * —— 不在这里二次整形（二次整形 = 第二份口径，页面与工人屏迟早不同）。</p>
     *
     * @param setId 套 id（{@code processing_order_sets.id}）
     * @return 详情；跨租户 / 已软删 / 不存在 ⇒ 404（fail-closed）
     */
    public Map<String, Object> setDetail(String setId, Long tenantId) {
        if (!StringUtils.hasText(setId)) {
            throw BusinessException.validationError("套件 id 不能为空");
        }
        ProcessingOrderSet set = orderSetMapper.selectById(setId);
        if (!isAlive(set, tenantId)) {
            throw BusinessException.notFound("套件", "该套件不存在或不属于当前租户");
        }
        ProcessingOrder po = requireProcessingOrder(set.getProcessingOrderId(), tenantId);
        List<ProcessingPositionOperation> setOperations =
                listSetOperations(set.getProcessingOrderId(), set.getId(), tenantId);
        Map<String, Object> progress = productionService.progressOf(setOperations);

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("set_id", set.getId());
        result.put("set_no", set.getSetNo());
        result.put("set_index", set.getSetIndex());
        result.put("craft_line_id", set.getCraftLineId());
        result.put("processing_order_id", po.getId());
        result.put("processing_order_no", po.getProcessingOrderNo());
        result.put("order_id", po.getOrderId());
        result.put("order_no", orderNoOf(po.getOrderId(), tenantId));
        result.put("completed", isCompleted(progress));
        result.put("completed_at", completedAt(setOperations));
        result.put("set_overview", setOverview(set, setOperations, tenantId));
        result.put("progress", progress);
        return result;
    }

    // ============================================================ 交付物 3：扫码循环进度

    /**
     * 扫码循环进度（按订单 / 加工单）。
     *
     * <p>「扫码循环」= 工人扫一次码（= 开工 / 领活，issue #4967 改判①）就推进一道工序
     * （设计 §5.1「一次扫码同时干两件事：推进工序进度 + 记录个人计件」）⇒ 进度 = 本单/本套的
     * <b>活跃工序实例报满率</b>，判据与 {@code set_progress} / {@code GET /agent/production/progress}
     * **同一份**（{@link ProductionService#progressOf}）。</p>
     *
     * <p><b>按订单号</b>时取该订单**当前活跃加工单**（{@code selectActiveByOrderId}，与
     * {@link ProductionService#progress} 同款）；该订单还没有加工单 ⇒ 返回零值行
     * （{@code processing_order_id=null} + {@code sets=[]}），与既有 {@code progress} 的
     * 「还没生产就是 0」口径一致，<b>不</b>抛 404。<b>按加工单号</b>时点名即须存在 ⇒ 查不到 404。</p>
     *
     * @param orderNo           订单号（与 {@code processingOrderNo} 至少给一个）
     * @param processingOrderNo 加工单号（更具体，两者都给时以它为准）
     */
    public Map<String, Object> scanProgress(String orderNo, String processingOrderNo, Long tenantId) {
        Order order;
        ProcessingOrder po;
        if (StringUtils.hasText(processingOrderNo)) {
            po = processingOrderByNo(processingOrderNo.trim(), tenantId);
            order = orderById(po.getOrderId(), tenantId);
        } else if (StringUtils.hasText(orderNo)) {
            order = productionService.resolveOrder(orderNo.trim(), tenantId);
            po = processingOrderMapper.selectActiveByOrderId(order.getId(), tenantId);
        } else {
            throw BusinessException.validationError("orderNo 与 processingOrderNo 至少要给一个");
        }

        List<ProcessingOrderSet> sets = po == null ? List.of() : listSetsOfOrders(List.of(po.getId()), tenantId);
        List<ProcessingPositionOperation> operations = po == null
                ? List.<ProcessingPositionOperation>of()
                : listOrderOperations(po.getId(), tenantId);
        Map<String, List<ProcessingPositionOperation>> operationsBySet = groupBySet(operations);
        Map<String, Object> overall = productionService.progressOf(operations);

        List<Map<String, Object>> setRows = new ArrayList<>();
        int completedSets = 0;
        for (ProcessingOrderSet set : sets) {
            List<ProcessingPositionOperation> setOperations =
                    operationsBySet.getOrDefault(set.getId(), List.of());
            Map<String, Object> progress = productionService.progressOf(setOperations);
            boolean completed = isCompleted(progress);
            if (completed) {
                completedSets++;
            }
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("set_id", set.getId());
            row.put("set_no", set.getSetNo());
            row.put("set_index", set.getSetIndex());
            row.put("completed", completed);
            row.put("completed_at", completedAt(setOperations));
            row.put("total_operations", progress.get("total"));
            row.put("done_operations", progress.get("done"));
            row.put("progress_percent", progress.get("percent"));
            setRows.add(row);
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("order_id", order == null ? null : order.getId());
        result.put("order_no", order == null ? null : order.getOrderNo());
        result.put("processing_order_id", po == null ? null : po.getId());
        result.put("processing_order_no", po == null ? null : po.getProcessingOrderNo());
        result.put("total_sets", sets.size());
        result.put("completed_sets", completedSets);
        result.put("total_operations", overall.get("total"));
        result.put("done_operations", overall.get("done"));
        result.put("progress_percent", overall.get("percent"));
        result.put("sets", setRows);
        return result;
    }

    // ============================================================ 单一口径聚合（原 ProductionScanService）
    // ⚠️ 以下 setOverview / overviewOperationView / positionView / positionEntry / productNameOf /
    //    listSetOperations / listOrderOperations / completedAt / requireProcessingOrder 全部是
    //    **原样搬移**（issue #4967 → issue #5247），语义一字未改；两消费者共用同一份。

    /**
     * 本套工序总览（issue #4967 交付物 2；设计 {@code docs/design/set-code-and-scan-loop.md} §4.1）。
     *
     * <p><b>形状</b>：{@code {set_no, set_index, positions: [{order_item_id, position_kind,
     * position_name, remark, operations: [{operation_id, logical_name, position, seq, qty, unit,
     * unit_price, status, done_qty}]}], cut_plan: [{order_item_id, position_kind, position_name,
     * component, fabric_meters, panel_count, panel_length_m, remark, missing_reason}]}}。</p>
     *
     * <p>🔴 {@code cut_plan}（issue #5693）= **精裁输出清单**（给裁床的「裁多长 × 几片」），
     * 与 {@code positions} 同源同序；取值来源与缺值口径见 {@link #cutPlan}。挂在**本键之内**
     * 是有意的：{@code set_overview} 是「单一实现、两个读面」的载体 ⇒ 两个读面自动同源。</p>
     *
     * <p>🔴 {@code remark}（issue #5685）= **商家填的部位级备注**（订单行 {@code processing_info.remark}），
     * 就地取自订单行现值；**未填 ⇒ {@code null}**（键恒在，不省键、不造空串）。</p>
     *
     * <p><b>口径</b>：① 列**全部**工序（不只是待做）—— 工人要一眼看到「这一套还有哪几道没做」
     * ⇒ 已完成的道必须也在（{@code status} / {@code done_qty} 让页面自己区分）；
     * ② {@code unit_price} 为 {@code null} = <b>未定价</b>（≠ 0 元，V90 / #4696），读面**不折 0**；
     * ③ 排序沿用 {@link #listSetOperations} 的既有读面序（部位名 → seq），**不另排**；
     * ④ 工序按 {@code order_item_id} 分组（缺值落「未归属部位」一组，**不丢行**）。</p>
     */
    public Map<String, Object> setOverview(ProcessingOrderSet set,
                                           List<ProcessingPositionOperation> setOperations,
                                           Long tenantId) {
        Map<String, List<ProcessingPositionOperation>> byItem = byOrderItem(setOperations);
        List<Map<String, Object>> positions = new ArrayList<>();
        for (Map.Entry<String, List<ProcessingPositionOperation>> entry : byItem.entrySet()) {
            List<ProcessingPositionOperation> ops = entry.getValue();
            ProcessingPositionOperation head = ops.get(0);
            Map<String, Object> view = new LinkedHashMap<>();
            view.put("order_item_id", entry.getKey());
            view.put("position_kind", head.getPositionKind());
            view.put("position_name", positionView(entry.getKey(), head.getPositionKind(),
                    setOperations, tenantId).get("position_name"));
            // 部位级备注（issue #5685）：键**恒在**，未填 ⇒ null（不省键、也不造空串 —— 消费方不必写分支）
            view.put("remark", remarkOf(entry.getKey(), tenantId));
            view.put("operations", ops.stream().map(ProcessingSetReadService::overviewOperationView).toList());
            positions.add(view);
        }
        Map<String, Object> overview = new LinkedHashMap<>();
        overview.put("set_no", set.getSetNo());
        overview.put("set_index", set.getSetIndex());
        overview.put("positions", positions);
        // 精裁输出清单（issue #5693，**只加一个键**，既有键一字不动）：与上面 `positions`
        // **同一份** `setOperations`、**同一份**分组（`byOrderItem`）⇒ 本键随 `set_overview`
        // 自动出现在**两个**读面上（工人扫码 `GET /api/worker/production/scan` /
        // 商家 `GET /api/admin/processing-order-sets/{id}`），**零额外接线**。
        overview.put("cut_plan", cutPlan(setOperations, tenantId));
        return overview;
    }

    // ============================================================ 精裁输出清单（issue #5693）

    /**
     * 精裁输出清单 —— 给裁床的「**裁多长（米）× 几片**」（issue #5693，**只读**）。
     *
     * <p><b>行粒度 = 套 × 部位</b>（`order_item_id` 一组一行，序 = {@link #byOrderItem} 的首次出现序）。
     * 一套一行清单，因为「哪几片、每片多长」是**这一套**要做的事。</p>
     *
     * <h2>🔴 字段面的取值来源（issue 正文「前置 1」要求逐字钉死，不许两处口径）</h2>
     * <ul>
     *   <li><b>用料（米）</b>{@code fabric_meters} = 该部位「精裁」**工序实例**的 {@code qty}，
     *       且**仅当** {@code qty_source} 逐字 = {@value #QTY_SOURCE_FABRIC_METERS}（引擎直接供数）。
     *       <b>不</b>回落订单行 / 加工单快照的 {@code fabric_meters} —— 那是第二份口径；
     *       {@code fallback}（兜底 1）等取值一律留空 + 标原因（拿 1 当用料就是渲染假数据）。</li>
     *   <li><b>几片 / 裁多长</b> = {@link CuttingPlanCalculator#pieceLengths}（**同一份**分解，
     *       排料器 {@code StockBatchConsumptionService.piecesOf} 调的就是它）：
     *       定高买宽 ⇒ 1 片 × 用料米数；定宽买高 ⇒ {@code panels} 片 × {@code 用料 / panels}。
     *       <b>不在清单侧重算算料</b>（不自己 {@code ceil(M/G)}、不自己推窗高 + 卷边）。</li>
     *   <li><b>几片</b>的唯一输入 = 算料输出 {@code panels}（订单行 {@code processing_info.panels}，
     *       源头 = 引擎 {@code plan.panels}；定高买宽**无定义 ⇒ 键缺席**）；
     *       <b>加工类型</b> = 订单行列 {@code cutting_mode}（缺则回落 {@code processing_info.cuttingMode}，
     *       优先级与 {@code OrderLineCraftFields.toSnapshotKeys} 逐字一致）。</li>
     * </ul>
     *
     * <h2>缺值口径（不渲染假数据）</h2>
     * <p>九键**恒在**；算不出来时 {@code fabric_meters} / {@code panel_count} /
     * {@code panel_length_m} 一律 {@code null}（**不用 0 / 1 冒充**），并由
     * {@code missing_reason} 指名缺的是什么。<b>片数与每片长同生同灭</b>（同一份分解：
     * 拿不到用料就报不出「裁多长」，半截数据比空更危险）。</p>
     *
     * @param setOperations 本套的活跃工序实例（既有读面序；与 {@link #setOverview} 同一份入参）
     */
    List<Map<String, Object>> cutPlan(List<ProcessingPositionOperation> setOperations, Long tenantId) {
        List<Map<String, Object>> rows = new ArrayList<>();
        for (Map.Entry<String, List<ProcessingPositionOperation>> entry : byOrderItem(setOperations).entrySet()) {
            rows.add(cutPlanRow(entry.getKey(), entry.getValue(), tenantId));
        }
        return rows;
    }

    /** 清单一行（键集见 {@link #cutPlan}；九键恒在，缺值 null）。 */
    private Map<String, Object> cutPlanRow(String orderItemId, List<ProcessingPositionOperation> ops,
                                           Long tenantId) {
        OrderItem item = aliveItem(orderItemId, tenantId);
        // 🔴 存量行：`order_items.processing_info` **可为 NULL**（真库实证 issue #5550：待派明细 15/29 为 NULL），
        // 且 JSON 字符串解析失败时归一化也返回 null ⇒ **归一化结果是可能为 null 的缺值，不得直接解引用**。
        //（我第一版写成 `item == null ? Map.of() : normalize(...)` 三元 ⇒ 归一化那一支仍可能返回 null
        //  ⇒ 下面 `info.get(...)` NPE 500；类级元守卫 `ProcessingInfoNullSafetyMetaGuardTest` 抓的就是它。
        //  ⚠️ 判据只看**赋值行之后 6 行**内有没有 null 判定 ⇒ 说明性注释必须写在这里、不能插在两者中间。）
        // 语义：缺值 = 「这一行没有任何工艺键」⇒ 收敛成空表，下面一律按**缺键**读（不造值）。
        Map<String, Object> info = OrderLineCraftFields.normalize(
                item == null ? null : item.getProcessingInfo());
        if (info == null) {
            info = Map.of();
        }
        ProcessingPositionOperation cutOp = cutOperationOf(ops);
        BigDecimal fabricMeters = cutOp != null && QTY_SOURCE_FABRIC_METERS.equals(cutOp.getQtySource())
                ? cutOp.getQty()
                : null;
        String mode = CuttingPlanCalculator.modeOf(cuttingModeOf(item, info));
        Integer panels = OrderLineCraftFields.integerOrNull(info.get("panels"),
                "order_items." + orderItemId + " 的分幅数");
        List<BigDecimal> lengths = CuttingPlanCalculator.pieceLengths(mode, fabricMeters, panels);

        Map<String, Object> row = new LinkedHashMap<>();
        row.put("order_item_id", orderItemId);
        row.put("position_kind", ops.get(0).getPositionKind());
        row.put("position_name", positionNameOf(orderItemId, ops.get(0), ops, tenantId));
        row.put("component", textOrNull(info.get("componentRole")));
        row.put("fabric_meters", fabricMeters);
        row.put("panel_count", lengths.isEmpty() ? null : lengths.size());
        row.put("panel_length_m", lengths.isEmpty() ? null : lengths.get(0));
        row.put("remark", remarkOf(item));
        row.put("missing_reason", lengths.isEmpty()
                ? cutPlanMissingReason(cutOp, fabricMeters, mode, panels)
                : null);
        return row;
    }

    /** 该部位第一道「精裁」工序实例（按本套既有读面序取首道）；没有 ⇒ {@code null}。 */
    private static ProcessingPositionOperation cutOperationOf(List<ProcessingPositionOperation> ops) {
        for (ProcessingPositionOperation op : ops) {
            if (CUT_OPERATION.equals(ProductionOperationQueryService.logicalOperationName(op.getOperationName()))) {
                return op;
            }
        }
        return null;
    }

    /** 部位名：与该套 `positions[].position_name` **同一份**规则（工序实例的部位名 → 订单行商品名）。 */
    private String positionNameOf(String orderItemId, ProcessingPositionOperation head,
                                  List<ProcessingPositionOperation> ops, Long tenantId) {
        return (String) positionView(orderItemId, head.getPositionKind(), ops, tenantId).get("position_name");
    }

    /** 加工类型：**列优先**，缺则回落 {@code processing_info.cuttingMode}（与 {@code OrderLineCraftFields.toSnapshotKeys} 同优先级）。 */
    private static String cuttingModeOf(OrderItem item, Map<String, Object> info) {
        if (item != null && StringUtils.hasText(item.getCuttingMode())) {
            return item.getCuttingMode();
        }
        return textOrNull(info.get("cuttingMode"));
    }

    /** 非字符串 / 空串 / 纯空白 ⇒ {@code null}（不造值）；有值则 {@code trim}。 */
    private static String textOrNull(Object raw) {
        if (!(raw instanceof String text)) {
            return null;
        }
        String trimmed = text.trim();
        return trimmed.isEmpty() ? null : trimmed;
    }

    /**
     * 算不出来时**指名缺的是什么**（issue #5693 验收：「显式留空**或标注原因**」）。
     *
     * <p>分支序 = 先因后果：加工类型不认 ⇒ 后面两项都谈不上；再判用料；最后判幅数。
     * 每个分支的措辞都**说得出下一步该补什么**（不说「数据异常」这种不可行动的话）。</p>
     */
    private static String cutPlanMissingReason(ProcessingPositionOperation cutOp, BigDecimal fabricMeters,
                                              String mode, Integer panels) {
        if (mode == null) {
            return "未选加工类型（定高买宽 / 定宽买高）：裁多长与几片都算不出来（不猜工艺）";
        }
        if (fabricMeters == null) {
            return cutOp == null
                    ? "本套该部位没有「精裁」工序实例：用料米数无从取（不猜）"
                    : "「精裁」工序实例的应做数量不是算料用料（qty_source=" + cutOp.getQtySource()
                            + "）：不用兜底值当用料";
        }
        if (CuttingPlanCalculator.MODE_FIXED_WIDTH.equals(mode) && (panels == null || panels <= 0)) {
            return "缺幅数（panels）：定宽买高按幅数分片，算料没给该键（幅数无定义时键缺席）";
        }
        return "用料米数非正：算不出来（不用 0 冒充）";
    }

    /**
     * 总览里的一道工序（{@link #setOverview} 的元素）。
     *
     * <p>{@code logical_name} / {@code position} 与 {@code alternatives}、一屏上的 {@code operation}
     * **同一份**读时派生（{@code ProductionOperationQueryService} 的两个静态方法）—— 在这里再拼一份
     * 显示名就是第二份口径（#4621 / #4630 同族纪律）。</p>
     */
    private static Map<String, Object> overviewOperationView(ProcessingPositionOperation op) {
        Map<String, Object> view = new LinkedHashMap<>();
        view.put("operation_id", op.getId());
        view.put("logical_name",
                ProductionOperationQueryService.logicalOperationName(op.getOperationName()));
        view.put("position", ProductionOperationQueryService.displayPosition(
                op.getOperationName(), op.getPositionKind()));
        view.put("seq", op.getSeq());
        view.put("qty", nz(op.getQty()));
        view.put("unit", op.getUnit());
        view.put("unit_price", op.getUnitPrice());
        view.put("status", op.getStatus());
        view.put("done_qty", nz(op.getDoneQty()));
        return view;
    }

    /**
     * 部位视图（{@code {order_item_id, position_kind, position_name}}；三键**恒在**，
     * 缺值给 {@code null} 而不是省键 —— 消费方不必写分支）。
     */
    public Map<String, Object> positionView(String orderItemId, String positionKind,
                                            List<ProcessingPositionOperation> setOperations,
                                            Long tenantId) {
        String positionName = setOperations.stream()
                .filter(op -> orderItemId.equals(op.getOrderItemId()))
                .map(ProcessingPositionOperation::getPositionName)
                .filter(StringUtils::hasText)
                .findFirst()
                .orElseGet(() -> productNameOf(orderItemId, tenantId));
        return positionEntry(orderItemId, positionKind, positionName);
    }

    /** 部位三键（{@code order_item_id} / {@code position_kind} / {@code position_name}）恒在。 */
    public static Map<String, Object> positionEntry(String orderItemId, String positionKind,
                                                    String positionName) {
        Map<String, Object> view = new LinkedHashMap<>();
        view.put("order_item_id", orderItemId);
        view.put("position_kind", positionKind);
        view.put("position_name", positionName);
        return view;
    }

    /** 本套完成时刻 = **已完成**工序里最晚的 {@code done_at}（#4967 后 = 最后一次领活；无 ⇒ null，不猜）。 */
    public OffsetDateTime completedAt(List<ProcessingPositionOperation> operations) {
        OffsetDateTime latest = null;
        for (ProcessingPositionOperation op : operations) {
            if (op.getDoneAt() == null || !productionService.isDone(op)) {
                continue;
            }
            if (latest == null || op.getDoneAt().isAfter(latest)) {
                latest = op.getDoneAt();
            }
        }
        return latest;
    }

    /** 本套的活跃工序实例（同租户 + 未软删；既有读面序：部位名 → seq）。 */
    public List<ProcessingPositionOperation> listSetOperations(String processingOrderId, String setId,
                                                              Long tenantId) {
        List<ProcessingPositionOperation> rows = positionOperationMapper.selectList(
                new QueryWrapper<ProcessingPositionOperation>()
                        .eq("tenant_id", tenantId)
                        .eq("deleted", 0)
                        .eq("processing_order_id", processingOrderId)
                        .eq("set_id", setId)
                        .orderByAsc("position_name")
                        .orderByAsc("seq"));
        return rows == null ? List.of() : rows;
    }

    /** 整个加工单的活跃工序实例（同租户 + 未软删；与 {@link #listSetOperations} 同一读面序）。 */
    public List<ProcessingPositionOperation> listOrderOperations(String processingOrderId, Long tenantId) {
        List<ProcessingPositionOperation> rows = positionOperationMapper.selectList(
                new QueryWrapper<ProcessingPositionOperation>()
                        .eq("tenant_id", tenantId)
                        .eq("deleted", 0)
                        .eq("processing_order_id", processingOrderId)
                        .orderByAsc("position_name")
                        .orderByAsc("seq"));
        return rows == null ? List.of() : rows;
    }

    /** 加工单归属校验：同租户 + 未软删（任一不成立 ⇒ 404，fail-closed）。 */
    public ProcessingOrder requireProcessingOrder(String processingOrderId, Long tenantId) {
        ProcessingOrder po = aliveProcessingOrder(processingOrderId, tenantId);
        if (po == null) {
            throw BusinessException.notFound("加工单");
        }
        return po;
    }

    // ============================================================ 私有：查询 / 整形

    /**
     * 过滤条件 ⇒ 该订单/加工单下的加工单 id 集。
     *
     * @return {@code null} = **不加**加工单过滤（两个参数都没给）；空集 = 条件命中但该订单还没有加工单
     */
    private List<String> filterProcessingOrderIds(String orderNo, String processingOrderNo, Long tenantId) {
        if (StringUtils.hasText(processingOrderNo)) {
            return List.of(processingOrderByNo(processingOrderNo.trim(), tenantId).getId());
        }
        if (StringUtils.hasText(orderNo)) {
            Order order = productionService.resolveOrder(orderNo.trim(), tenantId);
            return processingOrdersOf(order.getId(), tenantId).stream().map(ProcessingOrder::getId).toList();
        }
        return null;
    }

    /** 加工单号 ⇒ 加工单（同租户 + 未软删；点名的对象不存在 ⇒ 404，不静默给空集）。 */
    private ProcessingOrder processingOrderByNo(String processingOrderNo, Long tenantId) {
        ProcessingOrder po = processingOrderMapper.selectOne(new QueryWrapper<ProcessingOrder>()
                .eq("processing_order_no", processingOrderNo)
                .eq("tenant_id", tenantId)
                .eq("deleted", 0)
                .last("LIMIT 1"));
        if (!isAlive(po, tenantId)) {
            throw BusinessException.notFound("加工单");
        }
        return po;
    }

    /** 该订单下**全部未删除**加工单（含已取消的历史单：读面按订单过滤不该静默丢单）。 */
    private List<ProcessingOrder> processingOrdersOf(String orderId, Long tenantId) {
        if (!StringUtils.hasText(orderId)) {
            return List.of();
        }
        List<ProcessingOrder> rows = processingOrderMapper.selectList(new QueryWrapper<ProcessingOrder>()
                .eq("order_id", orderId)
                .eq("tenant_id", tenantId)
                .eq("deleted", 0));
        return rows == null ? List.of() : rows;
    }

    /** 若干加工单下的套（同租户 + 未软删；按套号升序 —— 与分页序同一份，避免「翻页跳行」）。 */
    private List<ProcessingOrderSet> listSetsOfOrders(List<String> processingOrderIds, Long tenantId) {
        if (processingOrderIds != null && processingOrderIds.isEmpty()) {
            return List.of();
        }
        QueryWrapper<ProcessingOrderSet> wrapper = new QueryWrapper<ProcessingOrderSet>()
                .eq("tenant_id", tenantId)
                .eq("deleted", 0);
        if (processingOrderIds != null) {
            wrapper.in("processing_order_id", processingOrderIds);
        }
        wrapper.orderByAsc("set_no").orderByAsc("id");
        List<ProcessingOrderSet> rows = orderSetMapper.selectList(wrapper);
        return rows == null ? List.of() : rows;
    }

    /**
     * 列表行：身份 + 父链 + 进度（进度取 {@link ProductionService#progressOf}；
     * 工序取自本页加工单的**同一份**读面查询，不做 N+1）。
     */
    private Map<String, Object> setRowView(ProcessingOrderSet set,
                                           Map<String, List<ProcessingPositionOperation>> operationsBySet,
                                           Map<String, ProcessingOrder> poCache,
                                           Map<String, String> orderNoCache,
                                           Long tenantId) {
        String poId = set.getProcessingOrderId();
        ProcessingOrder po;
        if (poCache.containsKey(poId)) {
            po = poCache.get(poId);
        } else {
            po = aliveProcessingOrder(poId, tenantId);
            poCache.put(poId, po);
        }
        String orderId = po == null ? null : po.getOrderId();
        String orderNo = null;
        if (orderId != null) {
            if (orderNoCache.containsKey(orderId)) {
                orderNo = orderNoCache.get(orderId);
            } else {
                orderNo = orderNoOf(orderId, tenantId);
                orderNoCache.put(orderId, orderNo);
            }
        }

        Map<String, Object> progress = productionService.progressOf(
                operationsBySet.getOrDefault(set.getId(), List.of()));
        Map<String, Object> view = new LinkedHashMap<>();
        view.put("set_id", set.getId());
        view.put("set_no", set.getSetNo());
        view.put("set_index", set.getSetIndex());
        view.put("craft_line_id", set.getCraftLineId());
        view.put("processing_order_id", poId);
        view.put("processing_order_no", po == null ? null : po.getProcessingOrderNo());
        view.put("order_id", orderId);
        view.put("order_no", orderNo);
        view.put("total_operations", progress.get("total"));
        view.put("done_operations", progress.get("done"));
        view.put("progress_percent", progress.get("percent"));
        view.put("completed", isCompleted(progress));
        // 精裁输出清单（issue #5693）：与套件详情 `set_overview.cut_plan` **同一个**
        // {@link #cutPlan}（同一份分解、同一份取值口径）⇒ 列表行与详情行逐字段一致。
        view.put("cut_plan", cutPlan(operationsBySet.getOrDefault(set.getId(), List.of()), tenantId));
        return view;
    }

    /**
     * 工序实例按 {@code order_item_id} 分组（插入序 = **首次出现序**，不重排）。
     *
     * <p>🔴 唯一一份「按部位分组」规则：{@link #setOverview} 的 {@code positions} 与
     * {@link #cutPlan} 都调它 ⇒ 两处不会因分组口径不同而错位（各写一份 = 两处迟早不同）。</p>
     */
    private static Map<String, List<ProcessingPositionOperation>> byOrderItem(
            List<ProcessingPositionOperation> setOperations) {
        Map<String, List<ProcessingPositionOperation>> byItem = new LinkedHashMap<>();
        for (ProcessingPositionOperation op : setOperations) {
            byItem.computeIfAbsent(op.getOrderItemId(), key -> new ArrayList<>()).add(op);
        }
        return byItem;
    }

    /** 本页出现过的加工单 ⇒ 该加工单的全部工序（一次查询按套分组，避免 N+1）。 */
    private Map<String, List<ProcessingPositionOperation>> operationsBySet(List<ProcessingOrderSet> sets,
                                                                          Long tenantId) {
        Set<String> poIds = new LinkedHashSet<>();
        for (ProcessingOrderSet set : sets) {
            if (StringUtils.hasText(set.getProcessingOrderId())) {
                poIds.add(set.getProcessingOrderId());
            }
        }
        List<ProcessingPositionOperation> all = new ArrayList<>();
        for (String poId : poIds) {
            all.addAll(listOrderOperations(poId, tenantId));
        }
        return groupBySet(all);
    }

    /** 按 {@code set_id} 分组（缺值 = 存量未归属套的实例行 ⇒ 不进任何套的进度，也不丢行本身）。 */
    private static Map<String, List<ProcessingPositionOperation>> groupBySet(
            List<ProcessingPositionOperation> operations) {
        Map<String, List<ProcessingPositionOperation>> bySet = new LinkedHashMap<>();
        for (ProcessingPositionOperation op : operations) {
            if (op.getSetId() == null) {
                continue;
            }
            bySet.computeIfAbsent(op.getSetId(), key -> new ArrayList<>()).add(op);
        }
        return bySet;
    }

    private String orderNoOf(String orderId, Long tenantId) {
        Order order = orderById(orderId, tenantId);
        return order == null ? null : order.getOrderNo();
    }

    /** 订单（同租户 + 未软删）；取不到 ⇒ {@code null}（读面不因父链缺失就整页失败）。 */
    private Order orderById(String orderId, Long tenantId) {
        if (!StringUtils.hasText(orderId)) {
            return null;
        }
        Order order = orderMapper.selectById(orderId);
        if (order == null || !tenantId.equals(order.getTenantId())
                || Integer.valueOf(1).equals(order.getDeleted())) {
            return null;
        }
        return order;
    }

    private String productNameOf(String orderItemId, Long tenantId) {
        OrderItem item = aliveItem(orderItemId, tenantId);
        return item == null ? null : item.getProductName();
    }

    /** 订单行（同租户 + 未软删）；不可用 ⇒ {@code null}（读面不因父链缺失就整页失败）。 */
    private OrderItem aliveItem(String orderItemId, Long tenantId) {
        if (orderItemId == null) {
            return null;
        }
        OrderItem item = orderItemMapper.selectById(orderItemId);
        if (item == null || !tenantId.equals(item.getTenantId())
                || Integer.valueOf(1).equals(item.getDeleted())) {
            return null;
        }
        return item;
    }

    /**
     * 部位级备注（issue #5685）：读订单行 {@code processing_info.remark}（商家填的自由文本）。
     *
     * <p>形态：本类走 {@code OrderItemMapper.selectById}（BaseMapper）⇒ {@code JacksonTypeHandler}
     * 生效 ⇒ {@code processing_info} 恒为 {@code Map}（字符串形态只在**自定义 @Select 路径**出现，
     * 本类不经过那条路 ⇒ 非 Map 一律按「未填」处理）。</p>
     *
     * <p>取值纪律：非字符串 / 空串 / 纯空白 ⇒ {@code null}（= 未填，**不造值**、不折成空串）；
     * 有值则 {@code trim} 后返回（存量脏数据的首尾空白不该显示到工人手机上）。</p>
     */
    private String remarkOf(String orderItemId, Long tenantId) {
        return remarkOf(aliveItem(orderItemId, tenantId));
    }

    /** {@link #remarkOf(String, Long)} 的**值级**重载：调用方已取到订单行时复用同一份判据（不重复查库）。 */
    private static String remarkOf(OrderItem item) {
        if (item == null || !(item.getProcessingInfo() instanceof Map<?, ?> info)) {
            return null;
        }
        return textOrNull(info.get("remark"));
    }

    /** 加工单（同租户 + 未软删）；不可用 ⇒ {@code null}。 */
    private ProcessingOrder aliveProcessingOrder(String processingOrderId, Long tenantId) {        if (!StringUtils.hasText(processingOrderId)) {
            return null;
        }
        ProcessingOrder po = processingOrderMapper.selectById(processingOrderId);
        return isAlive(po, tenantId) ? po : null;
    }

    /** 套行可用性：非空 + 同租户 + 未软删。 */
    private static boolean isAlive(ProcessingOrderSet set, Long tenantId) {
        return set != null && tenantId.equals(set.getTenantId())
                && Integer.valueOf(0).equals(set.getDeleted());
    }

    private static boolean isAlive(ProcessingOrder po, Long tenantId) {
        return po != null && tenantId.equals(po.getTenantId())
                && Integer.valueOf(0).equals(po.getDeleted());
    }

    /**
     * 套是否已做完 = **全部**活跃工序实例报满（{@code done_qty ≥ qty}，issue #4961 的完工口径）。
     *
     * <p>🔴 空套（一道活跃工序实例都没有，通常 = 实例化没跑 / 存量脏数据）⇒ {@code false}：
     * 不把「无事可做」说成「已完成」（那正是本仓最忌的静默错误）。</p>
     */
    private static boolean isCompleted(Map<String, Object> progress) {
        Object total = progress.get("total");
        return total instanceof Integer count && count > 0 && total.equals(progress.get("done"));
    }

    private static BigDecimal nz(BigDecimal value) {
        return value == null ? BigDecimal.ZERO : value;
    }
}