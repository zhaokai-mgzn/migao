package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.QualityCheck;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.QualityCheckMapper;
import com.migao.admin.worker.WorkerIdentity;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.time.DayOfWeek;
import java.time.Duration;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.time.temporal.TemporalAdjusters;
import java.time.temporal.WeekFields;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;

/**
 * 质检记录（**成品帘级**）—— issue #5652 的第一刀。
 *
 * <p>🔴 <b>口径（用户 2026-10-16 逐字裁定，本类不得偏离）</b>：
 * ① <b>颗粒度 =「是按成品帘来检查的」</b>—— 一条记录 = <b>一件成品帘</b>
 * （{@code orderItemId} 级）：不逐工序、不逐工序完工检；
 * ② <b>录入者 =「B 独立质检员」</b>—— 判定由质检员录入（权限面 = 端点上的
 * {@code @RequirePermission}，本类不重复判权限）；报工人<b>只报数量</b>；
 * ③ <b>判定 ≠ 合格 ⇒ 原因必填</b>—— 缺原因 = 422 具名报错，<b>绝不静默存</b>。</p>
 *
 * <p>🔴 <b>两套口径并存、互不覆盖</b>（本单红线）：报工（{@code ProductionWorkLog}）是
 * <b>数量事实</b>，本类是<b>质检判定</b>。本类<b>不</b>读写任何报工行、<b>不</b>重算
 * {@code qty}/{@code qualifiedQty}；质检也<b>不</b>参与计件（返工/报废不计件是报工侧
 * {@code workType} 的既有口径，本单一个字都没碰）—— 本类只落**一张新表**。</p>
 *
 * <p>租户隔离：写入落 {@code tenantId}（由调用方从 {@code TenantContext} 取），读取由
 * {@code TenantLineInnerInterceptor} 注入租户谓词；跨租户的成品帘 ⇒ <b>404</b>
 * （与「不存在」逐字同一形态，不泄露存在性）。</p>
 */
@Service
@RequiredArgsConstructor
public class QualityCheckService {

    /** 表名（读面按 id 反查时用；不新造第二份字符串常量在别处）。 */
    public static final String TABLE = "quality_inspections";

    /**
     * 质检三态（<b>成品帘判定</b>）：{@code pass} 合格 / {@code rework} 返工 / {@code scrap} 报废。
     *
     * <p>取值形态<b>复用</b>报工侧既有习惯（小写 ASCII 单词），但语义面<b>各自独立</b> ——
     * 报工的 {@code work_type} 说的是「这一笔报的是什么货」，本判定说的是「这一件成品帘判了什么」。
     * 两处<b>不</b>互相引用、<b>不</b>互相改写（用户裁定的「两套口径并存」）。</p>
     */
    public static final Set<String> RESULTS = Set.of("pass", "rework", "scrap");

    /** 检验人身份类别（V163，issue #7162）：观星台员工 / 工人端。 */
    public static final String INSPECTOR_EMPLOYEE = "employee";
    public static final String INSPECTOR_WORKER = "worker";
    private static final Set<String> INSPECTOR_KINDS = Set.of(INSPECTOR_EMPLOYEE, INSPECTOR_WORKER);

    /** 判为合格时允许原因为空后的文案锚（供报错文案复用）。 */
    private static final String REASON_REQUIRED =
            "质检判定为「%s」时必须填写不合格原因（判定 ≠ 合格 ⇒ 原因必填）";

    /** 参与质检的加工单状态（与 {@link #create} 的「活跃加工单」同一集合 —— 已取消的单不质检）。 */
    private static final List<String> TARGET_PROCESSING_STATUSES =
            List.of("generated", "issued", "in_processing", "completed");

    /** 待检清单分页（服务端封顶：一次不许拉爆整租户）。 */
    private static final int TARGETS_DEFAULT_SIZE = 20;
    private static final int TARGETS_MAX_SIZE = 100;

    private final QualityCheckMapper qualityInspectionMapper;

    /**
     * 单据联动工序（issue #7165）：**字段注入**而非构造参数 —— 本类构造签名被单测显式装配，
     * 加参数会把它们全改一遍（{@code OrderService} 的 {@code poolChangeNotifier} 同款先例）。
     * {@code null} = 未装配（单测切片）⇒ 跳过联动，不影响记录落库。
     */
    @Autowired(required = false)
    private DocumentOperationLinkage documentOperationLinkage;
    private final OrderItemMapper orderItemMapper;
    private final ProcessingOrderMapper processingOrderMapper;
    /** 加工单 → 所属销售订单号（待检清单要显示「这张加工单是哪个订单的」，issue #7160）。 */
    private final OrderMapper orderMapper;
    /** 加工单快照解析：`items_snapshot` 可能是 JSON 字符串形态（自定义 `@Select` 不经 typeHandler）。 */
    private final ObjectMapper objectMapper;

