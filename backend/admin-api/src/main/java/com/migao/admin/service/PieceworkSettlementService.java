package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.PieceworkSettlement;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.PieceworkSettlementMapper;
import com.migao.admin.time.BusinessClock;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.time.YearMonth;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * <b>计件结算单</b>（issue #5653）—— 生成 / 列 / 详情 / 作废，**没有任何改写路径**。
 *
 * <h2>口径（用户 2026-10-16 裁定 A 快照式；本类的语义真值源）</h2>
 * <ul>
 *   <li><b>生成即冻结、不可改</b>：一行落库后，金额 / 期间 / 工人 / 明细**没有任何改写入口**。
 *       要改 ⇒ 作废（{@link #voidSettlement}）+ 重开新单；</li>
 *   <li><b>作废留痕、不物理删</b>：作废只置 {@code voided_at} / {@code voided_by} / {@code void_reason}，
 *       行仍在表里可查；</li>
 *   <li><b>期间唯一性取「具名报错」</b>（四条判据里的第三条第 3 项二选一）：同租户 × 同期间 × 同工人
 *       已有**活跃**单 ⇒ {@code 409 PIECEWORK_SETTLEMENT_EXISTS}，可行动提示 = 先作废再重开。
 *       <b>依据</b>：本单的语义是「凭证」而不是「缓存」—— 幂等返回既有单会让商家以为「我刚点的这次
 *       生成生效了」，而实际上看到的是**别的时点**的冻结值；经营账目上「同一动作两次不同结论」比
 *       多一个 409 危险得多。并发面由 {@code ON CONFLICT DO NOTHING} 原子闸保证**绝不**落两行、也绝不 500
 *       （见 {@code PieceworkSettlementMapper.insertActiveIfAbsent}）；</li>
 *   <li><b>金额服务端算、且与报表同源</b>：{@link #generate} 逐值取
 *       {@link ProductionService#pieceworkSummary} 的 {@code total} 与 {@code per_operation}
 *       —— 本类**不注入**报工表 / 工序实例表 Mapper，也**不调用**聚合算法（结构判据：结算侧没有第二份算法）。</li>
 * </ul>
 *
 * <h2>本轮不做（用户裁定排除，不许读成已解决）</h2>
 * 发放状态字段（已发/未发）、发放动作、导出、与财务域耦合 —— 重启条件见 issue #5653 的口径裁定评论。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class PieceworkSettlementService {

    /** 「同期间 × 同工人已有活跃单」—— 具名 409，提示可行动的出口（先作废再重开）。 */
    public static final String CODE_EXISTS = "PIECEWORK_SETTLEMENT_EXISTS";
    /** 该期间该工人**没有可结的计件金额**（未报工 / 未定价 ⇒ 金额算不出来）—— 不落 0 元单。 */
    public static final String CODE_NO_AMOUNT = "PIECEWORK_SETTLEMENT_NO_AMOUNT";
    /** 单不存在 / 跨租户 / 已作废（作废动作的目标侧）。 */
    public static final String CODE_NOT_FOUND = "PIECEWORK_SETTLEMENT_NOT_FOUND";
    /** 期间非法（必须 {@code YYYY-MM}，与报表端点同一份校验口径）。 */
    public static final String CODE_BAD_PERIOD = "VALIDATION_ERROR";

    private final PieceworkSettlementMapper settlementMapper;
    private final ProductionService productionService;

    /** 结算序号 / 留痕用的「业务现在」（仓内唯一时钟单点；**不写**时区字面量、**不用**无参 now()）。 */
    @Autowired(required = false)
    private BusinessClock businessClock = new BusinessClock();

    private static final ObjectMapper JSON = new ObjectMapper();

    /**
     * 生成一张结算单（期间 × 工人）—— 金额**逐值**取自 {@code piecework/summary}。
     *
     * @param period     期间 {@code YYYY-MM}（必填，非法 ⇒ 422）
     * @param workerName 工人名（必填非空白）
     * @param tenantId   租户（跨租户隔离）
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> generate(String period, String workerName, Long tenantId) {
        String normalizedPeriod = normalizePeriod(period);
        String worker = requireWorker(workerName);
        if (!settlementMapper.selectList(activeQuery(tenantId, normalizedPeriod, worker)).isEmpty()) {
            // 具名报错（不是幂等返回）：见类注记「期间唯一性取一」的依据
            throw exists(worker, normalizedPeriod);
        }

        // 🔴 唯一真值：与报表 / per-order / 工人端**同一个聚合**的读数，本侧不重算
        Map<String, Object> summary = productionService.pieceworkSummary(normalizedPeriod, worker, tenantId);
        Map<String, Object> workerRow = perWorkerRow(summary, worker);
        if (workerRow == null) {
            throw new BusinessException(CODE_NO_AMOUNT,
                    "「" + worker + "」在 " + normalizedPeriod + " 没有可结的计件金额（未报工，或报工的工序未定价）"
                            + "—— 未定价 ≠ ¥0.00，本系统不会为它落一张 0 元结算单。",
                    422);
        }
        BigDecimal amount = (BigDecimal) workerRow.get("amount");
        List<PieceworkSettlement.LineItem> lines = lineItems(summary);

        OffsetDateTime now = businessClock.nowOffset();
        String actor = currentUserId();
        PieceworkSettlement row = PieceworkSettlement.builder()
                .tenantId(tenantId)
                .period(normalizedPeriod)
                .workerName(worker)
                .totalAmount(amount)
                .lineItems(lines)
                .generatedBy(actor)
                .generatedAt(now)
                .createdAt(now)
                .updatedAt(now)
                .build();
        row.setDeleted(0);

        if (settlementMapper.insertActiveIfAbsent(row, toJson(lines)) == 0) {
            // 原子闸拦下的并发败者：绝不落第二行、也绝不 500
            throw exists(worker, normalizedPeriod);
        }
        log.info("计件结算单已生成 tenant={} period={} worker={} settlement={} amount={}",
                tenantId, normalizedPeriod, worker, row.getId(), amount);
        return view(row, summary);
    }

    /** 列结算单（期间可选；默认**含已作废**—— 留痕要求「旧单仍在、可查」）。 */
    public Map<String, Object> list(String period, Boolean includeVoided, Long tenantId) {
        QueryWrapper<PieceworkSettlement> wrapper = new QueryWrapper<PieceworkSettlement>()
                .eq("tenant_id", tenantId)
                .eq("deleted", 0)
                .orderByDesc("period")
                .orderByAsc("worker_name")
                .orderByDesc("created_at");
        if (StringUtils.hasText(period)) {
            wrapper.eq("period", normalizePeriod(period));
        }
        List<PieceworkSettlement> rows = settlementMapper.selectList(wrapper);
        List<Map<String, Object>> items = new ArrayList<>();
        int voided = 0;
        for (PieceworkSettlement row : rows) {
            boolean isVoided = row.getVoidedAt() != null;
            if (isVoided) {
                voided++;
            }
            if (Boolean.FALSE.equals(includeVoided) && isVoided) {
                continue;
            }
            items.add(rowView(row, null));
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("period", StringUtils.hasText(period) ? normalizePeriod(period) : null);
        result.put("total", items.size());
        result.put("voided_count", voided);
        result.put("items", items);
        return result;
    }

    /**
     * 结算单详情。响应同时给出**冻结快照**与该期间**现取**的报表读数 ——
     * 「同源」在消费面上可见（{@code snapshot.total_amount} vs {@code summary.total}）。
     */
    public Map<String, Object> detail(String id, Long tenantId) {
        PieceworkSettlement row = requireSettlement(id, tenantId);
        return view(row, productionService.pieceworkSummary(row.getPeriod(), row.getWorkerName(), tenantId));
    }

    /**
     * 作废一张活跃单（**不物理删**）：只置 voided_at / voided_by / void_reason。
     *
     * @param reason 作废原因（必填非空白 —— 留痕要答得出「为什么」）
     */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> voidSettlement(String id, String reason, Long tenantId) {
        if (!StringUtils.hasText(reason)) {
            throw new BusinessException("VALIDATION_ERROR", "作废结算单必须填写作废原因（留痕要答得出「为什么作废」）。", 422);
        }
        OffsetDateTime now = businessClock.nowOffset();
        String actor = currentUserId();
        if (settlementMapper.voidActive(id, tenantId, actor, reason.trim(), now) != 1) {
            throw new BusinessException(CODE_NOT_FOUND,
                    "结算单不存在、已作废或不属于当前企业 —— 已作废的单不会二次作废（幂等空操作判为失败，不谎报成功）。",
                    409);
        }
        PieceworkSettlement row = settlementMapper.selectById(id);
        log.info("计件结算单已作废 tenant={} settlement={} by={}", tenantId, id, actor);
        return rowView(row, null);
    }

    // ── 内部 ────────────────────────────────────────────────────────────────

    private static QueryWrapper<PieceworkSettlement> activeQuery(Long tenantId, String period, String worker) {
        return new QueryWrapper<PieceworkSettlement>()
                .eq("tenant_id", tenantId)
                .eq("period", period)
                .eq("worker_name", worker)
                .eq("deleted", 0)
                .isNull("voided_at");
    }

    private PieceworkSettlement requireSettlement(String id, Long tenantId) {
        PieceworkSettlement row = settlementMapper.selectById(id);
        if (row == null || !tenantId.equals(row.getTenantId())) {
            throw new BusinessException(CODE_NOT_FOUND, "结算单不存在或不属于当前企业。", 404);
        }
        return row;
    }

    private static BusinessException exists(String worker, String period) {
        return new BusinessException(CODE_EXISTS,
                "「" + worker + "」在 " + period + " 已有一张生效的结算单（结算单生成即冻结、不可改）。"
                        + "如需按最新报工重开：先作废那张单（填写原因），再重新生成。",
                409);
    }

    /** 期间校验（与报表端点同一份口径：{@code YYYY-MM}；缺失/非法 ⇒ 422 可行动错误）。 */
    private static String normalizePeriod(String period) {
        if (!StringUtils.hasText(period)) {
            throw new BusinessException(CODE_BAD_PERIOD, "缺少期间参数 period，格式 YYYY-MM（例如 2026-10）。", 422);
        }
        try {
            return YearMonth.parse(period.trim()).toString();
        } catch (DateTimeParseException e) {
            throw new BusinessException(CODE_BAD_PERIOD,
                    "期间格式非法：" + period + "（应为 YYYY-MM，例如 2026-10）。", 422);
        }
    }

    private static String requireWorker(String workerName) {
        if (!StringUtils.hasText(workerName)) {
            throw new BusinessException("VALIDATION_ERROR", "缺少工人姓名 worker_name。", 422);
        }
        return workerName.trim();
    }

    /** 从报表读数里取该工人那一行（取不到 ⇒ {@code null}，调用方给具名 422）。 */
    @SuppressWarnings("unchecked")
    private static Map<String, Object> perWorkerRow(Map<String, Object> summary, String worker) {
        Object rows = summary.get("per_worker");
        if (!(rows instanceof List<?> list)) {
            return null;
        }
        for (Object item : list) {
            if (item instanceof Map<?, ?> map && worker.equals(map.get("worker_name"))) {
                return (Map<String, Object>) map;
            }
        }
        return null;
    }

    /** 明细快照 = 报表 {@code per_operation} 的同源子集（只留工序 / 数量 / 金额三个键）。 */
    @SuppressWarnings("unchecked")
    private static List<PieceworkSettlement.LineItem> lineItems(Map<String, Object> summary) {
        List<PieceworkSettlement.LineItem> lines = new ArrayList<>();
        Object rows = summary.get("per_operation");
        if (!(rows instanceof List<?> list)) {
            return lines;
        }
        for (Object item : list) {
            if (!(item instanceof Map<?, ?> map)) {
                continue;
            }
            Map<String, Object> row = (Map<String, Object>) map;
            lines.add(new PieceworkSettlement.LineItem(
                    row.get("operation") == null ? null : String.valueOf(row.get("operation")),
                    (BigDecimal) row.get("qty"),
                    (BigDecimal) row.get("amount")));
        }
        return lines;
    }

    private static String toJson(List<PieceworkSettlement.LineItem> lines) {
        try {
            return JSON.writeValueAsString(lines);
        } catch (JsonProcessingException e) {
            // 明细只在生成那一刻序列化；失败就**不要**落一张没有明细的结算单（不静默降级）
            throw new BusinessException("PIECEWORK_SETTLEMENT_SERIALIZE_FAILED",
                    "结算明细序列化失败，本次未生成结算单。", 500);
        }
    }

    /** 行视图（列表 / 详情 / 生成 / 作废共用一处 —— 同一条记录不允许有两种形状）。 */
    private static Map<String, Object> rowView(PieceworkSettlement row, Map<String, Object> summary) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", row.getId());
        out.put("period", row.getPeriod());
        out.put("worker_name", row.getWorkerName());
        out.put("total_amount", row.getTotalAmount());
        out.put("line_items", row.getLineItems());
        out.put("generated_by", row.getGeneratedBy());
        out.put("generated_at", row.getGeneratedAt());
        out.put("voided", row.getVoidedAt() != null);
        out.put("voided_at", row.getVoidedAt());
        out.put("voided_by", row.getVoidedBy());
        out.put("void_reason", row.getVoidReason());
        if (summary != null) {
            out.put("summary_total", summary.get("total"));
        }
        return out;
    }

    /** 生成动作的响应 = 行视图 + 本次依据的报表读数（同源在消费面上可见）。 */
    private static Map<String, Object> view(PieceworkSettlement row, Map<String, Object> summary) {
        Map<String, Object> out = rowView(row, summary);
        out.put("same_source", true);
        return out;
    }

    /**
     * 「谁干的」= {@code SecurityUser.userId}（与 {@code TenantParamAuditService.resolveActor} /
     * {@code StockLedgerService.resolveOperator} 同一口径）。无认证上下文 ⇒ {@code null}
     * —— **不编造**身份（本服务由端点的授权闸把守，无认证时到不了这里）。
     */
    private static String currentUserId() {
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth != null && auth.getPrincipal() instanceof com.migao.admin.security.SecurityUser user) {
            return user.getUserId();
        }
        return null;
    }
}
