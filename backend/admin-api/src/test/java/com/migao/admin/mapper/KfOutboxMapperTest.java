// case_ids: KF-017
package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import org.apache.ibatis.annotations.Select;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;

import static org.assertj.core.api.Assertions.assertThat;

class KfOutboxMapperTest {

    @Test
    @DisplayName("claim 用 SKIP LOCKED，parts 显式转 text")
    void claimDue() throws Exception {
        Method m = KfOutboxMapper.class.getMethod("claimDue",
                java.time.OffsetDateTime.class, int.class, String.class);
        String sql = String.join(" ", m.getAnnotation(Select.class).value());
        assertThat(sql).contains("FOR UPDATE SKIP LOCKED")
                .contains("CAST(o.parts AS text)");
        assertThat(m.getAnnotation(InterceptorIgnore.class).tenantLine()).isEqualTo("true");
    }
}