    /**
     * 录入一条质检记录（成品帘级）。
     *
     * @param tenantId   当前租户（调用方从 {@code TenantContext} 取，**不**从 body 取）
     * @param orderItemId 一件成品帘（{@code order_items.id}）—— 质检的**唯一**颗粒度
     * @param result     质检三态之一（{@code pass}/{@code rework}/{@code scrap}）
     * @param reason     不合格原因：判定 ≠ {@code pass} 时必填
     * @param inspectorId   检验人 id（服务端从 {@code SecurityContext} 解）
     * @param inspectorName 检验人展示名
     * @param inspectedAt   检验时刻（调用方取业务时钟单点 {@code BusinessClock}）
     * @return 逐字段可读的记录视图（判定/原因/检验人/时刻/成品帘）
     */
    public Map<String, Object> create(Long tenantId, String orderItemId, String result, String reason,
                                      String inspectorId, String inspectorName, OffsetDateTime inspectedAt) {
        return create(tenantId, orderItemId, result, reason, inspectorId, inspectorName,
                INSPECTOR_EMPLOYEE, inspectedAt);
    }

    /**
     * 录入一条质检记录（带**检验人身份类别**，issue #7162）—— 工人端扫描后录判定走这里。
     *
     * @param inspectorKind {@code employee}（观星台）/ {@code worker}（工人 session）；未知值 ⇒ 422
     */
    public Map<String, Object> create(Long tenantId, String orderItemId, String result, String reason,
                                      String inspectorId, String inspectorName, String inspectorKind,
                                      OffsetDateTime inspectedAt) {
        return create(tenantId, orderItemId, result, reason, inspectorId, inspectorName, inspectorKind,
                inspectedAt, null);
    }

    /**
     * 同上 + **工人身份**（issue #7165）：工人端录判定时，合格 ⇒ 联动完成该件成品帘的「质检」工序，
     * 计件记给该工人；观星台员工录（{@code actor = null}）⇒ 只完成工序、不计件。
     */
    @org.springframework.transaction.annotation.Transactional(rollbackFor = Exception.class)
    public Map<String, Object> create(Long tenantId, String orderItemId, String result, String reason,
                                      String inspectorId, String inspectorName, String inspectorKind,
                                      OffsetDateTime inspectedAt, WorkerIdentity actor) {
        String kind = inspectorKind == null ? INSPECTOR_EMPLOYEE : inspectorKind.trim();
        if (!INSPECTOR_KINDS.contains(kind)) {
            throw BusinessException.validationError(
                    "inspector_kind 仅支持 employee/worker（员工/工人），收到：" + inspectorKind);
        }
        if (!StringUtils.hasText(orderItemId)) {
            throw BusinessException.validationError("order_item_id 必填：质检的颗粒度是**一件成品帘**，缺它无法落记录");
        }
        String normalized = result == null ? null : result.trim();
        if (normalized == null || !RESULTS.contains(normalized)) {
            throw BusinessException.validationError(
                    "inspection_result 仅支持 pass/rework/scrap（合格/返工/报废），收到："
                            + (result == null ? "null" : result));
        }
        // 🔴 判定 ≠ 合格 ⇒ 原因必填（本单判据 4：缺原因必须**具名报错**，不许静默存）
        String trimmedReason = reason == null ? null : reason.trim();
        if (!"pass".equals(normalized) && !StringUtils.hasText(trimmedReason)) {
            throw BusinessException.validationError(
                    String.format(REASON_REQUIRED, label(normalized)),
                    List.of(BusinessException.detail("reason", "判定为「" + label(normalized) + "」时必须说明原因")),
                    "请填写不合格原因（如：布面污渍 / 尺寸偏差 / 缝线开裂）后再提交");
        }

        OrderItem item = resolveOrderItem(tenantId, orderItemId);
        ProcessingOrder po = processingOrderMapper.selectActiveByOrderId(item.getOrderId(), tenantId);
        if (po == null) {
            throw BusinessException.validationError(
                    "该成品帘所属订单尚无活跃加工单，无法质检（质检对象必须是加工中的成品帘）");
        }

        QualityCheck row = QualityCheck.builder()
                .tenantId(tenantId)
                .processingOrderId(po.getId())
                .orderItemId(orderItemId)
                .positionName(item.getProductName())
                .inspectorId(inspectorId)
                .inspectorName(inspectorName)
                .inspectorKind(kind)
                .inspectionResult(normalized)
                .reason(trimmedReason)
                .inspectedAt(inspectedAt)
                .deleted(0)
                .build();
        qualityInspectionMapper.insert(row);
        // issue #7165：**合格**才代表这一件的质检工序做完（返工/报废还要再检）
        if ("pass".equals(normalized) && documentOperationLinkage != null) {
            documentOperationLinkage.completeQualityOperation(item.getOrderId(), orderItemId, actor, tenantId);
        }
        return view(row);
    }

