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
 * 工人登录态（V98，issue #4733）：报工身份的**唯一根**。
 *
 * <p>对应表 {@code worker_sessions}。与商家账号彻底分离：本表只服务
 * {@code /api/worker/**}，工人 session **不得**进 {@code /api/admin/**}。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("worker_sessions")
public class WorkerSession {

    /** 会话 id（32 位 UUID 去横线）：前端存本地并以 {@code X-Worker-Session-Id} 回传。 */
    @TableId(type = IdType.INPUT)
    private String id;

    private Long tenantId;

    /** 工人 id（{@code users.id}）。 */
    private String workerId;

    /** 工号快照。 */
    private String workerNo;

    /** 姓名快照（= {@code users.nickname}）。 */
    private String workerName;

    /** 设备标签（PAD-车间-01 之类）。 */
    private String deviceLabel;

    private OffsetDateTime startedAt;

    private OffsetDateTime lastSeenAt;

    /** 闲置过期时刻：每次成功请求顺延（服务端算）。 */
    private OffsetDateTime idleExpiresAt;

    /** 结束时刻；{@code null} = 仍活跃。 */
    private OffsetDateTime endedAt;

    /** logout 主动登出 / idle 闲置超时 / switched 快速切换工人 / revoked 停用撤销。 */
    private String endReason;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;

    private Integer deleted;
}
