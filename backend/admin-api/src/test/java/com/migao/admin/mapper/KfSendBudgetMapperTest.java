// case_ids: KF-018
package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import org.apache.ibatis.annotations.Insert;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;

import static org.assertj.core.api.Assertions.assertThat;

class KfSendBudgetMapperTest {

    @Test
    @DisplayName("预算原子扣减：48h 重置 + used<5")
    void tryConsume() throws Exception {
        Method m = KfSendBudgetMapper.class.getMethod("tryConsume", String.class, Long.class);
        String sql = String.join(" ", m.getAnnotation(Insert.class).value());
        assertThat(sql).contains("ON CONFLICT (session_id) DO UPDATE")
                .contains("INTERVAL '48 hours'")
                .contains("kf_send_budget.used < 5");
        assertThat(m.getAnnotation(InterceptorIgnore.class).tenantLine()).isEqualTo("true");
    }
}