    /**
     * 质检记录读面（按加工单 / 成品帘过滤，时间倒序）。
     *
     * <p>同一件成品帘允许多条（返工后重检）⇒ 读面把**逐条**给出（含 {@code inspected_at}），
     * **不**替客户端挑「当前判定」：那是展示口径，前端按时间序取第一条即可，
     * 服务端不制造第二份聚合。</p>
     */
    public List<Map<String, Object>> list(Long tenantId, String processingOrderId, String orderItemId) {
        LambdaQueryWrapper<QualityCheck> q = new LambdaQueryWrapper<QualityCheck>()
                .eq(QualityCheck::getTenantId, tenantId)
                .eq(QualityCheck::getDeleted, 0)
                .orderByDesc(QualityCheck::getInspectedAt)
                .orderByDesc(QualityCheck::getCreatedAt);
        if (StringUtils.hasText(processingOrderId)) {
            q.eq(QualityCheck::getProcessingOrderId, processingOrderId);
        }
        if (StringUtils.hasText(orderItemId)) {
            q.eq(QualityCheck::getOrderItemId, orderItemId);
        }
        List<Map<String, Object>> out = new ArrayList<>();
        for (QualityCheck row : qualityInspectionMapper.selectList(q)) {
            out.add(view(row));
        }
        return out;
    }

    /**
     * **待检清单**（商家「质检记录」页的第一屏，issue #7140）。
     *
     * <p>为什么必须有这个读面：{@link #list} 只能读出**已录**的记录。「哪些成品帘还没检」
     * 它在结构上答不出（没有行 = 没有事实）⇒ 质检员在观星台上没有工作清单
     * —— 这正是 issue #7140 的现场形态（后端有端点、观星台一个入口都没有）。</p>
     *
     * <p>口径：一条 = **一件成品帘**（加工单快照 {@code items[].itemId} = {@code order_items.id}，
     * 与 {@link #create} 的颗粒度**同一份**）；只收活跃加工单（已取消的不质检）；
     * {@code state} = 该成品帘**最新一条**记录的判定（无记录 = {@code pending}）。
     * 「最新」排序与 {@link #list} **同一份**（{@code inspected_at} 倒序、同刻再按 {@code created_at} 倒序）。</p>
     *
     * <p>⚠️ <b>不重算任何数量口径</b>：本方法只做「把加工单快照展开成成品帘行 + 取最新判定」，
     * 不碰报工、不算合格率（{@code counts} 只是逐条状态的计数，不是比率）。</p>
     *
     * @param keyword 加工单号关键词（空 = 不限）
     * @param status  {@code all} / {@code pending}（未检）/ {@code pass} / {@code rework} / {@code scrap}
     */
    public Map<String, Object> targets(Long tenantId, String keyword, String status, Integer pageArg, Integer sizeArg) {
        int size = sizeArg == null || sizeArg <= 0 ? TARGETS_DEFAULT_SIZE : Math.min(sizeArg, TARGETS_MAX_SIZE);
        int page = pageArg == null || pageArg <= 0 ? 1 : pageArg;
        String kw = keyword == null ? "" : keyword.trim();
        String filter = StringUtils.hasText(status) ? status.trim() : "all";
        if (!"all".equals(filter) && !"pending".equals(filter) && !RESULTS.contains(filter)) {
            throw BusinessException.validationError(
                    "status 仅支持 pending/pass/rework/scrap/all（未检 / 合格 / 返工 / 报废 / 全部），收到：" + status);
        }

        List<ProcessingOrder> orders = activeOrders(tenantId, kw);
        Map<String, String> orderNoByOrderId = loadOrderNos(orders);

        Map<String, Map<String, Object>> latestByItem = latestInspectionByItem(tenantId, orders);

        List<Map<String, Object>> rows = new ArrayList<>();
        Map<String, Integer> counts = new LinkedHashMap<>();
        counts.put("pending", 0);
        counts.put("pass", 0);
        counts.put("rework", 0);
        counts.put("scrap", 0);
        for (ProcessingOrder po : orders) {
            for (Map<String, Object> item : snapshotItems(po)) {
                String orderItemId = str(item.get("itemId"));
                // 存量行没有订单行 id ⇒ 指不出「哪一件成品帘」⇒ 不可质检（不猜、不编）
                if (!StringUtils.hasText(orderItemId)) {
                    continue;
                }
                Map<String, Object> latest = latestByItem.get(orderItemId);
                String state = latest == null ? "pending" : String.valueOf(latest.get("result"));
                if (counts.containsKey(state)) {
                    counts.put(state, counts.get(state) + 1);
                }
                if (!"all".equals(filter) && !filter.equals(state)) {
                    continue;
                }
                Map<String, Object> row = new LinkedHashMap<>();
                row.put("order_item_id", orderItemId);
                row.put("processing_order_id", po.getId());
                row.put("processing_order_no", po.getProcessingOrderNo());
                // 订单号（issue #7160）：同屏给出「这张加工单是哪个订单的」；取不到 ⇒ null，不编值。
                row.put("order_no", orderNoByOrderId.get(po.getOrderId()));
                row.put("processing_status", po.getStatus());
                row.put("product_name", str(item.get("productName")));
                row.put("color_name", str(item.get("colorName")));
                row.put("sku", str(item.get("sku")));
                row.put("quantity", item.get("quantity"));
                row.put("unit", str(item.get("unit")));
                row.put("state", state);
                row.put("latest", latest);
                rows.add(row);
            }
        }

        int total = rows.size();
        int from = Math.min((page - 1) * size, total);
        int to = Math.min(from + size, total);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("items", new ArrayList<>(rows.subList(from, to)));
        out.put("total", total);
        out.put("page", page);
        out.put("size", size);
        out.put("counts", counts);
        return out;
    }

