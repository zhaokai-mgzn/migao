// case_ids: PG-056
package com.migao.admin.mapper;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static com.migao.admin.mapper.MapperTypeHandlerAssertions.assertJsonbColumnsBound;

/**
 * {@link UserMemoryMapper} 的 JSONB 映射判据（issue #4865 同族：手写 {@code @Select} 必须绑
 * autoResultMap，否则 {@code user_memories.related_to} 以 JSON 字符串落到 {@code Object} 字段上）。
 *
 * <p>判据本体在 {@link MapperTypeHandlerAssertions}（单一出处）；本类只钉**这个** mapper（两个方法）。
 * 红证：把任一方法的 {@code @ResultMap} 去掉 ⇒ 本类必红。</p>
 */
@DisplayName("#4865 同族守卫：UserMemoryMapper 的 related_to 必须经 JacksonTypeHandler")
class UserMemoryMapperTest {

    @Test
    @DisplayName("related_to 必须在真实 ResultMap 上挂 JacksonTypeHandler（两个查询方法都要）")
    void jsonbColumnBindsJacksonTypeHandler() {
        assertJsonbColumnsBound(UserMemoryMapper.class);
    }
}
