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
     * 客户来了**新消息** ⇒ 预算窗口重置（`used=0` / `window_start=NOW()`；issue #9302）。
     *
     * <p>微信侧规则（`docs/wechat-store-and-kefu-research.md`）：「客户**主动发送消息**后的 48 小时内，
     * 企业最多发 **5 条**；**若用户继续发送消息，企业可再次下发**」⇒ 窗口起点是**客户最后一条消息**，
     * 不是「会话建好那一刻」。旧实现只在窗口过期 48h 时重置 ⇒ 整个会话总共 5 条，聊到第 6 句 AI
     * 就再也发不出去，与「大部分客服工作由智能客服完成」的裁定（2026-11-28）冲突。</p>
     *
     * <p><b>硬上限不动</b>：仍是「每条客户消息 ≤5 条」（{@link #tryConsume} 的 `used < 5` 与
     * `ck_kf_send_budget_used` 护栏都保留）。**只由入站新消息触发**，重复消息（`msgid` 幂等）不得重置 ——
     * 否则重放能给同一条消息白送 5 条额度。</p>
     */
    @InterceptorIgnore(tenantLine = "true")
    @Insert("INSERT INTO kf_send_budget (session_id, tenant_id, window_start, used) "
            + "VALUES (#{sessionId}, #{tenantId}, NOW(), 0) "
            + "ON CONFLICT (session_id) DO UPDATE SET "
            + "used = 0, window_start = NOW(), updated_at = NOW()")
    int resetWindow(@Param("sessionId") String sessionId, @Param("tenantId") Long tenantId);

    /**
     * 只读：当前窗口内已用条数（窗口已过 48h 或没有预算行 ⇒ 0）。
     * 工作台展示「5 条/48h 余量」用（issue #9198）；**不扣减**，扣减只在 {@link #tryConsume}。
     */
    @Select("SELECT CASE WHEN window_start > NOW() - INTERVAL '48 hours' THEN used ELSE 0 END "
            + "FROM kf_send_budget WHERE session_id = #{sessionId}")
    Integer selectUsedInWindow(@Param("sessionId") String sessionId);
}
