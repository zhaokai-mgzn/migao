package com.migao.admin.mapper;

import com.migao.admin.entity.AfterSalesTicket;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;

import java.time.OffsetDateTime;

/**
 * 售后工单 Mapper 接口
 */
@Mapper
public interface AfterSalesTicketMapper extends BaseMapper<AfterSalesTicket> {


    /**
     * 「**超时工单**」的**唯一口径**（issue #5792）：`status ∈ (pending, processing)` 且
     * `deadline` 非空且已过 `now`。
     *
     * <p>为什么收敛成一处：同一个数字出现在**三个**读面 —— 经营简报快照（`overdue_tickets`）、
     * 经营看板（「超时工单」卡）、以及工单列表的「只看超时」筛选。三处各写一份 wrapper 必然漂移，
     * 而判据只能钉住其中一份 ⇒ 用户会看到「卡片说 3 条，点进去列表 5 条」。</p>
     */
    static void applyOverdue(LambdaQueryWrapper<AfterSalesTicket> wrapper, OffsetDateTime now) {
        wrapper.in(AfterSalesTicket::getStatus, "pending", "processing")
                .isNotNull(AfterSalesTicket::getDeadline)
                .lt(AfterSalesTicket::getDeadline, now);
    }

    /** 超时工单数（口径 = {@link #applyOverdue}，与列表筛选同源） */
    default long selectOverdueCount(Long tenantId, OffsetDateTime now) {
        LambdaQueryWrapper<AfterSalesTicket> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(AfterSalesTicket::getTenantId, tenantId);
        applyOverdue(wrapper, now);
        return selectCount(wrapper);
    }
}
