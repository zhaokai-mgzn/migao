package com.migao.admin.mapper;

import com.migao.admin.entity.UserMemory;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/**
 * 用户记忆 Mapper 接口
 */
@Mapper
public interface UserMemoryMapper extends BaseMapper<UserMemory> {

    /** 查询用户的高重要性记忆（用于注入 System Prompt） */
    @Select("SELECT * FROM user_memories WHERE tenant_id = #{tenantId} AND user_id = #{userId} AND importance >= #{minImportance} ORDER BY importance DESC")
    List<UserMemory> selectImportantMemories(
        @Param("tenantId") Long tenantId,
        @Param("userId") String userId,
        @Param("minImportance") Float minImportance
    );

    /** 按 key 查找记忆（用于 upsert 去重） */
    @Select("SELECT * FROM user_memories WHERE tenant_id = #{tenantId} AND user_id = #{userId} AND key = #{key}")
    UserMemory selectByKey(
        @Param("tenantId") Long tenantId,
        @Param("userId") String userId,
        @Param("key") String key
    );
}
