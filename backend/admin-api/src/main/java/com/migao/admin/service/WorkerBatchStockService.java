package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.dto.BatchStocktakeRequest;
import com.migao.admin.dto.BatchStockViews;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.dto.WorkerBatchCorrectionRequest;
import com.migao.admin.dto.WorkerBatchStockViews;
import com.migao.admin.entity.Product;
import com.migao.admin.entity.User;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.UserMapper;
import com.migao.admin.worker.WorkerIdentity;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 工人端**批次库存修正**（issue #8104；用户 2026-10-29 逐字
 * 「手机端还要增加一个库存修正的功能……允许工人对某个批次的布匹进行修正」）。
 *
 * <h2>它解决什么</h2>
 * <p>车间现场：这一卷布实际只剩 42 米，系统显示 45.5 米（量错 / 破损 / 报工时选错批次）。
 * 改前工人只能回电脑端找管理员盘点（{@code POST /api/admin/batch-stock/stocktake}，需要
 * {@code product:create}）⇒ 账实差异在现场被**跳过**，越积越大。本服务给工人一条
 * **按批次**的修正通道。</p>
 *
 * <h2>为什么不是第二套库存写逻辑</h2>
 * <p>本类**不写任何一张表**：它把「实盘米数」改写成一次**按批次盘点**，交给
 * {@link BatchStocktakeService#stocktake} —— 那个类是全仓唯一的批次盘点写面
 * （批次分录 {@code reason=stocktake} + SKU 库存同一事务对齐；类级守卫
 * {@code tests/unit_ci_workflows/test_batch_stocktake_write_point.py} 钉住「批次台账的写入点唯一」）。
 * 于是「工人修正」与「商家盘点」在账上是**同一种事实**（实盘为准），差异只在
 * {@code note} 里写明是谁、为什么 —— 不需要新迁移、不需要新的 reason 族。</p>
 *
 * <h2>五条口径（每条都有会红的判据）</h2>
 * <ol>
 *   <li><b>批次必须属于本租户</b>：按 {@code tenantId + batchId} 查，查不到 ⇒ 404
 *       （不是 403 —— 避免存在性泄露）；</li>
 *   <li><b>实盘米数走库存链路的同一条准入</b>（{@link StockQuantity#requireOneDecimal}）：
 *       超精度 422、负数 400（文案说清「最小是 0」）；<b>服务端绝不静默取整</b>；</li>
 *   <li><b>幂等</b>：{@code clientRequestId} 拼成运行标识 {@code wc-<id>}，复用
 *       {@code uk_batch_consumption_stocktake} 与 {@link BatchStocktakeService} 的重放判定
 *       ⇒ 网络重试 / 连点只记一笔，第二遍回 {@code replayed}；</li>
 *   <li><b>实盘 == 系统余量 ⇒ 零写入</b>（上游 {@code unchanged}）：不动 SKU 库存、不落分录；</li>
 *   <li><b>台账答得出「谁、为什么」</b>：批次分录的 {@code operator} = 工人姓名，
 *       {@code note} 以「工人库存修正：姓名（工号 X），原因 …」开头（上游统一截断到列宽内）。</li>
 * </ol>
 *
 * <h2>边界（照实登记，§19.1）</h2>
 * <ul>
 *   <li><b>不做盘点单</b>：无单号 / 无审批 / 无打印 —— 沿用 #5865 的「A 最小录入式」；</li>
 *   <li><b>一次提交只能改一个批次</b>：工人现场就是「这一卷」，批量盘点仍是商家面的事；</li>
 *   <li><b>不新增 reason 族</b>：工人修正 = 实盘为准 ⇒ 沿用 {@code reason=stocktake}
 *       （要在台账上把「工人修正 / 商家盘点」分列 ⇒ 另开迁移单，见 issue #8104 的边界段）；</li>
 *   <li>「盘亏把 SKU 库存扣成负」仍由上游 422（{@code INSUFFICIENT_STOCK}）拦下 —— 本类不放宽。</li>
 * </ul>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class WorkerBatchStockService {

    /** 实盘米数为负（与商家盘点的 {@code STOCKTAKE_ACTUAL_NEGATIVE} 同口径，但文案面向工人）。 */
    public static final String ERR_ACTUAL_NEGATIVE = "WORKER_STOCK_CORRECTION_ACTUAL_NEGATIVE";

    /** 批次不存在 / 不属于本租户（404：不泄露别的租户有没有这个 id）。 */
    public static final String ERR_BATCH_NOT_FOUND = "WORKER_STOCK_CORRECTION_BATCH_NOT_FOUND";

    /** 幂等键缺失 / 形态非法（422：它是「重试不双记」的唯一凭据，缺它不许提交）。 */
    public static final String ERR_REQUEST_ID = "WORKER_STOCK_CORRECTION_REQUEST_ID";

    /**
     * 修正原因**闭词表**（全仓唯一来源；端侧选项由读面下发，不另写一份）。
     *
     * <p>取值不参与库存算法 —— 只进台账 {@code note}。验收集合的意义是「工人必须说出为什么」，
     * 而不是「不同原因走不同口径」（那会把一次盘点拆成几个族，见类注释的边界）。</p>
     */
    public static final List<WorkerBatchStockViews.Reason> REASONS = List.of(
            new WorkerBatchStockViews.Reason("miscount", "数量记错了"),
            new WorkerBatchStockViews.Reason("damaged", "破损 / 报废"),
            new WorkerBatchStockViews.Reason("wrong_batch", "报工选错批次"),
            new WorkerBatchStockViews.Reason("other", "其他"));

    /** 幂等键 → 盘点运行标识的前缀（与裁剪报工的 {@code wc-} 形态同族，但**不复用**它的键空间）。 */
    public static final String RUN_PREFIX = "wc-";

    /** 备注上限（只进 note；列宽 255，留足前缀与上游文案的余量）。 */
    public static final int MAX_NOTE_LENGTH = 60;

    /** 幂等键上限（{@code wc-} + 48 = 51 ≤ 列宽 64）。 */
    public static final int MAX_REQUEST_ID_LENGTH = 48;

    private static final Set<String> REASON_CODES = REASONS.stream()
            .map(WorkerBatchStockViews.Reason::code)
            .collect(java.util.stream.Collectors.toCollection(LinkedHashSet::new));

    private final StockBatchConsumptionService batchStockService;
    private final BatchStocktakeService batchStocktakeService;
    private final ProductMapper productMapper;
    private final UserMapper userMapper;

    /**
     * 按批次搜（批次号 / 旧系统批次号 / 货号 / 缸号 / 入库单号任一段命中）。
     *
     * <p>排序 / 分页 / 余量口径全部复用 {@link StockBatchConsumptionService#remainingPage} ——
     * 本方法只补两件工人必须看见的东西：**品名**（认布）与**原因清单**（屏上选项的来源）。</p>
     *
     * @param keyword 可为空（空 = 最近入库的批次，工人可直接浏览）
     */
    public WorkerBatchStockViews.BatchPage search(Long tenantId, String keyword, long page, long size) {
        PageResponse<BatchStockViews.BatchRemaining> result =
                batchStockService.remainingPage(tenantId, null, null, keyword, page, size);
        Map<String, String> names = productNames(tenantId, result.getItems());
        List<WorkerBatchStockViews.BatchRow> rows = new ArrayList<>();
        for (BatchStockViews.BatchRemaining row : result.getItems()) {
            rows.add(new WorkerBatchStockViews.BatchRow(row.batchId(), row.batchNo(), row.productId(),
                    names.get(row.productId()), row.skuCode(), row.dyeLot(), row.inboundNo(),
                    row.receivedDate(), row.remainingMeters()));
        }
        return new WorkerBatchStockViews.BatchPage(rows, result.getTotal(), result.getPage(),
                result.getSize(), REASONS);
    }

    /**
     * 提交一次修正：把一个批次的余量改成工人实测的米数。
     *
     * <p>校验**全部先于写入**（fail-closed）：批次归属 / 米数精度 / 非负 / 原因 / 幂等键
     * 任一不合法 ⇒ 一个字节都不落（上游 {@code BatchStocktakeService} 的「校验先于写入」再兜一层）。</p>
     *
     * @param identity 由 {@code WorkerSessionService} 从工人 session 解出的身份（**不是**请求体里的字段）
     */
    public WorkerBatchStockViews.Correction correct(Long tenantId, WorkerIdentity identity,
                                                    WorkerBatchCorrectionRequest request) {
        if (identity == null) {
            throw BusinessException.authFailed("尚未登录工人身份，请先用工号 + PIN 登录");
        }
        if (request == null) {
            throw BusinessException.validationError("修正请求体不能为空");
        }
        if (request.getBatchId() == null) {
            throw BusinessException.validationError("缺少批次（batchId）：请先在搜索结果里选中要修正的批次");
        }
        if (request.getActualMeters() == null) {
            throw BusinessException.validationError("请填实盘米数（这一批现在实际还剩多少米）");
        }
        BigDecimal actual = StockQuantity.requireOneDecimal(request.getActualMeters(), "实盘米数");
        if (actual.signum() < 0) {
            throw new BusinessException(ERR_ACTUAL_NEGATIVE,
                    String.format("实盘米数不能为负：%s", actual.toPlainString()), 400,
                    "实盘米数是「这一批现在实际还剩多少米」⇒ 最小是 0；报损请选「破损 / 报废」原因");
        }
        String reason = requireReason(request.getReason());
        String runId = RUN_PREFIX + requireRequestId(request.getClientRequestId());
        String note = requireNote(request.getNote());

        BatchStockViews.BatchRemaining batch =
                batchStockService.remainingOfBatch(tenantId, request.getBatchId());
        if (batch == null) {
            throw new BusinessException(ERR_BATCH_NOT_FOUND,
                    String.format("批次 %s 不存在或不属于当前企业", request.getBatchId()), 404,
                    "请刷新搜索结果后重新选中该批次；若批次已被删除，请联系管理员核对入库单");
        }
        String workerNo = workerNo(identity);
        String operator = operatorOf(identity);
        String reasonLabel = REASONS.stream()
                .filter(r -> r.code().equals(reason))
                .map(WorkerBatchStockViews.Reason::label)
                .findFirst()
                .orElse(reason);
        String prefix = notePrefix(identity, workerNo, reasonLabel, note);

        BatchStocktakeRequest.Line requestLine = new BatchStocktakeRequest.Line();
        requestLine.setBatchId(batch.batchId());
        requestLine.setActualMeters(actual);
        BatchStockViews.StocktakeResult result = batchStocktakeService.stocktake(tenantId,
                batch.productId(), runId, List.of(requestLine),
                new StockBatchConsumptionService.StocktakeAudit(operator, prefix));
        BatchStockViews.StocktakeLineResult line = result.lines().isEmpty()
                ? null : result.lines().get(0);
        if (line == null) {
            // 上游契约是「一个批次一行」；走到这里说明账坏了 —— 不静默给假回执
            throw new BusinessException("WORKER_STOCK_CORRECTION_NO_LINE",
                    "修正回执缺少批次行 —— 本次未确认落账，请刷新后重试", 500,
                    "若重复出现，请把这条文案与批次号反馈给管理员核对批次台账");
        }
        log.info("工人库存修正: tenant={}, worker={}({}), batch={}, before={}, actual={}, delta={}, status={}",
                tenantId, identity.workerName(), workerNo, batch.batchNo(),
                line.beforeMeters(), line.actualMeters(), line.delta(), line.status());
        return new WorkerBatchStockViews.Correction(runId, line.batchId(), line.batchNo(),
                names(batch.productId()), line.skuCode(), line.status(), line.beforeMeters(),
                line.actualMeters(), line.delta(), line.afterMeters(), identity.workerName(), workerNo);
    }

    // ══════════════════════════════════════════════════════════════════════════════
    // 校验 / 文案（纯函数，便于被单测逐值钉住）
    // ══════════════════════════════════════════════════════════════════════════════

    private static String requireReason(String raw) {
        String reason = StringUtils.hasText(raw) ? raw.trim() : "";
        if (!REASON_CODES.contains(reason)) {
            throw BusinessException.validationError(String.format(
                    "请选择修正原因（可选：%s）—— 台账要答得出「这批为什么变了」",
                    String.join(" / ", REASONS.stream().map(WorkerBatchStockViews.Reason::code).toList())));
        }
        return reason;
    }

    /**
     * 幂等键：非空、≤48、只含 {@code A-Za-z0-9-}（端侧用 UUID；放宽到连字符即可覆盖）。
     *
     * <p>形态校验不是洁癖：它同时挡住「把任意长文本塞进运行标识」——
     * {@code stock_batch_consumptions.stocktake_run_id} 是 {@code VARCHAR(64)}，
     * 写库时才炸就是 500。</p>
     */
    private static String requireRequestId(String raw) {
        String id = StringUtils.hasText(raw) ? raw.trim() : "";
        if (id.isEmpty()) {
            throw new BusinessException(ERR_REQUEST_ID,
                    "缺少幂等键（clientRequestId）—— 它是「网络重试不重复记账」的唯一凭据", 422,
                    "请刷新页面后重新提交（页面会自动生成一个新的提交标识）");
        }
        if (id.length() > MAX_REQUEST_ID_LENGTH || !id.matches("[A-Za-z0-9-]+")) {
            throw new BusinessException(ERR_REQUEST_ID,
                    String.format("幂等键形态不合法：%s（最长 %d 位，只允许字母 / 数字 / 连字符）",
                            id, MAX_REQUEST_ID_LENGTH), 422,
                    "请刷新页面后重新提交（页面会自动生成一个新的提交标识）");
        }
        return id;
    }

    private static String requireNote(String raw) {
        String note = StringUtils.hasText(raw) ? raw.trim() : null;
        if (note != null && note.length() > MAX_NOTE_LENGTH) {
            throw BusinessException.validationError(String.format(
                    "备注最多 %d 字，当前 %d 字 —— 请精简后重试", MAX_NOTE_LENGTH, note.length()));
        }
        return note;
    }

    /** 台账 note 的前缀：谁 + 工号 + 原因（+ 备注）。上游会把它与批次盘点的原句拼起来并截断。 */
    private static String notePrefix(WorkerIdentity identity, String workerNo, String reasonLabel,
                                     String note) {
        StringBuilder sb = new StringBuilder("工人库存修正：");
        sb.append(StringUtils.hasText(identity.workerName()) ? identity.workerName() : "（未署名工人）");
        if (StringUtils.hasText(workerNo)) {
            sb.append("（工号 ").append(workerNo).append('）');
        }
        sb.append("，原因 ").append(reasonLabel);
        if (note != null) {
            sb.append("，备注 ").append(note);
        }
        return sb.toString();
    }

    /** 台账 {@code operator}：姓名优先、缺名回落工号、再缺回落 id（截到列宽 64）。 */
    private static String operatorOf(WorkerIdentity identity) {
        String operator = StringUtils.hasText(identity.workerName()) ? identity.workerName()
                : (StringUtils.hasText(identity.workerId()) ? identity.workerId() : "worker");
        return operator.length() <= 64 ? operator : operator.substring(0, 64);
    }

    /** 工号（会话行里有，但 {@link WorkerIdentity} 不承载 ⇒ 按 workerId 读一次；读不到不编）。 */
    private String workerNo(WorkerIdentity identity) {
        if (!StringUtils.hasText(identity.workerId())) {
            return null;
        }
        User user = userMapper.selectById(identity.workerId());
        return user == null ? null : user.getWorkerNo();
    }

    private String names(String productId) {
        if (!StringUtils.hasText(productId)) {
            return null;
        }
        List<Product> products = productMapper.selectList(new LambdaQueryWrapper<Product>()
                .in(Product::getId, List.of(productId)));
        return products.isEmpty() ? null : products.get(0).getName();
    }

    private Map<String, String> productNames(Long tenantId,
                                             List<BatchStockViews.BatchRemaining> rows) {
        Set<String> ids = new LinkedHashSet<>();
        for (BatchStockViews.BatchRemaining row : rows) {
            if (StringUtils.hasText(row.productId())) {
                ids.add(row.productId());
            }
        }
        if (ids.isEmpty()) {
            return Map.of();
        }
        List<Product> products = productMapper.selectList(new LambdaQueryWrapper<Product>()
                .eq(Product::getTenantId, tenantId)
                .in(Product::getId, ids));
        Map<String, String> out = new LinkedHashMap<>();
        for (Product product : products) {
            out.put(product.getId(), product.getName());
        }
        return out;
    }
}
