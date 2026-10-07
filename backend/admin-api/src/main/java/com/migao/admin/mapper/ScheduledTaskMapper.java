package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ScheduledTask;
import org.apache.ibatis.annotations.Mapper;

import java.time.OffsetDateTime;
import java.util.List;

/**
 * 定时任务（issue #6486 包 1）。对应表：{@code scheduled_tasks}。
 *
 * <p>查询口径**只写一处**（与 {@code WorkerPageConfigMapper#selectActiveByTenant} 同款理由）：
 * 扫描器与商家读面共用这里的 where 条件 —— 各写一遍迟早一处漏 {@code deleted = 0}
 * （软删行被当成生效待办 = 静默投递一条已取消的提醒）。</p>
 */
@Mapper
public interface ScheduledTaskMapper extends BaseMapper<ScheduledTask> {

    /**
     * 本租户**到期且待投递**的待办（扫描器主查询）。
     *
     * <p>口径 = {@code status='pending'} + {@code deleted=0} + {@code fire_at <= now}，
     * 按 {@code fire_at} 升序（= 紧急度排序：越早到期越先投），取前 {@code limit} 条。</p>
     *
     * <p>🔴 <b>必须有界</b>：一次扫描不许把全租户的积压待办拉进内存。超出的部分**不丢** ——
     * 下一轮（`fired` 后剩下的仍是 `pending`）继续投，只是延后。</p>
     */
    default List<ScheduledTask> selectDueByTenant(Long tenantId, OffsetDateTime now, int limit) {
        return selectList(new LambdaQueryWrapper<ScheduledTask>()
                .eq(ScheduledTask::getTenantId, tenantId)
                .eq(ScheduledTask::getStatus, ScheduledTask.STATUS_PENDING)
                .eq(ScheduledTask::getDeleted, 0)
                .le(ScheduledTask::getFireAt, now)
                .orderByAsc(ScheduledTask::getFireAt)
                .last("LIMIT " + limit));
    }

    /**
     * 本租户的待办列表（读面）。
     *
     * @param status 为 {@code null} 时不按状态过滤（全量）
     */
    default List<ScheduledTask> selectByTenant(Long tenantId, String status, int limit) {
        LambdaQueryWrapper<ScheduledTask> q = new LambdaQueryWrapper<ScheduledTask>()
                .eq(ScheduledTask::getTenantId, tenantId)
                .eq(ScheduledTask::getDeleted, 0);
        if (status != null && !status.isBlank()) {
            q.eq(ScheduledTask::getStatus, status);
        }
        q.orderByAsc(ScheduledTask::getFireAt).last("LIMIT " + limit);
        return selectList(q);
    }

    /**
     * 幂等键命中检查（同租户 + 同 dedup_key + 未删）。命中 ⇒ 调用方**不重复建单**。
     */
    default ScheduledTask selectByDedupKey(Long tenantId, String dedupKey) {
        return selectOne(new LambdaQueryWrapper<ScheduledTask>()
                .eq(ScheduledTask::getTenantId, tenantId)
                .eq(ScheduledTask::getDedupKey, dedupKey)
                .eq(ScheduledTask::getDeleted, 0)
                .last("LIMIT 1"));
    }
}
