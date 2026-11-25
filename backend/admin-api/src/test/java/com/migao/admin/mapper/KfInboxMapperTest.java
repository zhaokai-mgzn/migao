// case_ids: KF-007
package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import org.apache.ibatis.annotations.Insert;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;

import static org.assertj.core.api.Assertions.assertThat;

class KfInboxMapperTest {

    @Test
    @DisplayName("msg_signature 唯一冲突静默忽略，payload 显式转 jsonb")
    void insertIgnore() throws Exception {
        Method m = KfInboxMapper.class.getMethod("insertIgnore",
                String.class, String.class, Long.class, String.class, String.class);
        String sql = String.join(" ", m.getAnnotation(Insert.class).value());
        assertThat(sql).contains("INSERT INTO kf_inbox")
                .contains("ON CONFLICT (msg_signature) DO NOTHING")
                .contains("CAST(#{payload} AS jsonb)");
        assertThat(m.getAnnotation(InterceptorIgnore.class).tenantLine()).isEqualTo("true");
    }
}
