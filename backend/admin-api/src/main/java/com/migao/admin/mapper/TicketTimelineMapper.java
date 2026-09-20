package com.migao.admin.mapper;

import com.migao.admin.entity.TicketTimeline;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.ResultMap;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/**
 * 工单时间线 Mapper 接口
 *
 * <p>🔴 手写 {@code @Select} 必须显式绑 autoResultMap（口径见 {@code ProcessingOrderMapper} 类注释）：
 * 否则 {@code content}（JSONB）以 JSON 字符串落到 {@code Object} 字段上 ⇒
 * 售后详情 {@code StatusHistoryItem} 的 {@code tl.getContent() instanceof Map} 恒为假
 * ⇒ 状态流转历史**静默丢字段**（不报错，只是空）。</p>
 */
@Mapper
public interface TicketTimelineMapper extends BaseMapper<TicketTimeline> {

    /**
     * 根据工单 ID 查询时间线（按时间正序）
     */
    @ResultMap("mybatis-plus_TicketTimeline")
    @Select("SELECT * FROM ticket_timeline WHERE ticket_id = #{ticketId} AND tenant_id = #{tenantId} ORDER BY created_at ASC")
    List<TicketTimeline> selectByTicketId(@Param("ticketId") String ticketId, @Param("tenantId") Long tenantId);
}
