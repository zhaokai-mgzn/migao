package com.migao.admin.service;

// case_ids: OR-041

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.TenantParamAudit;
import com.migao.admin.mapper.TenantParamAuditMapper;
import com.migao.admin.security.SecurityUser;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 企业参数**变更留痕**服务（V131，issue #5131 = §22 **P6**）—— 口径 **B = best-effort**
 * （用户 2026-09-26 裁定：审计写失败只记日志 + 计数，不让配置保存失败）。
 *
 * <p>守四条会被下一位验收者重开的判据：</p>
 * <ol>
 *   <li><b>一行 = 一个真正变了的键</b>：改了 1 个键 ⇒ 恰好 1 行、改前改后逐值正确（红证：
 *       把「只记变了的键」改成「全记」⇒ 行数断言红；把 old/new 写反 ⇒ 逐值断言红）；</li>
 *   <li><b>没变的键不写行</b>（红证：去掉 {@code sameValue} 短路 ⇒ 零行断言红）；</li>
 *   <li><b>取不到身份 ⇒ unknown + 原因</b>（红证：回落 {@code "system"} / 编一个用户 ⇒
 *       {@code actorName} 非空断言红）；</li>
 *   <li><b>写失败不抛、但可观测</b>（红证：去掉 try/catch ⇒ 本测试抛异常即红；去掉计数 ⇒
 *       指标断言红）。</li>
 * </ol>
 */
@DisplayName("TenantParamAuditService 变更留痕（issue #5131 P6）")
class TenantParamAuditServiceTest {

    private static final Long TENANT = 7L;
    private static final String OP = "op-0123456789abcdef";

    private TenantParamAuditMapper mapper;
    private SimpleMeterRegistry meters;
    private TenantParamAuditService service;

    @BeforeEach
    void setUp() {
        mapper = mock(TenantParamAuditMapper.class);
        meters = new SimpleMeterRegistry();
        service = new TenantParamAuditService(mapper, meters, new ObjectMapper());
    }

    @AfterEach
    void tearDown() {
        SecurityContextHolder.clearContext();
    }

    // ══════════════════════════════════════════════════════════════════════
    // 判据 1：一行 = 一个真正变了的键（值 / 身份 / 操作身份逐格正确）
    // ══════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("改了一个键 ⇒ 恰好一行，改前→改后与「谁改的」逐格正确")
    void recordsExactlyOneRowPerChangedKey() {
        authenticate("u-9", "13800138000");

        int written = service.recordChanges(TENANT, TenantParamAuditService.DOMAIN_CRAFT_CALC,
                TenantParamAuditService.OPERATION_PUT, OP,
                Map.of("hem_margin", new BigDecimal("0.3"), "margin_single", new BigDecimal("0.2")),
                Map.of("hem_margin", new BigDecimal("0.25"), "margin_single", new BigDecimal("0.2")));

        assertThat(written).isEqualTo(1);
        TenantParamAudit row = onlyRow();
        assertThat(row.getTenantId()).isEqualTo(TENANT);
        assertThat(row.getParamDomain()).isEqualTo(TenantParamAuditService.DOMAIN_CRAFT_CALC);
        assertThat(row.getParamKey()).isEqualTo("hem_margin");
        assertThat(row.getOldValue()).isEqualTo("0.3");
        assertThat(row.getNewValue()).isEqualTo("0.25");
        assertThat(row.getOperation()).isEqualTo(TenantParamAuditService.OPERATION_PUT);
        assertThat(row.getOperationId()).isEqualTo(OP);
        assertThat(row.getActorId()).isEqualTo("u-9");
        assertThat(row.getActorName()).isEqualTo("13800138000");
        assertThat(row.getActorSource()).isEqualTo(TenantParamAuditService.SOURCE_SECURITY_CONTEXT);
        // 身份**确定**时不得带「为什么不知道」—— DB 侧由 ck_tenant_param_audit_unknown 同款钉住
        assertThat(row.getActorUnknownReason()).isNull();
        assertThat(row.getCreatedAt()).isNotNull();
        assertThat(row.getId()).isNotBlank();
    }

    @Test
    @DisplayName("配置行不存在（首次保存）⇒ 改前值为 null（**不是**把引擎默认值当成改前值）")
    void firstSaveHasNullOldValues() {
        authenticate("u-9", "13800138000");

        service.recordChanges(TENANT, TenantParamAuditService.DOMAIN_CRAFT_CALC,
                TenantParamAuditService.OPERATION_PUT, OP,
                Map.of(), Map.of("hem_margin", new BigDecimal("0.25")));

        TenantParamAudit row = onlyRow();
        assertThat(row.getOldValue()).isNull();
        assertThat(row.getNewValue()).isEqualTo("0.25");
    }

