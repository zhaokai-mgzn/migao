package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

@Mapper
public interface KfSendBudgetMapper {

    /**
     * 原子扣减：新会话插 1；已存在且未超 5 条（或窗口已过 48h 重置）则 +1。
     * 返回 0 = 预算耗尽（调用方必须停发，不能“先发再补”）。
     */
    @InterceptorIgnore(tenantLine = "true")
    @Insert("INSERT INTO kf_send_budget (session_id, tenant_id, window_start, used) "
            + "VALUES (#{sessionId}, #{tenantId}, NOW(), 1) "
            + "ON CONFLICT (session_id) DO UPDATE SET "
            + "used = CASE WHEN kf_send_budget.window_start < NOW() - INTERVAL '48 hours' "
            + "THEN 1 ELSE kf_send_budget.used + 1 END, "
            + "window_start = CASE WHEN kf_send_budget.window_start < NOW() - INTERVAL '48 hours' "
            + "THEN NOW() ELSE kf_send_budget.window_start END, "
            + "updated_at = NOW() "
            + "WHERE kf_send_budget.window_start < NOW() - INTERVAL '48 hours' "
            + "OR kf_send_budget.used < 5")
    int tryConsume(@Param("sessionId") String sessionId, @Param("tenantId") Long tenantId);
}
