package com.aikf.admin.mapper;

import com.aikf.admin.entity.TicketNote;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/**
 * 工单备注 Mapper 接口
 */
@Mapper
public interface TicketNoteMapper extends BaseMapper<TicketNote> {

    /**
     * 根据工单 ID 查询备注列表（按时间正序）
     */
    @Select("SELECT * FROM ticket_notes WHERE ticket_id = #{ticketId} AND tenant_id = #{tenantId} ORDER BY created_at ASC")
    List<TicketNote> selectByTicketId(@Param("ticketId") String ticketId, @Param("tenantId") Long tenantId);
}