    @Test
    @DisplayName("结构化值（tiers）落成 JSON，不是 Java 的 Map.toString")
    void structuredValuesArePersistedAsJson() {
        authenticate("u-9", "13800138000");
        Map<String, Object> tier = new LinkedHashMap<>();
        tier.put("fullness", new BigDecimal("2.0"));
        tier.put("label", "标准工艺");

        service.recordChanges(TENANT, TenantParamAuditService.DOMAIN_CRAFT_CALC,
                TenantParamAuditService.OPERATION_PUT, OP,
                Map.of(), Map.of("tiers", Map.of("standard", tier)));

        String newValue = onlyRow().getNewValue();
        assertThat(newValue).startsWith("{").endsWith("}");
        assertThat(newValue).contains("\"fullness\":2.0").contains("\"label\":\"标准工艺\"");
    }

    // ══════════════════════════════════════════════════════════════════════
    // 判据 2：没变的不写（不写噪音行；数值表示不同不算变更）
    // ══════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("一个键都没变 ⇒ 零行且不碰 mapper（「保存了但没改」不得变成 11 行噪音）")
    void unchangedKeysWriteNothing() {
        authenticate("u-9", "13800138000");

        int written = service.recordChanges(TENANT, TenantParamAuditService.DOMAIN_CRAFT_CALC,
                TenantParamAuditService.OPERATION_PUT, OP,
                Map.of("hem_margin", new BigDecimal("0.3")),
                Map.of("hem_margin", new BigDecimal("0.3")));

        assertThat(written).isZero();
        verify(mapper, never()).insert(any(TenantParamAudit.class));
    }

    @Test
    @DisplayName("0.30 与 0.3 是同一个值（NUMERIC 列回读 vs 校验后的 BigDecimal）⇒ 不算变更")
    void numericRepresentationDifferenceIsNotAChange() {
        authenticate("u-9", "13800138000");

        int written = service.recordChanges(TENANT, TenantParamAuditService.DOMAIN_CRAFT_CALC,
                TenantParamAuditService.OPERATION_PUT, OP,
                Map.of("hem_margin", new BigDecimal("0.30")),
                Map.of("hem_margin", new BigDecimal("0.3")));

        assertThat(written).isZero();
        verify(mapper, never()).insert(any(TenantParamAudit.class));
    }

    // ══════════════════════════════════════════════════════════════════════
    // 判据 3：身份 —— 取不到就如实记 unknown + 原因（不编用户）
    // ══════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("无认证上下文 ⇒ actor_source=unknown + 原因，actor_id/actor_name 为空（**不编用户**）")
    void unauthenticatedCallRecordsUnknownWithReason() {
        SecurityContextHolder.clearContext();

        service.recordChanges(TENANT, TenantParamAuditService.DOMAIN_CRAFT_CALC,
                TenantParamAuditService.OPERATION_PUT, OP,
                Map.of(), Map.of("hem_margin", new BigDecimal("0.25")));

        TenantParamAudit row = onlyRow();
        assertThat(row.getActorSource()).isEqualTo(TenantParamAuditService.SOURCE_UNKNOWN);
        assertThat(row.getActorUnknownReason())
                .isEqualTo(TenantParamAuditService.UNKNOWN_NO_AUTH_CONTEXT);
        assertThat(row.getActorId()).isNull();
        assertThat(row.getActorName()).isNull();
    }

    @Test
    @DisplayName("身份解析与 StockLedgerService.resolveOperator **同源**（两套解析不许漂）")
    void actorSourceStaysHomologousWithStockLedgerOperator() {
        authenticate("u-9", "13800138000");
        // 有上下文时先取一次既有解析器的结论（清空之后它必然变成 `system`，不能那时再比）
        String operatorWhileAuthenticated = StockLedgerService.resolveOperator();
        assertThat(operatorWhileAuthenticated).isEqualTo("13800138000");
        service.recordChanges(TENANT, TenantParamAuditService.DOMAIN_CRAFT_CALC,
                TenantParamAuditService.OPERATION_PUT, OP, Map.of("k", "a"), Map.of("k", "b"));

        // 无上下文：既有解析器记 `system`（它是**库存账**的操作人兜底），
        // 本表必须记「未知 + 原因」—— 借用 `system` 会把「不知道谁改的」伪装成一个归属。
        SecurityContextHolder.clearContext();
        assertThat(StockLedgerService.resolveOperator()).isEqualTo(StockLedgerService.OPERATOR_SYSTEM);
        service.recordChanges(TENANT, TenantParamAuditService.DOMAIN_CRAFT_CALC,
                TenantParamAuditService.OPERATION_PUT, OP, Map.of("k", "a"), Map.of("k", "b"));

        ArgumentCaptor<TenantParamAudit> captor = ArgumentCaptor.forClass(TenantParamAudit.class);
        verify(mapper, times(2)).insert(captor.capture());
        List<TenantParamAudit> rows = captor.getAllValues();
        // 同源：有身份时本表记的名字 = 既有解析器的结论
        assertThat(rows.get(0).getActorName()).isEqualTo(operatorWhileAuthenticated);
        TenantParamAudit row = rows.get(1);
        assertThat(row.getActorName()).isNull();
        assertThat(row.getActorName()).isNotEqualTo(StockLedgerService.OPERATOR_SYSTEM);
        assertThat(row.getActorSource()).isEqualTo(TenantParamAuditService.SOURCE_UNKNOWN);
        assertThat(row.getActorUnknownReason()).isNotBlank();
    }

