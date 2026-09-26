package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 企业参数**变更留痕**（V131，issue #5131 = §22 **P6**）。对应表：{@code tenant_param_audit}。
 *
 * <p><b>一行 = 一个参数键的一次变更</b>（谁 / 何时 / 哪个域的哪个键 / 改前 → 改后），
 * 同一次保存写下的多行共享 {@link #operationId}（日志行里也打它 ⇒ 日志 ↔ 账本可对账）。</p>
 *
 * <p><b>只追加</b>：没有任何更新/删除路径（{@code deleted} 列与全库同构，但本表不软删）。</p>
 *
 * <p><b>身份是怎么确定的</b>（{@link #actorSource}，同 {@code worker_report_audits.identity_source} 的口径）：
 * {@code security_context} = 取自 {@code SecurityContext} 的 {@code SecurityUser}；
 * {@code unknown} = 无认证上下文 ⇒ {@link #actorId} / {@link #actorName} 为 {@code null} 且
 * {@link #actorUnknownReason} 必非空（<b>不编用户</b>；DB 侧由 {@code ck_tenant_param_audit_unknown} 钉住）。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("tenant_param_audit")
public class TenantParamAudit {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** 参数域：{@code craft_calc}（算料，当前唯一写面）。 */
    private String paramDomain;

    /** 参数键（如 {@code hem_margin}）—— 键集随算料引擎演进，故不做白名单。 */
    private String paramKey;

    /** 改前值；{@code null} = 该键此前**没有**存储值（本租户当时在用引擎默认值），**不是**「值是空」。 */
    private String oldValue;

    /** 改后值（PUT 是全量替换 ⇒ 恒非 null）。 */
    private String newValue;

    /** 操作者 userId（{@code actor_source='unknown'} 时为 null）。 */
    private String actorId;

    /** 操作者用户名（手机号）；取不到时回落 userId，两者都取不到 ⇒ null。 */
    private String actorName;

    /** 身份来源：{@code security_context} / {@code unknown}（见类注释）。 */
    private String actorSource;

    /** {@code actor_source='unknown'} 时**必填**：为什么归因不了。 */
    private String actorUnknownReason;

    /** 操作形态：{@code put}（当前唯一写面 = 全量替换）。 */
    private String operation;

    /** 一次保存的身份（同一次 PUT 的多行共享）。 */
    private String operationId;

    private OffsetDateTime createdAt;

    private Integer deleted;
}
