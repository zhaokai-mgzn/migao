package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

@Mapper
public interface KfSyncCursorMapper {

    /** 回调只做「加速触发」：无论回调是否重复，都把 dirty_at 置为现在。 */
    @InterceptorIgnore(tenantLine = "true")
    @Insert("INSERT INTO kf_sync_cursor (tenant_id, open_kfid, dirty_at, updated_at) "
            + "VALUES (#{tenantId}, #{openKfid}, NOW(), NOW()) "
            + "ON CONFLICT (tenant_id, open_kfid) DO UPDATE SET dirty_at = NOW(), updated_at = NOW()")
    int markDirty(@Param("tenantId") Long tenantId, @Param("openKfid") String openKfid);
}
