package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import com.migao.admin.entity.KfSyncCursor;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.time.OffsetDateTime;
import java.util.List;

@Mapper
public interface KfSyncCursorMapper {

    /** 回调只做「加速触发」：无论回调是否重复，都把 dirty_at 置为现在。 */
    @InterceptorIgnore(tenantLine = "true")
    @Insert("INSERT INTO kf_sync_cursor (tenant_id, open_kfid, dirty_at, updated_at) "
            + "VALUES (#{tenantId}, #{openKfid}, NOW(), NOW()) "
            + "ON CONFLICT (tenant_id, open_kfid) DO UPDATE SET dirty_at = NOW(), updated_at = NOW()")
    int markDirty(@Param("tenantId") Long tenantId, @Param("openKfid") String openKfid);

    /**
     * 多实例抢占：只领取 dirty 且未被领取（或领取已超时）的游标。
     * CTE + FOR UPDATE SKIP LOCKED ⇒ 输家不阻塞、不重复处理。
     */
    @InterceptorIgnore(tenantLine = "true")
    @Select("WITH picked AS ("
            + "SELECT tenant_id, open_kfid FROM kf_sync_cursor "
            + "WHERE dirty_at IS NOT NULL AND (claimed_at IS NULL OR claimed_at < #{staleBefore}) "
            + "ORDER BY dirty_at LIMIT #{limit} FOR UPDATE SKIP LOCKED"
            + ") UPDATE kf_sync_cursor c SET claimed_by = #{claimedBy}, claimed_at = NOW() "
            + "FROM picked p WHERE c.tenant_id = p.tenant_id AND c.open_kfid = p.open_kfid "
            + "RETURNING c.tenant_id, c.open_kfid, c.cursor, c.dirty_at, c.claimed_by, c.claimed_at")
    List<KfSyncCursor> claimDue(@Param("staleBefore") OffsetDateTime staleBefore,
                                @Param("limit") int limit,
                                @Param("claimedBy") String claimedBy);

    /** 整轮 sync 成功 ⇒ 推进 cursor + 清 dirty + 释放 claim。 */
    @InterceptorIgnore(tenantLine = "true")
    @Update("UPDATE kf_sync_cursor SET cursor = #{cursor}, dirty_at = NULL, claimed_by = NULL, "
            + "claimed_at = NULL, last_success_at = NOW(), updated_at = NOW() "
            + "WHERE tenant_id = #{tenantId} AND open_kfid = #{openKfid}")
    int clearDirty(@Param("tenantId") Long tenantId,
                   @Param("openKfid") String openKfid,
                   @Param("cursor") String cursor);

    /** 失败/跳过 ⇒ 只释放 claim，dirty 保留给下一轮重试。 */
    @InterceptorIgnore(tenantLine = "true")
    @Update("UPDATE kf_sync_cursor SET claimed_by = NULL, claimed_at = NULL, updated_at = NOW() "
            + "WHERE tenant_id = #{tenantId} AND open_kfid = #{openKfid} AND claimed_by = #{claimedBy}")
    int releaseClaim(@Param("tenantId") Long tenantId,
                     @Param("openKfid") String openKfid,
                     @Param("claimedBy") String claimedBy);
}
