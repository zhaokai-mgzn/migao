package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.entity.ProcessingOrderSet;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.mapper.ProcessingOrderSetMapper;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.time.Duration;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * 「卡在哪」的判据与报表（切片 ③，issue #4776；设计
 * {@code docs/design/set-code-and-scan-loop.md} §6）。
 *
 * <p><b>本类是只读面</b>（设计 §14 ③「卡点报表（§6.3）← 只读面（D8）」）：不写库、不带
 * {@code @Transactional}、不改任何既有列/键。</p>
 *
 * <h2>① 三态判据（**必须可区分**，不许混）</h2>
 * <p>设计 §6.1 的判据表以「这道工序处于什么状态」为基座，而设计 §6.3 的 SQL 只写了
 * {@code o.status = 'pending'} —— 那一列**装不下三态**：报工允许部分数量
 * （{@code assertWithinPlannedQty} 只拒绝超上限），所以「做了一半」的实例行
 * {@code status} 仍是 {@code 'pending'}。⇒ 若照 SQL 字面把 {@code pending} 当「没开工」，
 * 「做了一半」会被**静默算成没开工**（催料催到正在干的活上）。故本类把三态**显式分开</b>：</p>
 * <table border="1">
 *   <caption>三态（互斥且完备）</caption>
 *   <tr><th>态</th><th>判据</th><th>依据</th></tr>
 *   <tr><td>{@code not_started} 没开工</td>
 *       <td>{@code done_qty = 0}（NULL 按 0 读）<b>且</b>{@code done_at IS NULL}</td>
 *       <td>issue #4776 逐字：「该（套 × 部位）的工序实例 {@code done_at IS NULL} 且
 *           {@code done_qty = 0}（从未报过工）」</td></tr>
 *   <tr><td>{@code in_progress} 做了一半</td>
 *       <td>{@code 0 < done_qty < qty}</td>
 *       <td>设计 §6.1 行①的语义边界（「上道已交，**这道没人扫**」）—— 报了 6/11 米的工序
 *           **有人扫过**，不是「没人扫」</td></tr>
 *   <tr><td>{@code completed} 已完成</td>
 *       <td>{@code done_qty ≥ qty}</td>
 *       <td><b>复用</b> {@link ProductionService#isDone}（既有**唯一**一份完工判据；
 *           切片 ② 落 {@code done_at} 用的是同一份 ⇒ 不新造第二份口径）</td></tr>
 * </table>
 * <p>矛盾态（{@code done_qty = 0} 但 {@code done_at} 非空 —— 与切片 ② 的写入条件
 * 「{@code isDone} 才落笔」矛盾）**不判没开工**：宁可漏报一个卡点，也不把「已经动过」的活
 * 报成「没人扫」（不猜）。</p>
 *
 * <h2>② A 模式卡点判据（**唯一一种**：没开工）</h2>
 * <p>设计 §6.1 行①（逐字）：「{@code status = 'pending'} <b>AND</b> 立即前道（同部位
 * {@code seq} 最大的更小 {@code seq}）{@code status = 'done'} <b>AND</b>
 * {@code now - predecessor.done_at > T_wait}」；§6.3 给出可直接落码的 SQL。</p>
 * <ul>
 *   <li><b>立即前道</b> = 同 {@code processing_order_id} + 同 {@code order_item_id} 中
 *       {@code seq} 最大的**更小** {@code seq}（{@code deleted = 0}）。</li>
 *   <li>🔴 {@code order_item_id} 的比较是 <b>{@code IS NOT DISTINCT FROM} 语义</b>
 *       （null-safe，见 §6.3 的 ⚠️）：普通 {@code =} 会让存量行（{@code order_item_id} 为
 *       NULL，V69 逐字）的「前道」永远匹配不到 ⇒ <b>该红不红</b>。本类用
 *       {@link Objects#equals} 逐字兑现该语义。</li>
 *   <li>🔴 前道<b>必须</b>有 {@code done_at}（§6.3 的 {@code p.done_at IS NOT NULL}）：
 *       切片 ② 之前的存量完成行没有该时刻 ⇒「上道几点完成」**不可知** ⇒ 不进卡点表
 *       （设计 {@code :46}：「{@code done_at} 不存在 ⇒ …『进度卡在哪』无判据」）。</li>
 *   <li>首道工序（{@code seq} 最小）没有前道 ⇒ 不进卡点表（§6.3 ⚠️：「首道工序的『等』是
 *       『等派工』，判据应另立 —— 见 §9 U7」）。</li>
 *   <li>{@code seq} 为 NULL 的实例行**判不出前道** ⇒ 不进卡点表（不猜）。</li>
 * </ul>
 *
 * <h2>③ 「卡了多久」用哪个时刻：**前道的 {@code done_at}**，绝不用 {@code updated_at}</h2>
 * <p>设计 §6.1 逐字：「A 模式的 ① <b>只需要 {@code done_at}</b>（本设计新增的<b>唯一</b>必需
 * 时序列）。今天的替代品是 {@code updated_at} —— ⚠️ <b>不可用</b>：它会被<b>任何</b>更新污染
 * （改名、改单价、重新实例化、其他字段的任何写入）⇒ 用它算「等了多久」会<b>静默给出错数</b>。」
 * ⇒ 本类的等待时长 = {@code now - predecessor.done_at}（= §6.3 的 {@code stalled_hours}），
 * 起算点 {@code predecessor_done_at} 一并回给调用方 ⇒「上道几点完成、等了多久」两句都可答
 * （判据 D8）。</p>
 *
 * <h2>④ 阈值从哪来（**不编数值**）</h2>
 * <p>设计 §6.4 实测全仓没有「标准工时」（F8 零命中），并把阈值列为<b>待裁定</b>（§8 A2）：
 * 「本设计<b>不替业务决定、不编数值</b>」。三条来源里 S1（同租户历史中位数）在 A 模式下
 * 「不能用 {@code started_at} ⇒ 只能退化为『同一工序在别的套/单上的报工间隔中位数』
 * （<b>口径更粗，需在落码时显式标注</b>），或直接用 S3」（§6.4 边界①）——
 * 那个更粗的口径属**待裁定**，本片**不发明**。</p>
 * <p>⇒ 本片只落 <b>S3</b>（「<b>全局默认常量</b>（如 {@code T_wait = 4h}）…<b>可配</b>」，
 * §6.4 表格逐字），且按设计的建议<b>响应里带 {@code threshold_source}</b>：今天恒为
 * {@code "default"}（S3）—— S1 落码时才会出现 {@code "history"}。**口径可解释**：
 * 「这道活等了 X 小时，超过阈值 Y 小时（来源：default）」。</p>
 *
 * <h2>与设计的偏离（照实登记）</h2>
 * <ul>
 *   <li><b>阈值只落 S3，S1 未落码</b>（§8 A2 待裁定 + §6.4 边界① 的 A 模式 S1 口径更粗 ⇒
 *       属待裁定项）。本类把 {@code threshold_source} 一并回给调用方 ⇒ 「阈值从哪来」
 *       **不静默**（与既有 {@code qty_source} 同族纪律）。</li>
 *   <li><b>报表用 Java 侧判据（复用 {@code isDone}）而不是 §6.3 的裸 SQL</b>：§6.3 的 SQL 把
 *       三态压成 {@code status = 'pending'} 一态（见 ①），且 SQL 里写不出「复用既有完工判据」
 *       —— 两处各写一份 {@code done_qty ≥ qty} 迟早漂移（切片 ① / ② 已按同款口径登记）。
 *       判据本体与 SQL 逐条对齐（前道 / null-safe 比较 / {@code done_at IS NOT NULL} /
 *       首道不进表 / 按 {@code stalled_hours} 降序）。</li>
 *   <li><b>B/C 模式的卡点不做</b>：§6.1 行②「开了没完」是 <b>仅 C</b>（§4.4 / §8 A3
 *       「C 只作预留」）；行③④是附加免费项（不进本片的报表）。裁定②-3 逐字：
 *       「『卡在哪』<b>在 A 模式下的口径 = 只有『没开工』那一种</b>」（§6 开头）。</li>
 *   <li><b>存量行（{@code set_id} 为 NULL）不进报表</b>：§6.3 的 SQL 是
 *       {@code JOIN processing_order_sets s ON s.id = o.set_id AND s.deleted = 0}（<b>INNER</b>
 *       JOIN）⇒ 判据本身就是「按套 × 工序」；V92 只给 {@code order_item_id} 非空的存量行回填
 *       {@code set_id}（§9 U1「留空 + 读面兜底」）⇒ 这些行**判不出属于哪一套**，故不进本报表
 *       （与设计同判据，不是本片新加的限制）。</li>
 * </ul>
 */
@Slf4j
@Service
public class ProductionStuckPointService {

    /** 三态 · 没开工（从未报过工）：{@code done_qty = 0} 且 {@code done_at IS NULL}。 */
    public static final String STATE_NOT_STARTED = "not_started";

    /** 三态 · 做了一半：{@code 0 < done_qty < qty}。 */
    public static final String STATE_IN_PROGRESS = "in_progress";

    /** 三态 · 已完成：{@code done_qty ≥ qty}（= 既有 {@link ProductionService#isDone}）。 */
    public static final String STATE_COMPLETED = "completed";

    /**
     * 卡点种类 · 没开工（A 模式**唯一**一种，设计 §6.1 行① / 裁定②-3）。
     * 非空即「这道卡住了」；{@code null} = 未卡（§3.1 逐字：「非空 = 这道卡住了，附判据与阈值来源」）。
     */
    public static final String KIND_NOT_STARTED = "not_started";

    /** 阈值来源 · S3 全局默认常量（设计 §6.4）。S1（历史中位数）落码后才会出现 {@code "history"}。 */
    public static final String THRESHOLD_SOURCE_DEFAULT = "default";

    /** 本报表判定的模式 = A（§6 裁定②-3：A 模式只查「没开工」那一种）。 */
    public static final String MODE_A = "A";

    /**
     * S3 兜底默认阈值（小时）= 设计 §6.4 的示例值（逐字「如 {@code T_wait = 4h}」），
     * <b>可配</b>：{@code migao.production.stuck-point.wait-threshold-hours}。
     *
     * <p>⚠️ 这是 <b>S3 兜底</b>，不是业务裁定值（§8 A2 待裁定）⇒ 响应恒带
     * {@code threshold_source}，调用方一眼能看出「这个阈值是兜底来的」。</p>
     */
    public static final double DEFAULT_WAIT_THRESHOLD_HOURS = 4.0;

    private final ProductionService productionService;
    private final ProcessingPositionOperationMapper positionOperationMapper;
    private final ProcessingOrderSetMapper orderSetMapper;

    /** 等开工多久算卡（小时）。S3：全局默认常量，可配（设计 §6.4）。 */
    private final double waitThresholdHours;

    public ProductionStuckPointService(
            ProductionService productionService,
            ProcessingPositionOperationMapper positionOperationMapper,
            ProcessingOrderSetMapper orderSetMapper,
            @Value("${migao.production.stuck-point.wait-threshold-hours:4}")
            double waitThresholdHours) {
        this.productionService = productionService;
        this.positionOperationMapper = positionOperationMapper;
        this.orderSetMapper = orderSetMapper;
        this.waitThresholdHours = waitThresholdHours;
    }

    // ============================================================ ① 三态判据（唯一一份）

    /**
     * 三态判定（互斥且完备，见类 javadoc ①）。
     *
     * @return {@link #STATE_NOT_STARTED} / {@link #STATE_IN_PROGRESS} / {@link #STATE_COMPLETED}
     */
    public String stateOf(ProcessingPositionOperation op) {
        if (productionService.isDone(op)) {
            return STATE_COMPLETED;
        }
        BigDecimal done = op.getDoneQty();
        if (done == null || done.signum() == 0) {
            // 没开工 = done_qty = 0 **且** done_at IS NULL（issue #4776 逐字）。
            // 矛盾态（done_qty=0 而 done_at 非空，与切片 ②「isDone 才落笔」矛盾）**不判没开工**：
            // 宁可漏报卡点，也不把「已经动过」的活报成「没人扫」。
            return op.getDoneAt() == null ? STATE_NOT_STARTED : STATE_IN_PROGRESS;
        }
        // 0 < done_qty < qty ⇒ 做了一半（报工允许部分数量 ⇒ status 仍是 'pending'）
        return STATE_IN_PROGRESS;
    }

    /** 是否「没开工」（A 模式卡点判据的**基座**）。 */
    public boolean isNotStarted(ProcessingPositionOperation op) {
        return STATE_NOT_STARTED.equals(stateOf(op));
    }

    // ============================================================ ② 卡点视图（§3.1 的 stalled 键）

    /**
     * 一道工序的卡点视图 —— 即设计 §3.1 一屏输出里的 {@code stalled} 键
     * （逐字：「{@code "stalled": { "kind": null }} // §6：非空 = 这道卡住了，附判据与阈值来源」）。
     *
     * <p>切片 ① 已逐字登记「{@code stalled}（§3.1）属切片 ③（卡点报表），本切片不落」⇒
     * 本方法就是那笔欠账的兑现：<b>只加一个键</b>，既有键一字不动。</p>
     *
     * @param setOperations 该套的活跃工序实例（前道在**本套**内找）
     * @param op            被判定的那道工序（{@code null} = 本次没有待做工序 ⇒ 无卡点可言）
     * @param now           当前时刻（测试可注入 ⇒ 「等了多久」可确定复现，不依赖挂钟）
     */
    public Map<String, Object> stalledView(List<ProcessingPositionOperation> setOperations,
                                          ProcessingPositionOperation op, OffsetDateTime now) {
        Map<String, Object> view = new LinkedHashMap<>();
        view.put("kind", null);
        view.put("state", null);
        view.put("predecessor_operation_id", null);
        view.put("predecessor_seq", null);
        view.put("predecessor_done", null);
        view.put("predecessor_done_at", null);
        view.put("stalled_hours", null);
        view.put("threshold_hours", waitThresholdHours);
        view.put("threshold_source", THRESHOLD_SOURCE_DEFAULT);
        if (op == null) {
            return view;
        }
        String state = stateOf(op);
        view.put("state", state);

        ProcessingPositionOperation predecessor = immediatePredecessor(setOperations, op);
        boolean predecessorDone = predecessor != null && productionService.isDone(predecessor);
        OffsetDateTime since = predecessor == null ? null : predecessor.getDoneAt();
        view.put("predecessor_operation_id", predecessor == null ? null : predecessor.getId());
        view.put("predecessor_seq", predecessor == null ? null : predecessor.getSeq());
        view.put("predecessor_done", predecessorDone);
        view.put("predecessor_done_at", since);

        // A 模式唯一判据（§6.1 行①）：没开工 + 上道已完成 + 上道完成时刻可知 + 等超阈值。
        // 🔴 等待时长**只**取自 predecessor.done_at —— updated_at 会被任何更新污染（§6.1 / D8）。
        if (!STATE_NOT_STARTED.equals(state) || !predecessorDone || since == null) {
            return view;
        }
        double stalledHours = hoursBetween(since, now);
        view.put("stalled_hours", stalledHours);
        if (stalledHours > waitThresholdHours) {
            view.put("kind", KIND_NOT_STARTED);
        }
        return view;
    }

    /** {@code stalledView} 的挂钟版（生产路径用；测试注入固定 {@code now} 保证可复现）。 */
    public Map<String, Object> stalledView(List<ProcessingPositionOperation> setOperations,
                                          ProcessingPositionOperation op) {
        return stalledView(setOperations, op, OffsetDateTime.now());
    }

    // ============================================================ ③ A 模式卡点报表（§6.3）

    /**
     * A 模式卡点报表：按**套 × 工序**列出「没开工」（设计 §6.3 的 SQL 逐条对齐，见类 javadoc）。
     *
     * @param processingOrderId 可选：只看某一个加工单（{@code null} / 空白 = 本租户全部活跃加工单）
     * @param tenantId          当前租户（**必带**：跨租户 fail-closed，与既有读面同款）
     * @return 报表（见下），键全部是**新增**（既有端点一字不动）
     */
    public Map<String, Object> report(String processingOrderId, Long tenantId) {
        return report(processingOrderId, tenantId, OffsetDateTime.now());
    }

    /**
     * 报表（可注入 {@code now} ⇒ 「等了多久 / 卡不卡」在测试里确定复现）。
     * <b>包级可见</b>：只给同包测试注入挂钟，生产路径走上面那个 public 重载。
     *
     * <p>响应形状：</p>
     * <pre>
     * {
     *   "mode": "A",                      // §6 裁定②-3：A 模式只查「没开工」那一种
     *   "threshold_hours": 4.0,           // §6.4 的 T_wait
     *   "threshold_source": "default",    // §6.4：「阈值从哪来」必须可解释
     *   "scope": {"processing_order_id": null},
     *   "states": {"not_started": n, "in_progress": n, "completed": n},   // 三态计数（可区分）
     *   "stuck_total": n,
     *   "stuck": [ {kind, processing_order_id, set_id, set_no, set_index,
     *               position:{order_item_id, position_kind, position_name},
     *               operation:{operation_id, logical_name, position, seq, unit, qty, done_qty, state},
     *               predecessor:{operation_id, logical_name, seq, done_at},
     *               stalled_hours, threshold_hours, threshold_source} ]   // 按 stalled_hours 降序（§6.3）
     * }
     * </pre>
     */
    Map<String, Object> report(String processingOrderId, Long tenantId, OffsetDateTime now) {
        String orderFilter = processingOrderId == null || processingOrderId.isBlank()
                ? null : processingOrderId.trim();

        // 套（live）：§6.3 的 `JOIN processing_order_sets s ON s.id = o.set_id AND s.deleted = 0`
        List<ProcessingOrderSet> sets = orderSetMapper.selectList(new LambdaQueryWrapper<ProcessingOrderSet>()
                .eq(ProcessingOrderSet::getTenantId, tenantId)
                .eq(ProcessingOrderSet::getDeleted, 0)
                .eq(orderFilter != null, ProcessingOrderSet::getProcessingOrderId, orderFilter));
        Map<String, ProcessingOrderSet> liveSets = new LinkedHashMap<>();
        for (ProcessingOrderSet set : sets == null ? List.<ProcessingOrderSet>of() : sets) {
            liveSets.put(set.getId(), set);
        }

        // 工序实例（活跃 + 有套归属）：`o.tenant_id = ? AND o.deleted = 0`
        List<ProcessingPositionOperation> rows = positionOperationMapper.selectList(
                new LambdaQueryWrapper<ProcessingPositionOperation>()
                        .eq(ProcessingPositionOperation::getTenantId, tenantId)
                        .eq(ProcessingPositionOperation::getDeleted, 0)
                        .isNotNull(ProcessingPositionOperation::getSetId)
                        .eq(orderFilter != null, ProcessingPositionOperation::getProcessingOrderId,
                                orderFilter));

        // INNER JOIN 语义：套行必须 live（软删套的实例行不进报表）
        List<ProcessingPositionOperation> scoped = new ArrayList<>();
        Map<String, List<ProcessingPositionOperation>> byOrder = new LinkedHashMap<>();
        Map<String, Integer> states = new LinkedHashMap<>();
        states.put(STATE_NOT_STARTED, 0);
        states.put(STATE_IN_PROGRESS, 0);
        states.put(STATE_COMPLETED, 0);
        for (ProcessingPositionOperation op : rows == null ? List.<ProcessingPositionOperation>of() : rows) {
            if (op.getSetId() == null || !liveSets.containsKey(op.getSetId())) {
                continue;
            }
            scoped.add(op);
            byOrder.computeIfAbsent(op.getProcessingOrderId(), k -> new ArrayList<>()).add(op);
            states.merge(stateOf(op), 1, Integer::sum);
        }

        List<Map<String, Object>> stuck = new ArrayList<>();
        for (ProcessingPositionOperation op : scoped) {
            if (!isNotStarted(op)) {
                continue;
            }
            // 前道在**同加工单 × 同部位**内找（§6.3：p.processing_order_id = o.processing_order_id
            // AND p.order_item_id IS NOT DISTINCT FROM o.order_item_id）
            ProcessingPositionOperation predecessor =
                    immediatePredecessor(byOrder.get(op.getProcessingOrderId()), op);
            if (predecessor == null || !productionService.isDone(predecessor)
                    || predecessor.getDoneAt() == null) {
                continue;
            }
            double stalledHours = hoursBetween(predecessor.getDoneAt(), now);
            if (stalledHours <= waitThresholdHours) {
                continue;
            }
            stuck.add(stuckRow(op, liveSets.get(op.getSetId()), predecessor, stalledHours));
        }
        // §6.3：`ORDER BY stalled_hours DESC`
        stuck.sort(Comparator.comparingDouble(
                (Map<String, Object> row) -> (Double) row.get("stalled_hours")).reversed());

        Map<String, Object> report = new LinkedHashMap<>();
        report.put("mode", MODE_A);
        report.put("threshold_hours", waitThresholdHours);
        report.put("threshold_source", THRESHOLD_SOURCE_DEFAULT);
        Map<String, Object> scope = new LinkedHashMap<>();
        scope.put("processing_order_id", orderFilter);
        report.put("scope", scope);
        report.put("states", states);
        report.put("stuck_total", stuck.size());
        report.put("stuck", stuck);
        return report;
    }

    /** 报表的一行（§6.3 的列 + 「上道几点完成」）。 */
    private Map<String, Object> stuckRow(ProcessingPositionOperation op, ProcessingOrderSet set,
                                         ProcessingPositionOperation predecessor, double stalledHours) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("kind", KIND_NOT_STARTED);
        row.put("processing_order_id", op.getProcessingOrderId());
        row.put("set_id", op.getSetId());
        row.put("set_no", set == null ? null : set.getSetNo());
        row.put("set_index", set == null ? null : set.getSetIndex());

        Map<String, Object> position = new LinkedHashMap<>();
        position.put("order_item_id", op.getOrderItemId());
        position.put("position_kind", op.getPositionKind());
        position.put("position_name", op.getPositionName());
        row.put("position", position);

        Map<String, Object> operation = new LinkedHashMap<>();
        operation.put("operation_id", op.getId());
        operation.put("logical_name",
                ProductionOperationQueryService.logicalOperationName(op.getOperationName()));
        operation.put("position", ProductionOperationQueryService.displayPosition(
                op.getOperationName(), op.getPositionKind()));
        operation.put("seq", op.getSeq());
        operation.put("unit", op.getUnit());
        operation.put("qty", op.getQty());
        operation.put("done_qty", op.getDoneQty());
        operation.put("state", stateOf(op));
        row.put("operation", operation);

        Map<String, Object> previous = new LinkedHashMap<>();
        previous.put("operation_id", predecessor.getId());
        previous.put("logical_name",
                ProductionOperationQueryService.logicalOperationName(predecessor.getOperationName()));
        previous.put("seq", predecessor.getSeq());
        previous.put("done_at", predecessor.getDoneAt());
        row.put("predecessor", previous);

        row.put("stalled_hours", stalledHours);
        row.put("threshold_hours", waitThresholdHours);
        row.put("threshold_source", THRESHOLD_SOURCE_DEFAULT);
        return row;
    }

    // ============================================================ 纯函数

    /**
     * 立即前道 = 同加工单 × 同 {@code order_item_id}（**null-safe**，= SQL 的
     * {@code IS NOT DISTINCT FROM}，§6.3 ⚠️）中 {@code seq} 最大的**更小** {@code seq}。
     *
     * <p>「找不到」的三种形态都返回 {@code null}（= 不进卡点表，§6.3）：首道工序没有更小
     * {@code seq}；本行 {@code seq} 为 NULL（判不出顺序 ⇒ 不猜）；同部位没有其他活跃行。</p>
     *
     * <p>{@code seq} 并列（脏数据）时取 {@code id} 最小的那个 ⇒ 结果**确定**（同输入同输出），
     * 不随查询返回顺序漂移。</p>
     */
    private static ProcessingPositionOperation immediatePredecessor(
            List<ProcessingPositionOperation> operations, ProcessingPositionOperation op) {
        if (op.getSeq() == null || operations == null) {
            return null;
        }
        ProcessingPositionOperation best = null;
        for (ProcessingPositionOperation candidate : operations) {
            if (candidate == null || Objects.equals(candidate.getId(), op.getId())) {
                continue;
            }
            if (!Objects.equals(candidate.getOrderItemId(), op.getOrderItemId())) {
                continue;
            }
            if (candidate.getSeq() == null || candidate.getSeq() >= op.getSeq()) {
                continue;
            }
            if (best == null || candidate.getSeq() > best.getSeq()
                    || (candidate.getSeq().equals(best.getSeq()) && idOf(candidate).compareTo(idOf(best)) < 0)) {
                best = candidate;
            }
        }
        return best;
    }

    private static String idOf(ProcessingPositionOperation op) {
        return op.getId() == null ? "" : op.getId();
    }

    /** 等待时长（小时）= {@code (now - since) / 3600}（与 §6.3 的 {@code EXTRACT(EPOCH …)/3600.0} 同口径）。 */
    private static double hoursBetween(OffsetDateTime since, OffsetDateTime now) {
        return Duration.between(since, now).toMillis() / 3_600_000.0;
    }
}
