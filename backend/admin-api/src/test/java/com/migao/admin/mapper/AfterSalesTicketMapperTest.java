package com.migao.admin.mapper;

// case_ids: UI-072

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.entity.AfterSalesTicket;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.time.OffsetDateTime;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 「超时工单」**唯一口径**的形态判据（issue #5792）。
 *
 * <p>为什么需要它：同一个数字出现在**三个**读面 —— 经营简报快照（`overdue_tickets`）、
 * 经营看板「超时工单」卡、以及工单列表的「只看超时」筛选。若各写一份 wrapper 就会漂移，
 * 用户会看到「卡片说 3 条、点进去列表 5 条」= **计数与下钻不一致**。</p>
 *
 * <p>⚠️ 边界（如实登记）：本测试**不连库**，判的是 wrapper 生成的 SQL 片段
 * （`getSqlSegment()`）而不是查询结果；真库行为由集成/真库用例覆盖。</p>
 */
@DisplayName("AfterSalesTicketMapper 超时工单口径（三读面同源守卫）")
class AfterSalesTicketMapperTest {

    /**
     * LambdaQueryWrapper 需要 MyBatis-Plus 的 lambda 缓存（本体是表元数据），
     * 纯单测里没有 MyBatis 会话 ⇒ 必须先 initTableInfo（本仓既有范式：
     * `KnowledgeCandidateMapperTest`）。少了它，第一次 `getSqlSegment()` 会抛
     * 「can not find lambda cache for this entity」——那是**测试脚手架**问题，不是口径问题。
     */
    @BeforeAll
    static void initTableInfo() {
        MybatisConfiguration configuration = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(configuration, "");
        TableInfoHelper.initTableInfo(assistant, AfterSalesTicket.class);
    }

    @Test
    @DisplayName("🔴 `applyOverdue` = pending/processing ∧ deadline 非空 ∧ deadline 已过（三条缺一即错口径）")
    void applyOverdueShape() {
        LambdaQueryWrapper<AfterSalesTicket> wrapper = new LambdaQueryWrapper<>();
        OffsetDateTime now = OffsetDateTime.parse("2026-09-29T21:00:00+08:00");
        AfterSalesTicketMapper.applyOverdue(wrapper, now);

        String seg = wrapper.getSqlSegment();
        // ① 只算「未结束」的工单（已解决/已拒绝/已关闭的过期 deadline 不算超时）
        assertThat(seg).contains("status IN");
        // ② deadline 为空的工单**不是**超时（没有承诺时限 ⇒ 无从超时）
        assertThat(seg).contains("deadline IS NOT NULL");
        // ③ 以「已过 deadline」为准
        assertThat(seg).contains("deadline <");
    }

    @Test
    @DisplayName("判据不空跑：wrapper 真的带上了参数（`now` 被消费）")
    void applyOverdueBindsNow() {
        LambdaQueryWrapper<AfterSalesTicket> wrapper = new LambdaQueryWrapper<>();
        OffsetDateTime now = OffsetDateTime.parse("2026-09-29T21:00:00+08:00");
        AfterSalesTicketMapper.applyOverdue(wrapper, now);

        // ⚠️ 参数是**惰性生成**的（在拼 SQL 片段时才落到 paramNameValuePairs）
        //    ⇒ 必须先取一次 segment 再断言参数，否则实际读到的是空 map（我第一版就踩了这个）。
        assertThat(wrapper.getSqlSegment()).isNotBlank();
        assertThat(wrapper.getParamNameValuePairs()).containsValue(now);
    }
}
