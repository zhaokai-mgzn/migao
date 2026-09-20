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
 * 报工身份旁路账（V98，issue #4733，**只追加**）：一行 = 一次报工动作。
 *
 * <p>为什么是旁路表而不是给 {@code production_work_logs} 加列：那是**冻结契约 + 红线**
 * （设计 §3.4 / {@code worker-scan-terminal.md} §7 逐字「不改 {@code production_work_logs}」）
 * ⇒ 「由哪个设备会话报的」+「身份来源是 session 还是 body」只能走旁路。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("worker_report_audits")
public class WorkerReportAudit {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String processingOrderId;

    /** 指向 {@code production_work_logs.id}。 */
    private String workLogId;

    private String operationId;

    private String workerId;

    private String workerName;

    /** 由哪个工人 session 报的；{@code null} = 无工人 session。 */
    private String workerSessionId;

    /** {@code server_session}（权威）/ {@code client_body}（显式降级）。 */
    private String identitySource;

    private OffsetDateTime createdAt;

    private Integer deleted;
}