    // ══════════════════════════════════════════════════════════════════════
    // 判据 4：口径 B —— 写失败不抛（配置照常保存），但**必须可观测**
    // ══════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("审计写失败 ⇒ **不抛**（调用方拿不到异常）+ 指标计数 + PARAM_AUDIT_WRITE_FAILED 日志")
    void auditWriteFailureIsSwallowedButObservable() {
        authenticate("u-9", "13800138000");
        when(mapper.insert(any(TenantParamAudit.class)))
                .thenThrow(new org.springframework.dao.DataAccessResourceFailureException("db down"));

        ch.qos.logback.classic.Logger auditLogger = (ch.qos.logback.classic.Logger)
                org.slf4j.LoggerFactory.getLogger(TenantParamAuditService.class);
        ch.qos.logback.core.read.ListAppender<ch.qos.logback.classic.spi.ILoggingEvent> appender =
                new ch.qos.logback.core.read.ListAppender<>();
        appender.start();
        auditLogger.addAppender(appender);
        int written;
        try {
            // 🔴 本行就是判据：审计腿抛异常时**不得**向上冒泡（否则配置写入会跟着失败）
            written = service.recordChanges(TENANT, TenantParamAuditService.DOMAIN_CRAFT_CALC,
                    TenantParamAuditService.OPERATION_PUT, OP,
                    Map.of("hem_margin", new BigDecimal("0.3")),
                    Map.of("hem_margin", new BigDecimal("0.25")));
        } finally {
            auditLogger.detachAppender(appender);
        }

        assertThat(written).isZero();
        // 可观测面 ①：计数（可画线/告警）
        assertThat(meters.get(TenantParamAuditService.WRITE_FAILED_METRIC)
                .tag("param_domain", TenantParamAuditService.DOMAIN_CRAFT_CALC)
                .counter().count()).isEqualTo(1.0d);
        // 可观测面 ②：一条可 grep 的结构化 ERROR（含对账四元组与异常本身）
        assertThat(appender.list).anySatisfy(event -> {
            assertThat(event.getLevel()).isEqualTo(ch.qos.logback.classic.Level.ERROR);
            assertThat(event.getFormattedMessage())
                    .contains("PARAM_AUDIT_WRITE_FAILED")
                    .contains("operationId=" + OP)
                    .contains("待写行数=1")
                    .contains("已写行数=0");
            assertThat(event.getThrowableProxy()).isNotNull();
        });
    }

    @Test
    @DisplayName("部分落库（第 2 行失败）⇒ 日志如实报「已写行数」，不把部分成功说成整体成功")
    void partialWriteIsReportedHonestly() {
        authenticate("u-9", "13800138000");
        when(mapper.insert(any(TenantParamAudit.class)))
                .thenReturn(1)
                .thenThrow(new org.springframework.dao.DataAccessResourceFailureException("db down"));
        ch.qos.logback.classic.Logger auditLogger = (ch.qos.logback.classic.Logger)
                org.slf4j.LoggerFactory.getLogger(TenantParamAuditService.class);
        ch.qos.logback.core.read.ListAppender<ch.qos.logback.classic.spi.ILoggingEvent> appender =
                new ch.qos.logback.core.read.ListAppender<>();
        appender.start();
        auditLogger.addAppender(appender);
        try {
            Map<String, Object> before = new LinkedHashMap<>();
            Map<String, Object> after = new LinkedHashMap<>();
            before.put("hem_margin", new BigDecimal("0.3"));
            after.put("hem_margin", new BigDecimal("0.3"));   // 未变
            before.put("margin_single", new BigDecimal("0.2"));
            after.put("margin_single", new BigDecimal("0.25")); // 变了
            before.put("margin_multi", new BigDecimal("0.3"));
            after.put("margin_multi", new BigDecimal("0.4"));  // 变了
            service.recordChanges(TENANT, TenantParamAuditService.DOMAIN_CRAFT_CALC,
                    TenantParamAuditService.OPERATION_PUT, OP, before, after);
        } finally {
            auditLogger.detachAppender(appender);
        }

        assertThat(appender.list).anySatisfy(event -> assertThat(event.getFormattedMessage())
                .contains("PARAM_AUDIT_WRITE_FAILED")
                .contains("待写行数=2")
                .contains("已写行数=1"));
    }

    // ══════════════════════════════════════════════════════════════════════
    // 工装
    // ══════════════════════════════════════════════════════════════════════

    private static void authenticate(String userId, String username) {
        SecurityUser user = new SecurityUser(userId, TENANT, username, List.of("admin"), List.of());
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(user, null, user.getAuthorities()));
    }

    private TenantParamAudit onlyRow() {
        ArgumentCaptor<TenantParamAudit> captor = ArgumentCaptor.forClass(TenantParamAudit.class);
        verify(mapper, times(1)).insert(captor.capture());
        return captor.getValue();
    }
}
