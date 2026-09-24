package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 批量更新的**逐条明细**（issue #5314 服务端包；表 {@code agent_batch_items}，迁移 V127）。
 *
 * <p><b>{@code old_value} 是撤销的唯一依据，必须持久化</b>（契约原文）——
 * 预览阶段就采集，不能只在内存里：批次执行与撤销之间可能隔很久（甚至跨进程重启）。</p>
 *
 * <p>逐条 {@code status} / {@code error} 是「部分失败逐条报告」的载体：执行与撤销都**逐条**落库，
 * <b>不做整体回滚</b>（回滚会把「哪几条真的改坏了」一起掩盖掉）。</p>
 *
 * <p>{@code tenant_id} 不在契约列举的列里，但**必须有**：本仓 {@code TenantLineInnerInterceptor}
 * 会给每张非忽略表注入 {@code tenant_id} 谓词，缺列即 SQL 报错；同表冗余租户列
 * 也是跨租户隔离的第二道闸（明细不经父批次直查时同样不可见）。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("agent_batch_items")
public class AgentBatchItem {

    @TableId(type = IdType.AUTO)
    private Long id;

    private String batchId;

    private Long tenantId;

    /** 资源 ID（商品 ID）。 */
    private String resourceId;

    /** 字段名（basePrice / status）。 */
    private String field;

    /** 改前值 —— **撤销的唯一依据**。 */
    private String oldValue;

    /** 改后值（执行时写入）。 */
    private String newValue;

    /** pending / success / failed / reverted / revert_failed / skipped。 */
    private String status;

    /** 逐条失败原因（成功时为 null）。 */
    private String error;
}