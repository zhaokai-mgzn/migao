package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import com.migao.admin.entity.KfSessionRemote;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

@Mapper
public interface KfSessionRemoteMapper {

    @InterceptorIgnore(tenantLine = "true")
    @Select("SELECT * FROM kf_session_remote WHERE session_id = #{sessionId} LIMIT 1")
    KfSessionRemote selectBySessionId(@Param("sessionId") String sessionId);

    @InterceptorIgnore(tenantLine = "true")
    @Select("SELECT * FROM kf_session_remote WHERE tenant_id = #{tenantId} AND open_kfid = #{openKfid} "
            + "AND external_userid = #{externalUserid} AND closed_at IS NULL LIMIT 1")
    KfSessionRemote selectCurrent(@Param("tenantId") Long tenantId,
                                  @Param("openKfid") String openKfid,
                                  @Param("externalUserid") String externalUserid);

    /** 同一 (open_kfid, external_userid) 的当前段唯一（部分索引）⇒ 并发建会话只成功一个。 */
    @InterceptorIgnore(tenantLine = "true")
    @Insert("INSERT INTO kf_session_remote (session_id, tenant_id, open_kfid, external_userid, state, epoch) "
            + "VALUES (#{sessionId}, #{tenantId}, #{openKfid}, #{externalUserid}, 0, 1) "
            + "ON CONFLICT (open_kfid, external_userid) WHERE closed_at IS NULL DO NOTHING")
    int insertIgnore(@Param("sessionId") String sessionId,
                     @Param("tenantId") Long tenantId,
                     @Param("openKfid") String openKfid,
                     @Param("externalUserid") String externalUserid);

    @InterceptorIgnore(tenantLine = "true")
    @Update("UPDATE kf_session_remote SET last_msg_at = NOW(), last_sync_at = NOW(), updated_at = NOW() "
            + "WHERE session_id = #{sessionId}")
    int touch(@Param("sessionId") String sessionId);
}
