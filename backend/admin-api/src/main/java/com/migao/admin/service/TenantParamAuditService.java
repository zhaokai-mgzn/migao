package com.migao.admin.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.TenantParamAudit;
import com.migao.admin.mapper.TenantParamAuditMapper;
import com.migao.admin.security.SecurityUser;
import io.micrometer.core.instrument.MeterRegistry;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * 企业参数**变更留痕**（V131，issue #5131 = §22 **P6**）：把「谁 / 何时 / 哪个键 / 改前 → 改后」写进
 * {@code tenant_param_audit}（一行 = 一个参数键的一次变更）。
 *
 * <h3>🔴 口径 B = best-effort（用户 2026-09-26 裁定，登记在 issue #5131 评论）</h3>
 * <p><b>审计写失败只记日志（+ 计数），不让配置保存失败。</b>理由：这是<b>配置页</b>（不是资金流转），
 * 可用性优先；审计表是主要留痕载体，写入失败必须以<b>显眼的方式</b>留痕，并且<b>不得静默</b>。</p>
 *
 * <p>落码形态 = <b>本类的公开方法吞掉一切 {@link RuntimeException}</b>（调用方拿不到异常 ——
 * 「尽力而为」写在<b>一处</b>，而不是每个调用点各写一遍 try/catch）：</p>
 * <ul>
 *   <li>结构化日志行 {@code PARAM_AUDIT_WRITE_FAILED}（含 tenant / domain / operation / operationId /
 *       待写行数 / 已写行数 / 异常本身与栈）—— <b>可 grep、可告警</b>；</li>
 *   <li>指标 {@link #WRITE_FAILED_METRIC} 计数（Micrometer，与 {@code LoginFailureGuard} 同族）——
 *       <b>可画线、可告警</b>。</li>
 * </ul>
 *
 * <p>⚠️ 残留（如实登记，不粉饰）：口径 B 允许出现「改了钱、查不到谁改的」。上面两条就是那条路径的
 * 可观测面 —— 它们<b>不会</b>让配置保存失败，<b>也不会</b>让任何门禁变红。</p>
 *
 * <h3>身份（「谁改的」）—— 复用本仓既有机制，不另造</h3>
 * <p>本仓「谁干的」的既有口径 = 读 {@code SecurityContextHolder}（控制器内联形态见
 * {@code AgentBatchController#currentUserId}；服务层审计形态见
 * {@code StockLedgerService#resolveOperator}，被 {@code RemnantService} /
 * {@code StockBatchConsumptionService} 共用）。本类<b>同源</b>，只多记一列
 * <b>身份是怎么确定的</b>（{@code actor_source}，同 {@code worker_report_audits.identity_source} 的口径）：
 * 取不到认证上下文 ⇒ <b>如实记 {@code unknown} + 原因</b>（{@code no_authentication_context}），
 * <b>不编用户</b>、也<b>不</b>借用 {@code StockLedgerService} 的 {@code "system"} 冒充归属。
 * 同源由 {@code TenantParamAuditServiceTest#actorSourceStaysHomologousWithStockLedgerOperator} 钉住
 * （两处解析器对同一 SecurityContext 必须给出同一身份）。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class TenantParamAuditService {

    /** 参数域：算料配置（当前唯一写面 = {@code PUT /api/admin/production/craft-calc-config}）。 */
    public static final String DOMAIN_CRAFT_CALC = "craft_calc";

    /** 操作形态：全量替换写（当前唯一写面）。 */
    public static final String OPERATION_PUT = "put";

    /** 身份来源：取自 {@code SecurityContext} 的 {@link SecurityUser}（权威，body 伪造不了）。 */
    public static final String SOURCE_SECURITY_CONTEXT = "security_context";

    /** 身份来源：**无认证上下文**（服务令牌 / 定时任务 / 单测直调）⇒ 如实记未知。 */
    public static final String SOURCE_UNKNOWN = "unknown";

    /** {@link #SOURCE_UNKNOWN} 的原因：本次调用**没有**认证上下文（不是「用户不存在」）。 */
    public static final String UNKNOWN_NO_AUTH_CONTEXT = "no_authentication_context";

    /** 审计写失败的计数指标（口径 B 的可观测面之一；名字形态与 {@code migao.auth.*} 一致）。 */
    public static final String WRITE_FAILED_METRIC = "migao.tenant_param_audit.write_failed";

    private final TenantParamAuditMapper tenantParamAuditMapper;
    private final MeterRegistry meterRegistry;
    private final ObjectMapper objectMapper;

    /**
     * 生成一次写的**操作身份**（{@code CraftCalcConfigService} 在写前生成，日志行与账本行共用它 ⇒ 可对账）。
     */
    public static String newOperationId() {
        return "op-" + UUID.randomUUID().toString().replace("-", "").substring(0, 16);
    }

    /**
     * 记录 {@code before → after} 的**逐键差异**（只记真正变了的键；没变 ⇒ 零行、不写库）。
     *
     * <p>🔴 <b>本方法不会抛</b>（口径 B）：任何 {@link RuntimeException}（含 mapper 抛出的
     * 数据访问异常）都被吞在这里 —— 但会打 {@code PARAM_AUDIT_WRITE_FAILED} 并给
     * {@link #WRITE_FAILED_METRIC} 计数，<b>不静默</b>。</p>
     *
     * @param before 改前的值（配置行不存在 ⇒ {@code null} 或空映射 ⇒ 每个键的改前值都是 {@code null}）
     * @param after  改后的值（**必填**：PUT 是全量替换）
     * @return 实际落库的**行数**（0 = 没有变更，或写入失败 —— 两者由上面的日志/指标区分）
     */
    public int recordChanges(Long tenantId, String paramDomain, String operation, String operationId,
                             Map<String, Object> before, Map<String, Object> after) {
        List<TenantParamAudit> rows = List.of();
        int written = 0;
        try {
            rows = diff(tenantId, paramDomain, operation, operationId, before, after);
            if (rows.isEmpty()) {
                return 0;   // 没有变更 ⇒ 不写噪音行（「改了没有」这件事由零行如实表达）
            }
            Actor actor = resolveActor();
            for (TenantParamAudit row : rows) {
                row.setActorId(actor.id());
                row.setActorName(actor.name());
                row.setActorSource(actor.source());
                row.setActorUnknownReason(actor.reason());
                tenantParamAuditMapper.insert(row);
                written++;
            }
        } catch (RuntimeException e) {
            // 🔴 口径 B（用户 2026-09-26 裁定）：**配置已保存，审计没留上** —— 只记日志 + 计数，不向上抛。
            //    「已写」用于分辨部分落库（同一 operation_id 的行本应整批在一起）。
            meterRegistry.counter(WRITE_FAILED_METRIC, "param_domain", String.valueOf(paramDomain)).increment();
            log.error("PARAM_AUDIT_WRITE_FAILED 配置已保存但变更未留痕（「谁改的 / 改前是多少」查不到，"
                            + "口径 B = best-effort 有意如此）: tenantId={} paramDomain={} operation={} "
                            + "operationId={} 待写行数={} 已写行数={}",
                    tenantId, paramDomain, operation, operationId, rows.size(), written, e);
        }
        return written;
    }

    // ══════════════════════════════════════════════════════════════════════
    // 内部：差异 / 身份 / 取值形态
    // ══════════════════════════════════════════════════════════════════════

    /** 逐键求差（只保留**值真的变了**的键；同值 ⇒ 不写行）。 */
    private List<TenantParamAudit> diff(Long tenantId, String paramDomain, String operation,
                                        String operationId, Map<String, Object> before,
                                        Map<String, Object> after) {
        if (after == null || after.isEmpty()) {
            return List.of();
        }
        List<TenantParamAudit> rows = new ArrayList<>();
        OffsetDateTime now = OffsetDateTime.now();
        for (Map.Entry<String, Object> entry : after.entrySet()) {
            Object oldValue = before == null ? null : before.get(entry.getKey());
            Object newValue = entry.getValue();
            if (isUnchanged(oldValue, newValue)) {
                continue;
            }
            rows.add(TenantParamAudit.builder()
                    .id("tpa-" + UUID.randomUUID().toString().replace("-", ""))
                    .tenantId(tenantId)
                    .paramDomain(paramDomain)
                    .paramKey(entry.getKey())
                    .oldValue(text(oldValue))
                    .newValue(text(newValue))
                    .operation(operation)
                    .operationId(operationId)
                    .createdAt(now)
                    .deleted(0)
                    .build());
        }
        return rows;
    }

    /**
     * 两值是否**没变**（判据要偏「记下来」这一侧）。
     *
     * <p>数值按<b>数值</b>比（{@code 0.30} 与 {@code 0.3} 是同一个值 —— 改前值来自 {@code NUMERIC} 列
     * 的 {@link BigDecimal}，改后值来自校验后的 {@link BigDecimal}）；其余按 {@code equals}。</p>
     *
     * <p>⚠️ <b>命名是判据的一部分</b>：本方法刻意<b>不</b>与那个<b>价格核对</b>比较器同名 ——
     * 既有守卫 {@code AgentWriteValuesTest#comparatorHasASingleDefinition} 要求 main 源码里
     * <b>价格核对</b>的比较器只能有<b>一处定义</b>（方法名见 {@code AgentWriteValues}；返回 {@code boolean}、
     * 三参 {@code (field, given, current)}）。本方法比的是<b>配置差异</b>（两个语义、不得共享实现），
     * 同名会被那条既有守卫判红（本次实测踩到；处置 = 改名，<b>不是</b>放宽守卫）。</p>
     *
     * <p>⚠️ 连<b>注释里</b>写那个方法名 + 参数括号都会再次触发该守卫（它只剥 {@code //} 行注释、
     * 不剥块注释；实测踩过一次）⇒ 本节<b>刻意</b>不写出完整签名 —— 「引用即实例」。</p>
     *
     * <p>⚠️ 已知偏向（<b>有意的</b>）：嵌套结构里若两侧数值的<b>表示类型</b>不同（如 {@code Integer 2} 与
     * {@code Double 2.0}）会被判成「变了」⇒ 多写一行「2 → 2.0」。这是<b>安全的那一侧</b>：
     * 宁可多留一行，不可漏掉一次真变更。</p>
     */
    private static boolean isUnchanged(Object a, Object b) {
        if (a == null || b == null) {
            return a == b;
        }
        if (a instanceof Number na && b instanceof Number nb) {
            try {
                return new BigDecimal(na.toString()).compareTo(new BigDecimal(nb.toString())) == 0;
            } catch (NumberFormatException e) {
                return a.equals(b);   // NaN / Infinity 之类（写面校验本就会拒 ⇒ 这里只保证不抛）
            }
        }
        return a.equals(b);
    }

    /**
     * 落库形态：标量给**字面量**（数值不写成科学计数法），结构化值（{@code tiers} /
     * {@code per_fold_mixed_times}）给 **JSON**（可被下游解析，而不是 Java 的 {@code Map.toString()}）。
     */
    private String text(Object value) {
        if (value == null) {
            return null;
        }
        if (value instanceof CharSequence s) {
            return s.toString();
        }
        if (value instanceof BigDecimal b) {
            return b.toPlainString();
        }
        if (value instanceof Number n) {
            return n.toString();
        }
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException e) {
            return String.valueOf(value);
        }
    }

    /** 身份解析（与 {@code StockLedgerService#resolveOperator} 同源，只多记「怎么确定的」）。 */
    private static Actor resolveActor() {
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth != null && auth.getPrincipal() instanceof SecurityUser securityUser) {
            return new Actor(securityUser.getUserId(), securityUser.getUsername(), SOURCE_SECURITY_CONTEXT, null);
        }
        return new Actor(null, null, SOURCE_UNKNOWN, UNKNOWN_NO_AUTH_CONTEXT);
    }

    /** 一次调用解出的身份（{@code source='unknown'} 时 {@code reason} 必非空 —— DB 侧同款约束）。 */
    private record Actor(String id, String name, String source, String reason) {
    }
}
