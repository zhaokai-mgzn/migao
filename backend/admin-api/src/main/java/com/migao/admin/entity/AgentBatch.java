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

    /**
     * 执行者标识 = <b>实例 + job</b>（{@code <实例>#<pid>/<job uuid>}，迁移 V208 / issue #8285）。
     *
     * <p>它是<b>租约的 fencing token</b>：claim 时写入、回收时置 NULL；终态 CAS 带
     * {@code executor_id} 谓词 ⇒ 心跳超时被回收的<b>僵尸 job</b> 再也不能把批次改写回
     * {@code done}（{@code WHERE status='executing'} 单独一条挡不住「回收后又有人在撤销」这种交错）。</p>
     */
    private String executorId;

    /** 该 executor 最近一次心跳时刻（claim 时写一次、执行中每条明细前刷新；超时/为空 ⇒ 可回收）。 */
    private OffsetDateTime heartbeatAt;
}