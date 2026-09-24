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
 * 批量更新的**批次**（issue #5314 服务端包；表 {@code agent_batches}，迁移 V127）。
 *
 * <p>为什么必须有自己的表（不复用 {@code audit_logs}）：批量是「一键确认 N 条 = 用户实际没看」的
 * <b>盲签</b>来源，撤销是它的<b>准入前置</b>（见 {@code docs/wiki/agent-write-boundary.md} §五）。
 * 撤销要求逐条可寻址的 {@code old_value}，而审计是**有界 fail-open**（3s 超时即丢行，丢行允许）
 * ⇒ 拿它当撤销依据 = 撤销会静默失去依据。故批次与明细各自落表，逐条留痕。</p>
 *
 * <p>状态机：{@code preview → executing → done | partial → reverted | revert_partial}；
 * <b>不可撤销</b> = 状态非 {@code done}/{@code partial}、或已 {@code reverted}。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("agent_batches")
public class AgentBatch {

    /** 批次 ID（响应里的 {@code batchId}；服务层显式赋值 ⇒ 创建响应立刻可回带）。 */
    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** product_price / product_status（白名单，DB CHECK 同源）。 */
    private String batchType;

    /** preview / executing / done / partial / reverted / revert_partial。 */
    private String status;

    private Integer itemCount;

    private Integer successCount;

    private Integer failCount;

    /** 发起人（认证上下文的 userId —— body 伪造不了）。 */
    private String createdBy;

    /** 落库由 DB 默认值 {@code NOW()} 负责（实体留 null ⇒ INSERT 省略该列）。 */
    private OffsetDateTime createdAt;

    private OffsetDateTime executedAt;

    private OffsetDateTime revertedAt;
}