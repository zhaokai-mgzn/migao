package com.aikf.admin.mapper;

import com.aikf.admin.entity.TicketTimeline;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/**
 * 工单时间线 Mapper 接口
 */
@Mapper
public interface TicketTimelineMapper extends BaseMapper<TicketTimeline> {

    /**
     * 根据工单 ID 查询时间线（按时间正序）
     */
    @Select("SELECT * FROM ticket_timeline WHERE ticket_id = #{ticketId} AND tenant_id = #{tenantId} ORDER BY created_at ASC")
    List<TicketTimeline> selectByTicketId(@Param("ticketId") String ticketId, @Param("tenantId") Long tenantId);
}
