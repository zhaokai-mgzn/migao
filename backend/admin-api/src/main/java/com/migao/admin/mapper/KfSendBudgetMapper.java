package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

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

    /**
     * 只读：当前窗口内已用条数（窗口已过 48h 或没有预算行 ⇒ 0）。
     * 工作台展示「5 条/48h 余量」用（issue #9198）；**不扣减**，扣减只在 {@link #tryConsume}。
     */
    @Select("SELECT CASE WHEN window_start > NOW() - INTERVAL '48 hours' THEN used ELSE 0 END "
            + "FROM kf_send_budget WHERE session_id = #{sessionId}")
    Integer selectUsedInWindow(@Param("sessionId") String sessionId);
}