    // ============================================================ 指标（issue #7192，P0+P1）

    /** 趋势分桶粒度（只认这三种；未知值 ⇒ 422，**不**静默回落 day）。 */
    public static final Set<String> STATS_BUCKETS = Set.of("day", "week", "month");

    /** 分组 Top-N（服务端封顶：页面是「谁在拖后腿」，不是全量排行）。 */
    private static final int STATS_TOP_N = 5;

    /** 趋势桶数上限（超出只保留**最近** N 个桶）。 */
    private static final int STATS_MAX_BUCKETS = 60;

    /** 样本量偏少的阈值（回传给前端做提示；**服务端照样算率**，只是让读数带上样本量）。 */
    public static final int STATS_MIN_SAMPLE = 20;

    private static final DateTimeFormatter MONTH_FMT = DateTimeFormatter.ofPattern("yyyy-MM");

    /**
     * 质检指标（**P0 + P1**，issue #7192）—— 用户 2026-10-18 提问「质检记录缺乏一个合格率的指标？」
     * 并按建议取 P0（率）+ P1（时间窗 / 趋势 / 分组 / 待检积压）。
     *
     * <h3>口径（🔴 全部按「件」聚合，不按记录条数）</h3>
     * <ul>
     *   <li><b>颗粒度 = 一件成品帘</b>（{@code order_item_id} 级，与 {@link #create} 同一把尺子）：
     *       同一件允许多条记录（返工后复检）⇒ 全部先按件折叠成「首检 / 最新」两条事实；</li>
     *   <li><b>首检合格率（FPY）= 首次判定为合格的件数 ÷ 已检件数</b>（复检合格<b>不洗白</b>）—— 主指标；</li>
     *   <li><b>当前合格率 / 返工率 / 报废率</b>：按<b>最新</b>判定计；三者互斥且和为 1（与清单四态同源）；</li>
     *   <li><b>未检件不进分母</b>（未检 ≠ 不合格），0 样本的率一律 {@code null}（前端显示「—」，
     *       <b>不是</b> 0%）；</li>
     *   <li><b>时间窗作用于「首检时刻」</b>（cohort = 窗口内**首次**被检的件）—— 否则窗口会一半落在
     *       返工复检上，率不可比。</li>
     * </ul>
     *
     * <h3>为什么在服务端算（不在前端拼）</h3>
     * <p>与 {@link #targets} 同一条纪律：颗粒度/排序/去重的口径只允许一份（前端只格式化，
     * 不重算率）。分页与清单读面<b>互不影响</b>：本方法只读、不写、不改任何判定口径。</p>
     *
     * @param fromArg 起始时刻（含；缺省 = 本月 1 日 00:00）；支持 {@code 2026-10-01} 或带偏移的 ISO 时刻
     * @param toArg   结束时刻（<b>不含</b>；缺省 = 不限）
     * @param bucketArg {@code day} / {@code week} / {@code month}
     */
    public Map<String, Object> stats(Long tenantId, String fromArg, String toArg, String bucketArg) {
        String bucket = StringUtils.hasText(bucketArg) ? bucketArg.trim() : "day";
        if (!STATS_BUCKETS.contains(bucket)) {
            throw BusinessException.validationError(
                    "bucket 仅支持 day/week/month（日/周/月），收到：" + bucketArg);
        }
        OffsetDateTime from = parseMoment(fromArg, "from");
        OffsetDateTime to = parseMoment(toArg, "to");
        String window = null;
        if (from == null && to == null) {
            from = LocalDate.now().withDayOfMonth(1)
                    .atStartOfDay(ZoneId.systemDefault()).toOffsetDateTime();
            window = "month";
        }
        if (from != null && to != null && !to.isAfter(from)) {
            throw BusinessException.validationError("时间窗不合法：结束时刻必须晚于起始时刻（to 为不含边界）");
        }

        // ① 全部记录（按 inspected_at 升序 + created_at 升序）：首检口径需要「这一件的第一条」，
        //    所以**不能**先按窗口裁行 —— 窗口外首检的件整件不进 cohort（见类注释口径 4）。
        List<QualityCheck> rows = qualityInspectionMapper.selectList(new LambdaQueryWrapper<QualityCheck>()
                .eq(QualityCheck::getTenantId, tenantId)
                .eq(QualityCheck::getDeleted, 0)
                .orderByAsc(QualityCheck::getInspectedAt)
                .orderByAsc(QualityCheck::getCreatedAt));

        Map<String, QualityCheck> firstByItem = new LinkedHashMap<>();
        Map<String, QualityCheck> lastByItem = new LinkedHashMap<>();
        for (QualityCheck row : rows) {
            String itemId = row.getOrderItemId();
            if (!StringUtils.hasText(itemId)) {
                continue;
            }
            firstByItem.putIfAbsent(itemId, row);
            lastByItem.put(itemId, row);
        }

        // ② cohort + 计数（全部按件）
        List<Map.Entry<String, QualityCheck>> cohort = new ArrayList<>();
        int inspected = 0;
        int firstPass = 0;
        int currentPass = 0;
        int rework = 0;
        int scrap = 0;
        for (Map.Entry<String, QualityCheck> entry : firstByItem.entrySet()) {
            if (!within(entry.getValue().getInspectedAt(), from, to)) {
                continue;
            }
            cohort.add(entry);
            inspected++;
            if ("pass".equals(entry.getValue().getInspectionResult())) {
                firstPass++;
            }
            QualityCheck last = lastByItem.get(entry.getKey());
            String latest = last == null ? null : last.getInspectionResult();
            if ("pass".equals(latest)) {
                currentPass++;
            } else if ("rework".equals(latest)) {
                rework++;
            } else if ("scrap".equals(latest)) {
                scrap++;
            }
        }

        // ③ 趋势（窗口内零填充的桶；超出上限只保留最近 N 个）
        Map<LocalDate, int[]> buckets = trendBuckets(from, to, bucket);
        for (Map.Entry<String, QualityCheck> entry : cohort) {
            LocalDate at = toLocalDate(entry.getValue().getInspectedAt());
            if (at == null) {
                continue;
            }
            int[] slot = buckets.computeIfAbsent(bucketStart(at, bucket), k -> new int[2]);
            slot[0]++;
            if ("pass".equals(entry.getValue().getInspectionResult())) {
                slot[1]++;
            }
        }
        List<Map<String, Object>> trend = new ArrayList<>();
        for (Map.Entry<LocalDate, int[]> entry : buckets.entrySet()) {
            Map<String, Object> point = new LinkedHashMap<>();
            point.put("bucket", bucketLabel(entry.getKey(), bucket));
            point.put("inspected", entry.getValue()[0]);
            point.put("first_pass", entry.getValue()[1]);
            point.put("first_pass_rate", rate(entry.getValue()[1], entry.getValue()[0]));
            trend.add(point);
        }

        // ④ 分组 Top-N（加工单 / 商品 / 检验人）—— 标签批量取回，不逐行单查
        Map<String, String> poNoById = new HashMap<>();
        Map<String, String> productById = new HashMap<>();
        loadGroupLabels(cohort, poNoById, productById);
        Map<String, int[]> byOrder = new LinkedHashMap<>();
        Map<String, int[]> byProduct = new LinkedHashMap<>();
        Map<String, int[]> byInspector = new LinkedHashMap<>();
        for (Map.Entry<String, QualityCheck> entry : cohort) {
            QualityCheck first = entry.getValue();
            boolean pass = "pass".equals(first.getInspectionResult());
            accumulate(byOrder, poNoById.getOrDefault(str(first.getProcessingOrderId()), "（未标注）"), pass);
            accumulate(byProduct, productById.getOrDefault(entry.getKey(), "（未标注）"), pass);
            String inspector = StringUtils.hasText(first.getInspectorName())
                    ? first.getInspectorName() : "（未标注）";
            accumulate(byInspector, inspector, pass);
        }

        Map<String, Object> counts = new LinkedHashMap<>();
        counts.put("inspected", inspected);
        counts.put("first_pass", firstPass);
        counts.put("current_pass", currentPass);
        counts.put("rework", rework);
        counts.put("scrap", scrap);

        Map<String, Object> rates = new LinkedHashMap<>();
        rates.put("first_pass_rate", rate(firstPass, inspected));
        rates.put("current_pass_rate", rate(currentPass, inspected));
        rates.put("rework_rate", rate(rework, inspected));
        rates.put("scrap_rate", rate(scrap, inspected));

        Map<String, Object> windowView = new LinkedHashMap<>();
        windowView.put("from", from);
        windowView.put("to", to);
        windowView.put("name", window);

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("window", windowView);
        out.put("bucket", bucket);
        out.put("min_sample", STATS_MIN_SAMPLE);
        out.put("counts", counts);
        out.put("rates", rates);
        out.put("trend", trend);
        out.put("by_processing_order", topGroups(byOrder));
        out.put("by_product", topGroups(byProduct));
        out.put("by_inspector", topGroups(byInspector));
        out.put("backlog", backlog(tenantId));
        return out;
    }

