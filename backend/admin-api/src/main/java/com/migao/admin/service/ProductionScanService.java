package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProcessingOrderSet;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.entity.ProcessingSetPartToken;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingOrderSetMapper;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
import com.migao.admin.mapper.ProcessingSetPartTokenMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Predicate;

/**
 * 扫码解析 + 工序推断（切片 ①，issue #4698；设计 {@code docs/design/set-code-and-scan-loop.md} §2.3 / §2.6 / §3）。
 *
 * <p><b>本切片是只读面</b>：只到「解析出 (套, 部位) + 推断出该报哪一道工序 + 返回一屏所需数据」，
 * <b>不写库</b>（报工主闭环 = 切片 ②）。因此本类的全部方法都**不**带 {@code @Transactional}、
 * **不**落任何痕。</p>
 *
 * <h2>① 解析顺序（设计 §2.6，五形态）</h2>
 * <ol>
 *   <li><b>新 token</b>（{@code processing_set_part_tokens.token}，带套带部位）⇒ 返回
 *       {@code (set_id, order_item_id, position)}，<b>部位由码给出、工人不选</b>；</li>
 *   <li>旧 {@code processing_orders.qr_token} → ③ {@code processing_order_no} → ④ {@code order_no}
 *       → ⑤ 内部 {@code order_id} —— 后四形态是 {@link ProductionService#resolveOrder} 的
 *       <b>既有冻结契约，一字不动</b>（issue #4005 / #4222），本类**只调用、不复制**；</li>
 * </ol>
 * 旧码命中 ⇒ <b>降级形态</b>：{@code granularity="order"} + {@code needs_selection:["set","position"]}
 * + 可选清单（该单的套 × 部位）。🔴 <b>绝不默认取第 1 套</b> —— 默认 = 静默把进度记到错的套上，
 * 正是要治的病（设计 §2.6）。降级形态的 {@code set_no} / {@code set_index} / {@code position} /
 * {@code operation} 一律 {@code null}（**不猜**）。
 *
 * <h2>② 推断算法（设计 §3.2）</h2>
 * <pre>
 * ① 部位级：扫到的那个部位的未完成工序 ⇒ min(seq)
 * ② 套级回落：本部位干完了，但整樘窗还有套级活（打卷/装袋/发货）⇒ min(seq) + rerouted=true
 * ③ 本套无活可做 ⇒ completed=true（不报错）
 * </pre>
 * <b>为什么必须有 ②</b>：套级工序只落在樘窗组的主布行（F11）⇒ 工人做完纱帘、拿纱帘的码再扫时，
 * 只按 ① 会得到「无工序可做」，而整樘窗其实还没做完 ⇒ 闭环断在这里。
 *
 * <h2>③ 硬约束：工序必须确定（设计 §3.3，用户裁定②-2）</h2>
 * 「不拦生产顺序」管<b>准入</b>，「工序必须确定」管<b>记账的确定性</b>（工资不能记到猜的那道）。
 * 本类兑现前半句的**唯一**实现方式：<b>绝不产出非唯一确定的工序</b> ——
 * 推断出多道（{@code seq} 重复的脏数据）且未显式给 {@code operation_id} ⇒
 * {@code OPERATION_AMBIGUOUS}（422，不返回任何工序），<b>不静默取第一道</b>。
 * 切片 ② 的记账入口在此之上加「未确定 ⇒ 拒绝写 {@code production_work_logs}」。
 *
 * <p><b>与设计的偏离（照实登记）</b>：</p>
 * <ul>
 *   <li>{@code PENDING} 的判据用<b>既有</b> {@link ProductionService#isDone}（{@code done_qty ≥ qty}），
 *       而不是设计 §3.2 字面的 {@code status <> 'done'} —— 报工允许**部分数量**
 *       （{@code assertWithinPlannedQty} 只拒绝超上限），而 {@code advanceDoneQtyIfUnchanged}
 *       一旦推进就把 {@code status} 置 {@code 'done'} ⇒ 照字面实现会让「报了 6/11 米」的工序
 *       从默认建议里消失、**永远做不完**（与 §3.4「默认数量 = 应做数量」的续报语义冲突）。
 *       取既有口径同时满足「不新造第二份口径」。</li>
 *   <li>§3.1 的 {@code display_name} 不落：显示名 = {@code logical_name} + {@code position}，
 *       由**既有**前端 helper 拼接（本类只给两个源键）—— 在 Java 侧再拼一份就是第二份口径
 *       （#4621 / #4630 的同族纪律）。</li>
 *   <li>{@code stalled}（§3.1）属切片 ③（卡点报表），本切片不落。</li>
 * </ul>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ProductionScanService {

    /** 解析粒度：新码（套 × 部位）—— 部位由码给出，工人不选。 */
    public static final String GRANULARITY_SET_POSITION = "set_position";

    /** 解析粒度：旧码降级（加工单级）—— 必须选套 + 选部位（设计 §2.6）。 */
    public static final String GRANULARITY_ORDER = "order";

    /** 推断来源：系统推断的下一道待做。 */
    public static final String DETERMINED_BY_INFERRED = "inferred";

    /** 推断来源：工人一键改（显式指定）。 */
    public static final String DETERMINED_BY_PICKED = "picked";

    /** 套级工序的作用域取值（{@code production_operations.scope}，V67 / issue #4384 A1）。 */
    private static final String SCOPE_SET = "set";

    /** 旧码降级形态必须由工人补齐的两个选择（设计 §2.6 逐字）。 */
    private static final List<String> DEGRADED_NEEDS_SELECTION = List.of("set", "position");

    private final ProcessingSetPartTokenMapper setPartTokenMapper;
    private final ProcessingOrderSetMapper orderSetMapper;
    private final ProcessingOrderMapper processingOrderMapper;
    private final ProcessingPositionOperationMapper positionOperationMapper;
    private final OrderItemMapper orderItemMapper;
    /** 工序库（判「部位级 / 套级」的**唯一**来源：实例行不带 scope，逐字取库、不硬编码工序名）。 */
    private final ProductionOperationQueryService operationQueryService;
    /**
     * 复用**冻结的四形态订单解析**（issue #4005 / #4222）：旧码路径必须是同一份实现 ——
     * 在扫描侧再写一份就是第二份口径（两处迟早不同），故只调用 {@link ProductionService#resolveOrder}。
     */
    private final ProductionService productionService;

    // ============================================================ 解析入口

    /**
     * 扫码解析 + 工序推断（只读）。
     *
     * @param token       码内容 / 手输号：新 token 优先，未命中回落既有四形态（qr_token →
     *                    processing_order_no → order_no → order_id）
     * @param operationId 可选：工人「一键改」指定的工序（必须属于本次扫码的部位/套，否则 422）
     * @param tenantId    当前租户
     * @return 一屏所需数据（见类 javadoc）；旧码 ⇒ 降级形态 + {@code needs_selection}
     */
    public Map<String, Object> resolve(String token, String operationId, Long tenantId) {
        if (!StringUtils.hasText(token)) {
            throw BusinessException.validationError("扫码内容不能为空");
        }
        String key = token.trim();
        // ① 新码优先（带套带部位）；未命中**只回落**，不并行写（设计 §2.6 双读一致性）
        ProcessingSetPartToken partToken = findPartToken(key, tenantId);
        if (partToken == null) {
            // ②~⑤ 既有四形态（一字不动）；全不命中 ⇒ 404「订单不存在」（既有行为）
            return degradedView(key, tenantId);
        }
        return setPositionView(partToken, operationId, tenantId);
    }

    /** 新码命中：`token` 未撤销 + 同租户（fail-closed，`deleted = 0` 正向相等）。 */
    private ProcessingSetPartToken findPartToken(String token, Long tenantId) {
        return setPartTokenMapper.selectOne(new LambdaQueryWrapper<ProcessingSetPartToken>()
                .eq(ProcessingSetPartToken::getToken, token)
                .eq(ProcessingSetPartToken::getTenantId, tenantId)
                .eq(ProcessingSetPartToken::getDeleted, 0)
                .last("LIMIT 1"));
    }

    // ============================================================ 新码：套 × 部位 + 推断

    private Map<String, Object> setPositionView(ProcessingSetPartToken partToken, String operationId,
                                                Long tenantId) {
        ProcessingOrderSet set = requireSet(partToken, tenantId);
        ProcessingOrder po = requireProcessingOrder(set.getProcessingOrderId(), tenantId);
        List<ProcessingPositionOperation> setOperations =
                listSetOperations(po.getId(), set.getId(), tenantId);
        Map<String, Map<String, Object>> catalog = operationQueryService.operationsByName(tenantId);

        // ── ① 部位级：扫到的那个部位的未完成工序 ──────────────────────────────
        List<ProcessingPositionOperation> candidates =
                pending(setOperations, op -> partToken.getOrderItemId().equals(op.getOrderItemId()));
        // ── ② 套级回落：本部位干完 ⇒ 整樘窗的套级活（打卷/装袋/发货）──────────
        boolean rerouted = false;
        if (candidates.isEmpty()) {
            candidates = pending(setOperations, op -> SCOPE_SET.equals(scopeOf(op, catalog)));
            rerouted = !candidates.isEmpty();
        }
        List<ProcessingPositionOperation> sorted = sortedBySeq(candidates);

        ProcessingPositionOperation chosen = null;
        String determinedBy = null;
        if (!sorted.isEmpty()) {
            if (StringUtils.hasText(operationId)) {
                // 一键改（§3.3）：显式指定 ⇒ 必须属于本次扫码的部位/套，否则 422（不记账）
                chosen = sorted.stream()
                        .filter(op -> operationId.trim().equals(op.getId()))
                        .findFirst()
                        .orElseThrow(() -> new BusinessException("OPERATION_NOT_IN_SCAN_TARGET",
                                "工序 " + operationId.trim() + " 不属于本次扫码的部位（"
                                        + partToken.getOrderItemId() + "），不得跨部位报工",
                                422,
                                "请重新扫码，或在返回的 alternatives 里选择本部位/本套的待做工序"));
                determinedBy = DETERMINED_BY_PICKED;
            } else {
                // 🔴 硬约束：工序必须确定 —— seq 重复（脏数据）⇒ 拒绝，不静默取第一道
                int minSeq = seqOf(sorted.get(0));
                List<ProcessingPositionOperation> ties = sorted.stream()
                        .filter(op -> seqOf(op) == minSeq)
                        .toList();
                if (ties.size() > 1) {
                    throw new BusinessException("OPERATION_AMBIGUOUS",
                            "本部位有 " + ties.size() + " 道待做工序的 seq 相同（= " + minSeq
                                    + "），无法确定本次报哪一道 ⇒ 拒绝（工序未确定不得记账）",
                            422,
                            "请先在生产 → 工序库修正该部位的工序顺序（seq 必须唯一），"
                                    + "或由工人显式指定 operation_id");
                }
                chosen = ties.get(0);
                determinedBy = DETERMINED_BY_INFERRED;
            }
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("granularity", GRANULARITY_SET_POSITION);
        result.put("order_id", po.getOrderId());
        result.put("processing_order_no", po.getProcessingOrderNo());
        result.put("set_no", set.getSetNo());
        result.put("set_index", set.getSetIndex());
        result.put("position", positionView(partToken, setOperations, tenantId));
        result.put("operation", chosen == null
                ? null
                : operationView(chosen, determinedBy, rerouted));
        result.put("alternatives", alternativeViews(sorted, chosen));
        result.put("set_progress", productionService.progressOf(setOperations));
        // ③ 本套无活可做 ⇒ 「本套已完成」（含完成时刻），不报错（设计 §3.2）
        result.put("completed", chosen == null);
        result.put("completed_at", completedAt(setOperations));
        result.put("needs_selection", List.of());
        return result;
    }

    /** 套归属校验：必须同租户 + 未软删 + 与 token 的加工单一致（三任一条不成立 ⇒ 404，fail-closed）。 */
    private ProcessingOrderSet requireSet(ProcessingSetPartToken partToken, Long tenantId) {
        ProcessingOrderSet set = orderSetMapper.selectById(partToken.getSetId());
        if (set == null || !tenantId.equals(set.getTenantId())
                || !Integer.valueOf(0).equals(set.getDeleted())
                || !partToken.getProcessingOrderId().equals(set.getProcessingOrderId())) {
            throw BusinessException.notFound("套", "该码指向的套不存在或已作废，请重新打印任务卡");
        }
        return set;
    }

    private ProcessingOrder requireProcessingOrder(String processingOrderId, Long tenantId) {
        ProcessingOrder po = processingOrderMapper.selectById(processingOrderId);
        if (po == null || !tenantId.equals(po.getTenantId())
                || !Integer.valueOf(0).equals(po.getDeleted())) {
            throw BusinessException.notFound("加工单");
        }
        return po;
    }

    // ============================================================ 旧码：降级形态（强制选部位）

    /**
     * 旧码降级形态（设计 §2.6）：{@code granularity="order"} + {@code needs_selection:["set","position"]}
     * + 可选清单。
     *
     * <p>🔴 <b>绝不默认取第 1 套</b>：{@code set_no} / {@code set_index} / {@code position} /
     * {@code operation} / {@code set_progress} 一律 {@code null}（**不知道就是不知道**），
     * 第 1 套只作为 {@code selections} 里的一个候选出现 —— 由工人选一次。</p>
     */
    private Map<String, Object> degradedView(String key, Long tenantId) {
        // 既有四形态（qr_token → processing_order_no → order_no → order_id），一字不动
        Order order = productionService.resolveOrder(key, tenantId);
        ProcessingOrder po = processingOrderMapper.selectActiveByOrderId(order.getId(), tenantId);

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("granularity", GRANULARITY_ORDER);
        result.put("order_id", order.getId());
        result.put("processing_order_no", po == null ? null : po.getProcessingOrderNo());
        result.put("set_no", null);
        result.put("set_index", null);
        result.put("position", null);
        result.put("operation", null);
        result.put("alternatives", List.of());
        result.put("set_progress", null);
        // null = **未知**（降级形态判不出是哪一套 ⇒ 判不出完没完），不是 false
        result.put("completed", null);
        result.put("completed_at", null);
        result.put("needs_selection", DEGRADED_NEEDS_SELECTION);
        result.put("selections", po == null ? List.of() : selectionView(po, tenantId));
        return result;
    }

    /**
     * 可选清单 = 该单的**套 × 部位**（设计 §2.6）。
     *
     * <p>部位取自该单**活跃工序实例**的 {@code order_item_id}（= 真能报工的部位；未实例化的套给空清单，
     * 因为对它无可报之事），按 {@code set_index} 升序、套内按既有读面同序（部位名 → seq）。</p>
     */
    private List<Map<String, Object>> selectionView(ProcessingOrder po, Long tenantId) {
        List<ProcessingOrderSet> sets = orderSetMapper.selectList(
                new LambdaQueryWrapper<ProcessingOrderSet>()
                        .eq(ProcessingOrderSet::getProcessingOrderId, po.getId())
                        .eq(ProcessingOrderSet::getTenantId, tenantId)
                        .eq(ProcessingOrderSet::getDeleted, 0)
                        .orderByAsc(ProcessingOrderSet::getSetIndex));
        List<ProcessingPositionOperation> operations = listOrderOperations(po.getId(), tenantId);

        List<Map<String, Object>> views = new ArrayList<>();
        for (ProcessingOrderSet set : sets == null ? List.<ProcessingOrderSet>of() : sets) {
            Set<String> seen = new LinkedHashSet<>();
            List<Map<String, Object>> positions = new ArrayList<>();
            for (ProcessingPositionOperation op : operations) {
                if (!set.getId().equals(op.getSetId()) || op.getOrderItemId() == null
                        || !seen.add(op.getOrderItemId())) {
                    continue;
                }
                positions.add(positionEntry(op.getOrderItemId(), op.getPositionKind(),
                        op.getPositionName()));
            }
            Map<String, Object> view = new LinkedHashMap<>();
            view.put("set_id", set.getId());
            view.put("set_no", set.getSetNo());
            view.put("set_index", set.getSetIndex());
            view.put("positions", positions);
            views.add(view);
        }
        return views;
    }

    // ============================================================ 整形

    private Map<String, Object> positionView(ProcessingSetPartToken partToken,
                                             List<ProcessingPositionOperation> setOperations,
                                             Long tenantId) {
        String positionName = setOperations.stream()
                .filter(op -> partToken.getOrderItemId().equals(op.getOrderItemId()))
                .map(ProcessingPositionOperation::getPositionName)
                .filter(StringUtils::hasText)
                .findFirst()
                .orElseGet(() -> productNameOf(partToken.getOrderItemId(), tenantId));
        return positionEntry(partToken.getOrderItemId(), partToken.getPositionKind(), positionName);
    }

    private static Map<String, Object> positionEntry(String orderItemId, String positionKind,
                                                     String positionName) {
        Map<String, Object> view = new LinkedHashMap<>();
        view.put("order_item_id", orderItemId);
        view.put("position_kind", positionKind);
        view.put("position_name", positionName);
        return view;
    }

    /**
     * 一屏上的「这次报哪一道」。
     *
     * <p>{@code unit_price} 为 {@code null} = <b>未定价</b>（≠ 0 元，V90 / issue #4696）——
     * 读面**不折 0**；{@code rerouted=true} = 本部位已干完、系统换到了**套级工序**（§3.2 ②），
     * 此时额外给 {@code carrier}（该套级工序的承载部位）⇒ 工人知道去哪做，**不静默换工序**。</p>
     */
    private static Map<String, Object> operationView(ProcessingPositionOperation op, String determinedBy,
                                                     boolean rerouted) {
        Map<String, Object> view = new LinkedHashMap<>();
        view.put("operation_id", op.getId());
        view.put("logical_name",
                ProductionOperationQueryService.logicalOperationName(op.getOperationName()));
        view.put("position", ProductionOperationQueryService.displayPosition(
                op.getOperationName(), op.getPositionKind()));
        view.put("group_name", op.getGroupName());
        view.put("unit", op.getUnit());
        view.put("qty", nz(op.getQty()));
        view.put("qty_source", op.getQtySource());
        view.put("unit_price", op.getUnitPrice());
        view.put("seq", op.getSeq());
        view.put("status", op.getStatus());
        view.put("determined_by", determinedBy);
        view.put("rerouted", rerouted);
        if (rerouted) {
            view.put("carrier", positionEntry(op.getOrderItemId(), op.getPositionKind(),
                    op.getPositionName()));
        }
        return view;
    }

    /** 一键改的候选 = 与默认项**同一层级**的其他待做工序（部位级命中 ⇒ 同部位；套级回落 ⇒ 同套级）。 */
    private static List<Map<String, Object>> alternativeViews(List<ProcessingPositionOperation> sorted,
                                                             ProcessingPositionOperation chosen) {
        List<Map<String, Object>> views = new ArrayList<>();
        for (ProcessingPositionOperation op : sorted) {
            if (chosen != null && chosen.getId().equals(op.getId())) {
                continue;
            }
            Map<String, Object> view = new LinkedHashMap<>();
            view.put("operation_id", op.getId());
            view.put("logical_name",
                    ProductionOperationQueryService.logicalOperationName(op.getOperationName()));
            view.put("position", ProductionOperationQueryService.displayPosition(
                    op.getOperationName(), op.getPositionKind()));
            view.put("seq", op.getSeq());
            view.put("qty", nz(op.getQty()));
            view.put("unit", op.getUnit());
            views.add(view);
        }
        return views;
    }

    // ============================================================ 查询 / 纯函数

    private List<ProcessingPositionOperation> listSetOperations(String processingOrderId, String setId,
                                                                Long tenantId) {
        List<ProcessingPositionOperation> rows = positionOperationMapper.selectList(
                new LambdaQueryWrapper<ProcessingPositionOperation>()
                        .eq(ProcessingPositionOperation::getProcessingOrderId, processingOrderId)
                        .eq(ProcessingPositionOperation::getTenantId, tenantId)
                        .eq(ProcessingPositionOperation::getSetId, setId)
                        .eq(ProcessingPositionOperation::getDeleted, 0)
                        .orderByAsc(ProcessingPositionOperation::getPositionName)
                        .orderByAsc(ProcessingPositionOperation::getSeq));
        return rows == null ? List.of() : rows;
    }

    private List<ProcessingPositionOperation> listOrderOperations(String processingOrderId, Long tenantId) {
        List<ProcessingPositionOperation> rows = positionOperationMapper.selectList(
                new LambdaQueryWrapper<ProcessingPositionOperation>()
                        .eq(ProcessingPositionOperation::getProcessingOrderId, processingOrderId)
                        .eq(ProcessingPositionOperation::getTenantId, tenantId)
                        .eq(ProcessingPositionOperation::getDeleted, 0)
                        .orderByAsc(ProcessingPositionOperation::getPositionName)
                        .orderByAsc(ProcessingPositionOperation::getSeq));
        return rows == null ? List.of() : rows;
    }

    private String productNameOf(String orderItemId, Long tenantId) {
        if (orderItemId == null) {
            return null;
        }
        OrderItem item = orderItemMapper.selectById(orderItemId);
        if (item == null || !tenantId.equals(item.getTenantId())
                || Integer.valueOf(1).equals(item.getDeleted())) {
            return null;
        }
        return item.getProductName();
    }

    private List<ProcessingPositionOperation> pending(List<ProcessingPositionOperation> operations,
                                                      Predicate<ProcessingPositionOperation> match) {
        return operations.stream()
                .filter(match)
                .filter(op -> !productionService.isDone(op))
                .toList();
    }

    private static List<ProcessingPositionOperation> sortedBySeq(List<ProcessingPositionOperation> operations) {
        List<ProcessingPositionOperation> sorted = new ArrayList<>(operations);
        sorted.sort(Comparator.comparingInt(ProductionScanService::seqOf)
                .thenComparing(op -> op.getId() == null ? "" : op.getId()));
        return sorted;
    }

    private static int seqOf(ProcessingPositionOperation op) {
        return op.getSeq() == null ? Integer.MAX_VALUE : op.getSeq();
    }

    /** 套级工序的判据 = **工序库**的 `scope`（逐字取库，不硬编码工序名）；库中缺该工序 ⇒ 不是套级。 */
    private static String scopeOf(ProcessingPositionOperation op,
                                  Map<String, Map<String, Object>> catalog) {
        Map<String, Object> meta = catalog.get(op.getOperationName());
        Object scope = meta == null ? null : meta.get("scope");
        return scope == null ? null : String.valueOf(scope);
    }

    /** 本套完成时刻 = **已完成**工序里最晚的 `done_at`（切片 ② 才写入；无 ⇒ null，不猜）。 */
    private OffsetDateTime completedAt(List<ProcessingPositionOperation> operations) {
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

    private static BigDecimal nz(BigDecimal value) {
        return value == null ? BigDecimal.ZERO : value;
    }
}
