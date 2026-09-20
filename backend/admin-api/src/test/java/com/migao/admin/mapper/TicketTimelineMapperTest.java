// case_ids: PG-056
package com.migao.admin.mapper;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static com.migao.admin.mapper.MapperTypeHandlerAssertions.assertJsonbColumnsBound;

/**
 * {@link TicketTimelineMapper} 的 JSONB 映射判据（issue #4865 同族：手写 {@code @Select} 必须绑
 * autoResultMap，否则 {@code ticket_timeline.content} 以 JSON 字符串落到 {@code Object} 字段上 ⇒
 * 售后详情 {@code StatusHistoryItem} 的 {@code instanceof Map} 恒假 ⇒ 状态流转历史**静默丢字段**）。
 *
 * <p>判据本体在 {@link MapperTypeHandlerAssertions}（单一出处）；本类只钉**这个** mapper。
 * 红证：把 {@code TicketTimelineMapper.selectByTicketId} 的 {@code @ResultMap} 去掉 ⇒ 本类必红。</p>
 */
@DisplayName("#4865 同族守卫：TicketTimelineMapper 的 content 必须经 JacksonTypeHandler")
class TicketTimelineMapperTest {

    @Test
    @DisplayName("content 必须在真实 ResultMap 上挂 JacksonTypeHandler")
    void jsonbColumnBindsJacksonTypeHandler() {
        assertJsonbColumnsBound(TicketTimelineMapper.class);
    }
}