    /**
     * 待检积压（P1）：未检件数 + 最久待检时长。
     *
     * <p>🔴 <b>近似口径，如实标注</b>：系统里没有「进入待检」的时间戳（待检是**派生读面** ——
     * 没有记录就是未检，见 {@link #targets}），所以「等了多久」只能从**加工单生成时刻**起算
     * —— 它给出的是<b>上界</b>（真实待检时长 ≤ 该值），页面必须写「近似」并说明起算点，
     * 不做假精确。真正的口径要新增落库字段，属 P2（另开单）。</p>
     */
    private Map<String, Object> backlog(Long tenantId) {
        List<ProcessingOrder> orders = activeOrders(tenantId, null);
        Map<String, Map<String, Object>> latestByItem = latestInspectionByItem(tenantId, orders);
        int pending = 0;
        OffsetDateTime oldest = null;
        for (ProcessingOrder po : orders) {
            for (Map<String, Object> item : snapshotItems(po)) {
                String itemId = str(item.get("itemId"));
                // 与清单同一份判据：指不出「哪一件」的行不进来（不猜、不编）
                if (!StringUtils.hasText(itemId) || latestByItem.containsKey(itemId)) {
                    continue;
                }
                pending++;
                OffsetDateTime since = po.getCreatedAt() != null ? po.getCreatedAt() : po.getGeneratedAt();
                if (since != null && (oldest == null || since.isBefore(oldest))) {
                    oldest = since;
                }
            }
        }
        Double hours = null;
        if (oldest != null) {
            long minutes = Math.max(0, Duration.between(oldest, OffsetDateTime.now()).toMinutes());
            hours = Math.round(minutes / 6.0) / 10.0;
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("pending", pending);
        out.put("oldest_pending_hours", hours);
        out.put("approximate", true);
        out.put("approximate_from", "processing_order.created_at");
        return out;
    }

    /** 一个分组桶：{已检件数, 首检合格件数}（按件计，**不**按记录条数）。 */
    private static void accumulate(Map<String, int[]> acc, String key, boolean pass) {
        int[] slot = acc.computeIfAbsent(key, k -> new int[2]);
        slot[0]++;
        if (pass) {
            slot[1]++;
        }
    }

    /** Top-N（按已检件数降序；率 = 该组首检合格件数 ÷ 该组已检件数）。 */
    private static List<Map<String, Object>> topGroups(Map<String, int[]> acc) {
        List<Map.Entry<String, int[]>> entries = new ArrayList<>(acc.entrySet());
        entries.sort((a, b) -> Integer.compare(b.getValue()[0], a.getValue()[0]));
        List<Map<String, Object>> out = new ArrayList<>();
        for (int i = 0; i < entries.size() && i < STATS_TOP_N; i++) {
            Map.Entry<String, int[]> entry = entries.get(i);
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("name", entry.getKey());
            row.put("inspected", entry.getValue()[0]);
            row.put("first_pass", entry.getValue()[1]);
            row.put("first_pass_rate", rate(entry.getValue()[1], entry.getValue()[0]));
            out.add(row);
        }
        return out;
    }

    /** 分组标签（加工单号 / 商品名 · 颜色）—— 一次 {@code IN}，与清单读面同源。 */
    private void loadGroupLabels(List<Map.Entry<String, QualityCheck>> cohort,
                                 Map<String, String> poNoById, Map<String, String> productById) {
        Set<String> poIds = new LinkedHashSet<>();
        Set<String> itemIds = new LinkedHashSet<>();
        for (Map.Entry<String, QualityCheck> entry : cohort) {
            String poId = str(entry.getValue().getProcessingOrderId());
            if (StringUtils.hasText(poId)) {
                poIds.add(poId);
            }
            itemIds.add(entry.getKey());
        }
        // 商品名 · 颜色取**加工单快照**（与待检清单同一份取数：快照才是那一件的固化真相，
        // 订单行事后可改；快照缺键 ⇒ 下面按订单行品名兜底，再缺 ⇒ 调用方写「（未标注）」）。
        if (!poIds.isEmpty()) {
            List<ProcessingOrder> pos = processingOrderMapper.selectBatchIds(poIds);
            if (pos != null) {
                for (ProcessingOrder po : pos) {
                    poNoById.put(po.getId(), po.getProcessingOrderNo());
                    for (Map<String, Object> item : snapshotItems(po)) {
                        String itemId = str(item.get("itemId"));
                        if (!StringUtils.hasText(itemId)) {
                            continue;
                        }
                        String label = productLabel(str(item.get("productName")), str(item.get("colorName")));
                        if (StringUtils.hasText(label)) {
                            productById.putIfAbsent(itemId, label);
                        }
                    }
                }
            }
        }
        if (!itemIds.isEmpty()) {
            List<OrderItem> items = orderItemMapper.selectBatchIds(itemIds);
            if (items != null) {
                for (OrderItem item : items) {
                    String label = productLabel(item.getProductName(), null);
                    if (StringUtils.hasText(label)) {
                        productById.putIfAbsent(item.getId(), label);
                    }
                }
            }
        }
    }

    /** 商品标签 = 品名 · 颜色（缺一项就只显示另一项；两项都缺 ⇒ {@code null}，由调用方兜底）。 */
    private static String productLabel(String productName, String colorName) {
        boolean hasProduct = StringUtils.hasText(productName);
        boolean hasColor = StringUtils.hasText(colorName);
        if (hasProduct && hasColor) {
            return productName.trim() + " · " + colorName.trim();
        }
        if (hasProduct) {
            return productName.trim();
        }
        return hasColor ? colorName.trim() : null;
    }

    /** 活跃加工单（清单读面与积压指标**同一份**取数口径）。 */
    private List<ProcessingOrder> activeOrders(Long tenantId, String keyword) {
        LambdaQueryWrapper<ProcessingOrder> q = new LambdaQueryWrapper<ProcessingOrder>()
                .eq(ProcessingOrder::getTenantId, tenantId)
                .eq(ProcessingOrder::getDeleted, 0)
                .in(ProcessingOrder::getStatus, TARGET_PROCESSING_STATUSES)
                .orderByDesc(ProcessingOrder::getCreatedAt);
        if (StringUtils.hasText(keyword)) {
            q.like(ProcessingOrder::getProcessingOrderNo, keyword);
        }
        return processingOrderMapper.selectList(q);
    }

    /** 解析时间参数（缺省 ⇒ {@code null} = 该侧不限）；非法 ⇒ 422 具名报错（不静默忽略）。 */
    private static OffsetDateTime parseMoment(String raw, String field) {
        if (!StringUtils.hasText(raw)) {
            return null;
        }
        String value = raw.trim();
        try {
            if (value.length() == 10) {
                return LocalDate.parse(value).atStartOfDay(ZoneId.systemDefault()).toOffsetDateTime();
            }
            return OffsetDateTime.parse(value);
        } catch (DateTimeParseException e) {
            throw BusinessException.validationError(
                    field + " 时间格式不合法（支持 2026-10-01 或 2026-10-01T00:00:00+08:00），收到：" + raw);
        }
    }

    /** 左闭右开窗口：{@code from <= moment < to}（缺省侧不限）。 */
    private static boolean within(OffsetDateTime moment, OffsetDateTime from, OffsetDateTime to) {
        if (moment == null) {
            return false;
        }
        return (from == null || !moment.isBefore(from)) && (to == null || moment.isBefore(to));
    }

    private static LocalDate toLocalDate(OffsetDateTime moment) {
        return moment == null ? null : moment.atZoneSameInstant(ZoneId.systemDefault()).toLocalDate();
    }

    private static LocalDate bucketStart(LocalDate date, String bucket) {
        return switch (bucket) {
            case "week" -> date.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY));
            case "month" -> date.withDayOfMonth(1);
            default -> date;
        };
    }

    private static LocalDate previousBucket(LocalDate date, String bucket) {
        return switch (bucket) {
            case "week" -> date.minusWeeks(1);
            case "month" -> date.minusMonths(1);
            default -> date.minusDays(1);
        };
    }

    private static String bucketLabel(LocalDate start, String bucket) {
        return switch (bucket) {
            case "week" -> String.format("%d-W%02d",
                    start.get(WeekFields.ISO.weekBasedYear()),
                    start.get(WeekFields.ISO.weekOfWeekBasedYear()));
            case "month" -> start.format(MONTH_FMT);
            default -> start.toString();
        };
    }

    /** 桶序列（含零填充）：从窗口结尾往回最多 {@link #STATS_MAX_BUCKETS} 个桶，按时间升序。 */
    private static Map<LocalDate, int[]> trendBuckets(OffsetDateTime from, OffsetDateTime to, String bucket) {
        LocalDate end = toLocalDate(to != null ? to : OffsetDateTime.now());
        LocalDate start = toLocalDate(from);
        if (end == null) {
            end = LocalDate.now();
        }
        if (start == null) {
            start = end.minusMonths(1);
        }
        LocalDate endBucket = bucketStart(end, bucket);
        LocalDate startBucket = bucketStart(start, bucket);
        List<LocalDate> keys = new ArrayList<>();
        LocalDate cursor = endBucket;
        while (!cursor.isBefore(startBucket) && keys.size() < STATS_MAX_BUCKETS) {
            keys.add(cursor);
            cursor = previousBucket(cursor, bucket);
        }
        Collections.reverse(keys);
        Map<LocalDate, int[]> map = new TreeMap<>();
        for (LocalDate key : keys) {
            map.put(key, new int[2]);
        }
        return map;
    }

    /** 比率（0~1，四位小数）；**分母为 0 ⇒ {@code null}**（前端显示「—」，不是 0%）。 */
    private static Double rate(int numerator, int denominator) {
        if (denominator <= 0) {
            return null;
        }
        return Math.round(numerator * 10000.0 / denominator) / 10000.0;
    }

    /**
     * 批量取回这批加工单所属的**销售订单号**（issue #7160；一次 {@code IN}，不逐行单查）。
     *
     * <p>租户与软删口径由 {@code OrderMapper} 的标准方法兜底（{@code TenantLineInnerInterceptor} +
     * {@code Order} 的 {@code @TableLogic}），与单查同口径、不因批量而放宽。存量加工单缺
     * {@code order_id} / 订单已不可见 ⇒ 不进表 ⇒ 行上 {@code order_no=null}（界面渲染 {@code —}，不编值）。</p>
     */
    private Map<String, String> loadOrderNos(List<ProcessingOrder> processingOrders) {
        Set<String> orderIds = new LinkedHashSet<>();
        for (ProcessingOrder po : processingOrders) {
            if (StringUtils.hasText(po.getOrderId())) {
                orderIds.add(po.getOrderId());
            }
        }
        Map<String, String> noById = new HashMap<>();
        if (orderIds.isEmpty()) {
            return noById;
        }
        List<Order> rows = orderMapper.selectBatchIds(orderIds);
        if (rows != null) {
            for (Order order : rows) {
                noById.put(order.getId(), order.getOrderNo());
            }
        }
        return noById;
    }

    /** 一次取回这批加工单的全部记录，按成品帘取**最新一条**（排序与 {@link #list} 同源）。 */
    private Map<String, Map<String, Object>> latestInspectionByItem(Long tenantId, List<ProcessingOrder> orders) {
        Map<String, Map<String, Object>> latestByItem = new LinkedHashMap<>();
        if (orders.isEmpty()) {
            return latestByItem;
        }
        List<String> processingOrderIds = new ArrayList<>();
        for (ProcessingOrder po : orders) {
            processingOrderIds.add(po.getId());
        }
        LambdaQueryWrapper<QualityCheck> q = new LambdaQueryWrapper<QualityCheck>()
                .eq(QualityCheck::getTenantId, tenantId)
                .eq(QualityCheck::getDeleted, 0)
                .in(QualityCheck::getProcessingOrderId, processingOrderIds)
                .orderByDesc(QualityCheck::getInspectedAt)
                .orderByDesc(QualityCheck::getCreatedAt);
        for (QualityCheck row : qualityInspectionMapper.selectList(q)) {
            latestByItem.putIfAbsent(row.getOrderItemId(), view(row));
        }
        return latestByItem;
    }

    /** 加工单快照里的成品帘行（兼容 JSON 字符串形态；形态不干净 ⇒ 该单不出待检行，**不编值**）。 */
    private List<Map<String, Object>> snapshotItems(ProcessingOrder po) {
        Object snapshot = po.getItemsSnapshot();
        if (snapshot instanceof String s) {
            if (!StringUtils.hasText(s)) {
                return List.of();
            }
            try {
                snapshot = objectMapper.readValue(s, Object.class);
            } catch (Exception e) {
                return List.of();
            }
        }
        if (snapshot == null) {
            return List.of();
        }
        try {
            return objectMapper.convertValue(snapshot, new TypeReference<List<Map<String, Object>>>() {});
        } catch (Exception e) {
            return List.of();
        }
    }

    /** 快照字段取值（缺键 / null ⇒ null，**不折算成空串**）。 */
    private String str(Object value) {
        return value == null ? null : String.valueOf(value);
    }

    /**
     * 定位一件成品帘（三重校验：存在 + 同租户 + 未软删）。
     *
     * <p>跨租户与不存在<b>给出同一个 404</b>（逐字同一形态）—— 403 等于承认「这个 id 存在，
     * 只是不给你看」（与发货读面同款纪律）。</p>
     */
    private OrderItem resolveOrderItem(Long tenantId, String orderItemId) {
        OrderItem item = orderItemMapper.selectById(orderItemId);
        if (item == null || !tenantId.equals(item.getTenantId())
                || (item.getDeleted() != null && item.getDeleted() != 0)) {
            throw BusinessException.notFound("成品帘");
        }
        return item;
    }

    /** 逐字段可读的记录视图（**缺值不渲染假数据**：null 原样为 null，不折 0 / 不写 undefined）。 */
    /**
     * 某件成品帘的**最新一条**质检判定（无记录 ⇒ {@code null}；「未检」不折成「合格」）。
     *
     * <p>工人端扫描后的质检区块用它显示「这件检过没有、上次判了什么」—— 与商家端读面
     * （{@link #list} 时间倒序取第一条）**同一份排序口径**（{@link com.migao.admin.mapper.QualityCheckMapper#selectLatestByOrderItemIds}）。</p>
     */
    public Map<String, Object> latest(Long tenantId, String orderItemId) {
        if (!StringUtils.hasText(orderItemId)) {
            throw BusinessException.validationError("order_item_id 必填：质检的颗粒度是一件成品帘");
        }
        List<QualityCheck> rows = qualityInspectionMapper.selectLatestByOrderItemIds(List.of(orderItemId.trim()));
        return rows == null || rows.isEmpty() ? null : view(rows.get(0));
    }

    private Map<String, Object> view(QualityCheck row) {
        Map<String, Object> v = new LinkedHashMap<>();
        v.put("id", row.getId());
        v.put("order_item_id", row.getOrderItemId());
        v.put("processing_order_id", row.getProcessingOrderId());
        v.put("position_name", row.getPositionName());
        v.put("result", row.getInspectionResult());
        v.put("result_label", label(row.getInspectionResult()));
        v.put("reason", row.getReason());
        v.put("inspector_id", row.getInspectorId());
        v.put("inspector_name", row.getInspectorName());
        // issue #7162：一条只加不改 —— 读面能区分「观星台员工录的」与「工人端录的」
        v.put("inspector_kind", row.getInspectorKind() == null ? INSPECTOR_EMPLOYEE : row.getInspectorKind());
        v.put("inspected_at", row.getInspectedAt());
        return v;
    }

    /** 三态的中文标签（展示用；未知值如实回 null，不猜）。 */
    private String label(String result) {
        if (result == null) {
            return null;
        }
        return switch (result) {
            case "pass" -> "合格";
            case "rework" -> "返工";
            case "scrap" -> "报废";
            default -> null;
        };
    }
}
