package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.entity.ProductionPieceworkSettlement;
import com.migao.admin.entity.ProductionPieceworkSettlementLine;
import com.migao.admin.entity.ProductionWorkLog;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProductionPieceworkSettlementLineMapper;
import com.migao.admin.mapper.ProductionPieceworkSettlementMapper;
import com.migao.admin.mapper.ProductionWorkLogMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.YearMonth;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 计件工资**结算**（issue #4483 = 母单 #4347 §二.4；真值源 §4）。
 *
 * <h2>它补的是哪一层</h2>
 *
 * 既有报表（{@code ProductionService.pieceworkSummary}）回答「这段时间挣了多少」，
 * 但**回答不了「这笔钱结了没有」**。没有这一层，工资可以被**事后静默改写** ——
 * 报工可增可改（补报 / 返工 / 重新实例化都会动聚合口径），而**已经发出去的钱**不该跟着变。
 *
 * <h2>锁定语义（本层的核心，不能省）</h2>
 *
 * {@code settled} 之后，该 {@code (tenantId, period, workerKey)} 的报工**不得再被改动**：
 * 报工入口（{@link ProductionService#report}）会调 {@link #assertNotSettled} 拦下，
 * 补报走**调整单**（新记录 + 留痕），**不回改历史** ——
 * 与既有纪律「快照冻结、不回算历史工资」（V61 / issue #4351）同源。
 *
 * <h2>逐笔可追溯（真值源 §4）</h2>
 *
 * 每张结算单都落 {@code production_piecework_settlement_lines}，逐笔指回
 * {@code production_work_logs.id} —— 金额能拆回每一笔，而不是只有一个总数。
 *
 * <h2>不加审批环节（用户裁定 2026-09-19）</h2>
 *
 * 「先做到**可核对**」：{@code draft → settled} 一步确认即可，不引入多级审批状态机。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class PieceworkSettlementService {

    private static final String STATUS_DRAFT = "draft";
    private static final String STATUS_SETTLED = "settled";

    private final ProductionPieceworkSettlementMapper settlementMapper;
    private final ProductionPieceworkSettlementLineMapper lineMapper;
    private final ProductionWorkLogMapper workLogMapper;
    private final ProductionService productionService;

    /**
     * 生成某期的结算单（**按人**，全租户）。
     *
     * <p>幂等：已存在**同人同期**的活跃结算单 ⇒ 跳过（不重复生成、不覆盖已结算的）。
     * 金额与逐笔明细都来自**当期报工**，且逐笔金额复用
     * {@link ProductionService#logAmount}（**唯一**公式，不复制第二份）。</p>
     *
     * @return {period, generated, skipped, settlements:[{worker_key, worker_name, amount, qty, line_count, status}]}
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> generate(String period, Long tenantId) {
        YearMonth month = parsePeriod(period);
        List<ProductionWorkLog> logs = listPeriodLogs(month, tenantId);
        Map<String, ProcessingPositionOperation> ops = activeOperationsById(tenantId);

        // 按工人分组（工人键 = worker_id 非空取它，否则取姓名 —— 与唯一索引同口径）
        Map<String, List<ProductionWorkLog>> byWorker = new LinkedHashMap<>();
        for (ProductionWorkLog log : logs) {
            byWorker.computeIfAbsent(workerKeyOf(log), k -> new ArrayList<>()).add(log);
        }

        List<Map<String, Object>> rows = new ArrayList<>();
        int generated = 0;
        int skipped = 0;
        for (Map.Entry<String, List<ProductionWorkLog>> entry : byWorker.entrySet()) {
            String workerKey = entry.getKey();
            ProductionPieceworkSettlement existing = findActive(tenantId, month.toString(), workerKey);
            if (existing != null) {
                skipped++;
                rows.add(settlementView(existing));
                continue;
            }
            ProductionPieceworkSettlement settlement =
                    createDraft(month, tenantId, workerKey, entry.getValue(), ops);
            generated++;
            rows.add(settlementView(settlement));
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("period", month.toString());
        result.put("generated", generated);
        result.put("skipped", skipped);
        result.put("settlements", rows);
        return result;
    }

    /**
     * **确认结算**（draft → settled，一步，不加审批）。
     *
     * <p>锁定之后该期该人的报工不可再改；再次确认 ⇒ 422（不静默重复结算）。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> settle(String settlementId, String operator, Long tenantId) {
        ProductionPieceworkSettlement settlement = settlementMapper.selectById(settlementId);
        if (settlement == null || !tenantId.equals(settlement.getTenantId())
                || Integer.valueOf(1).equals(settlement.getDeleted())) {
            throw BusinessException.notFound("结算单");
        }
        if (STATUS_SETTLED.equals(settlement.getStatus())) {
            throw BusinessException.validationError(
                    "该结算单已确认（" + settlement.getPeriod() + " / "
                            + settlement.getWorkerName() + "），不能重复结算");
        }
        settlement.setStatus(STATUS_SETTLED);
        settlement.setSettledAt(OffsetDateTime.now());
        settlement.setSettledBy(StringUtils.hasText(operator) ? operator.trim() : null);
        settlement.setUpdatedAt(OffsetDateTime.now());
        settlementMapper.updateById(settlement);
        log.info("计件结算已确认: id={}, period={}, worker={}, amount={}",
                settlementId, settlement.getPeriod(), settlement.getWorkerName(), settlement.getAmount());
        return settlementView(settlement);
    }

    /**
     * 结算单详情（含**逐笔明细**，真值源 §4「逐笔可追溯」）。
     */
    public Map<String, Object> detail(String settlementId, Long tenantId) {
        ProductionPieceworkSettlement settlement = settlementMapper.selectById(settlementId);
        if (settlement == null || !tenantId.equals(settlement.getTenantId())
                || Integer.valueOf(1).equals(settlement.getDeleted())) {
            throw BusinessException.notFound("结算单");
        }
        List<ProductionPieceworkSettlementLine> lines = lineMapper.selectList(
                new LambdaQueryWrapper<ProductionPieceworkSettlementLine>()
                        .eq(ProductionPieceworkSettlementLine::getSettlementId, settlementId)
                        .eq(ProductionPieceworkSettlementLine::getTenantId, tenantId)
                        .eq(ProductionPieceworkSettlementLine::getDeleted, 0)
                        .orderByAsc(ProductionPieceworkSettlementLine::getWorkDate));
        List<Map<String, Object>> lineViews = new ArrayList<>();
        for (ProductionPieceworkSettlementLine line : lines) {
            Map<String, Object> view = new LinkedHashMap<>();
            view.put("work_log_id", line.getWorkLogId());
            view.put("processing_order_id", line.getProcessingOrderId());
            view.put("operation_name", line.getOperationName());
            view.put("work_date", line.getWorkDate() == null ? null : line.getWorkDate().toString());
            view.put("amount", line.getAmount());
            view.put("qty", line.getQty());
            lineViews.add(view);
        }
        Map<String, Object> result = settlementView(settlement);
        result.put("lines", lineViews);
        return result;
    }

    /**
     * 该期该人**是否已结算**（报工入口的守卫）。
     *
     * <p>命中 ⇒ 抛 422 并**指名期次**（「哪一期被锁了」是工人能行动的信息；
     * 只说「不能报工」等于没说）。</p>
     */
    public void assertNotSettled(Long tenantId, LocalDate workDate, String workerId, String workerName) {
        assertPeriodNotLocked(settlementMapper, tenantId, workDate, workerId, workerName);
    }

    /**
     * 报工入口的**锁定守卫**（issue #4483 §二.4）。
     *
     * <p><b>为什么是 static 而不是实例方法</b>：报工在 {@link ProductionService}，而
     * {@code PieceworkSettlementService} 依赖它 ⇒ 反向注入会形成**循环依赖**（Spring 启动即失败）。
     * 故守卫做成「拿 mapper 就能判」的纯函数：两个调用点各自传入自己的 mapper，
     * 判定逻辑**只有这一份**（不复制第二份口径）。</p>
     *
     * <p>命中已结算 ⇒ 抛 422 并**指名期次**（「哪一期被锁了」是工人能行动的信息；
     * 只说「不能报工」等于没说）。</p>
     */
    static void assertPeriodNotLocked(ProductionPieceworkSettlementMapper mapper, Long tenantId,
                                      LocalDate workDate, String workerId, String workerName) {
        if (workDate == null || mapper == null) {
            return;
        }
        String period = YearMonth.from(workDate).toString();
        String key = workerKey(workerId, workerName);
        List<ProductionPieceworkSettlement> rows = mapper.selectList(
                new LambdaQueryWrapper<ProductionPieceworkSettlement>()
                        .eq(ProductionPieceworkSettlement::getTenantId, tenantId)
                        .eq(ProductionPieceworkSettlement::getPeriod, period)
                        .eq(ProductionPieceworkSettlement::getWorkerKey, key)
                        .eq(ProductionPieceworkSettlement::getDeleted, 0));
        if (rows == null || rows.isEmpty()) {
            return;
        }
        ProductionPieceworkSettlement settlement = rows.get(0);
        if (STATUS_SETTLED.equals(settlement.getStatus())) {
            throw BusinessException.validationError(
                    String.format("该期工资已结算并锁定（%s / %s），不能再报工或改动；"
                                    + "如需补报请走调整单（不回改历史）",
                            period, settlement.getWorkerName()));
        }
    }

    // ── 内部 ──────────────────────────────────────────────────────────────────────

    private ProductionPieceworkSettlement createDraft(YearMonth month, Long tenantId, String workerKey,
                                                      List<ProductionWorkLog> logs,
                                                      Map<String, ProcessingPositionOperation> ops) {
        BigDecimal total = BigDecimal.ZERO;
        BigDecimal qty = BigDecimal.ZERO;
        List<ProductionPieceworkSettlementLine> lines = new ArrayList<>();
        String workerId = null;
        String workerName = null;
        for (ProductionWorkLog log : logs) {
            if (!"normal".equals(log.getWorkType())) {
                continue; // 返工/报废不计件（与报表同一口径）
            }
            ProcessingPositionOperation op = ops.get(log.getOperationId());
            boolean hasSnapshot = log.getUnitPrice() != null;
            if (!hasSnapshot && op == null) {
                continue; // 既无快照、实例又真的不存在（脏数据）⇒ 不可计价（与报表同一兜底）
            }
            BigDecimal amount = ProductionService.logAmount(log, op);
            total = total.add(amount);
            qty = qty.add(ProductionService.nz(log.getQualifiedQty()));
            if (workerId == null && StringUtils.hasText(log.getWorkerId())) {
                workerId = log.getWorkerId();
            }
            if (workerName == null && StringUtils.hasText(log.getWorkerName())) {
                workerName = log.getWorkerName();
            }
            lines.add(ProductionPieceworkSettlementLine.builder()
                    .tenantId(tenantId)
                    .workLogId(log.getId())
                    .processingOrderId(log.getProcessingOrderId())
                    .operationName(log.getOperationName())
                    .workDate(log.getWorkDate())
                    .amount(amount)
                    .qty(ProductionService.nz(log.getQualifiedQty()))
                    .createdAt(OffsetDateTime.now())
                    .deleted(0)
                    .build());
        }

        ProductionPieceworkSettlement settlement = ProductionPieceworkSettlement.builder()
                .tenantId(tenantId)
                .period(month.toString())
                .workerId(workerId)
                .workerKey(workerKey)
                .workerName(workerName)
                .amount(total)
                .qty(qty)
                .lineCount(lines.size())
                .status(STATUS_DRAFT)
                .createdAt(OffsetDateTime.now())
                .updatedAt(OffsetDateTime.now())
                .deleted(0)
                .build();
        settlementMapper.insert(settlement);
        for (ProductionPieceworkSettlementLine line : lines) {
            line.setSettlementId(settlement.getId());
            lineMapper.insert(line);
        }
        log.info("生成计件结算单: period={}, worker={}, amount={}, lines={}",
                month, workerKey, total, lines.size());
        return settlement;
    }

    private ProductionPieceworkSettlement findActive(Long tenantId, String period, String workerKey) {
        List<ProductionPieceworkSettlement> rows = settlementMapper.selectList(
                new LambdaQueryWrapper<ProductionPieceworkSettlement>()
                        .eq(ProductionPieceworkSettlement::getTenantId, tenantId)
                        .eq(ProductionPieceworkSettlement::getPeriod, period)
                        .eq(ProductionPieceworkSettlement::getWorkerKey, workerKey)
                        .eq(ProductionPieceworkSettlement::getDeleted, 0));
        return rows == null || rows.isEmpty() ? null : rows.get(0);
    }

    private List<ProductionWorkLog> listPeriodLogs(YearMonth month, Long tenantId) {
        List<ProductionWorkLog> logs = workLogMapper.selectList(new LambdaQueryWrapper<ProductionWorkLog>()
                .eq(ProductionWorkLog::getTenantId, tenantId)
                .eq(ProductionWorkLog::getDeleted, 0)
                .ge(ProductionWorkLog::getWorkDate, month.atDay(1))
                .le(ProductionWorkLog::getWorkDate, month.atEndOfMonth())
                .orderByAsc(ProductionWorkLog::getWorkDate));
        return logs == null ? List.of() : logs;
    }

    private Map<String, ProcessingPositionOperation> activeOperationsById(Long tenantId) {
        // 与 ProductionService.activeOperationsById 同一判据（tenant + deleted=0）：
        // 已软删实例不得被算进来，否则同一笔报工在两处计价不同（#4205 判据要防的漂移）
        Map<String, ProcessingPositionOperation> byId = new LinkedHashMap<>();
        for (ProcessingPositionOperation op : productionService.listActiveOperations(tenantId)) {
            byId.put(op.getId(), op);
        }
        return byId;
    }

    /** 工人唯一键（{@code worker_id} 非空取它，否则取姓名）—— 与唯一索引同口径。 */
    private static String workerKeyOf(ProductionWorkLog log) {
        return workerKey(log.getWorkerId(), log.getWorkerName());
    }

    private static String workerKey(String workerId, String workerName) {
        if (StringUtils.hasText(workerId)) {
            return workerId.trim();
        }
        return StringUtils.hasText(workerName) ? workerName.trim() : "未分配";
    }

    private static Map<String, Object> settlementView(ProductionPieceworkSettlement settlement) {
        Map<String, Object> view = new LinkedHashMap<>();
        view.put("id", settlement.getId());
        view.put("period", settlement.getPeriod());
        view.put("worker_id", settlement.getWorkerId());
        view.put("worker_key", settlement.getWorkerKey());
        view.put("worker_name", settlement.getWorkerName());
        view.put("amount", settlement.getAmount());
        view.put("qty", settlement.getQty());
        view.put("line_count", settlement.getLineCount());
        view.put("status", settlement.getStatus());
        view.put("settled_at", settlement.getSettledAt() == null ? null : settlement.getSettledAt().toString());
        view.put("settled_by", settlement.getSettledBy());
        return view;
    }

    private static YearMonth parsePeriod(String period) {
        if (!StringUtils.hasText(period)) {
            throw BusinessException.validationError("period 不能为空（格式 YYYY-MM）");
        }
        try {
            return YearMonth.parse(period.trim());
        } catch (Exception e) {
            throw BusinessException.validationError("period 格式必须是 YYYY-MM");
        }
    }
}
