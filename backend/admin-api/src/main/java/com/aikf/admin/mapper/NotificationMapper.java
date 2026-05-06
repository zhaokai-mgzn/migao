package com.aikf.admin.mapper;

import com.aikf.admin.entity.Notification;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

/**
 * 通知记录 Mapper 接口
 */
@Mapper
public interface NotificationMapper extends BaseMapper<Notification> {

    /**
     * 分页查询指定接收人的通知
     */
    @Select("<script>" +
            "SELECT * FROM notifications WHERE tenant_id = #{tenantId} AND recipient_id = #{recipientId}" +
            "<if test='status != null'> AND status = #{status}</if>" +
            "<if test='channel != null'> AND channel = #{channel}</if>" +
            " ORDER BY created_at DESC" +
            "</script>")
    IPage<Notification> selectByRecipientId(@Param("tenantId") Long tenantId,
                                            @Param("recipientId") String recipientId,
                                            @Param("status") String status,
                                            @Param("channel") String channel,
                                            IPage<Notification> page);

    /**
     * 统计未读通知数
     */
    @Select("SELECT COUNT(*) FROM notifications WHERE tenant_id = #{tenantId} AND recipient_id = #{recipientId} AND status != 'read'")
    Long countUnread(@Param("tenantId") Long tenantId,
                     @Param("recipientId") String recipientId);
}
