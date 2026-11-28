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

    @Test
    @DisplayName("客户新消息 ⇒ 预算窗口重置（used=0 / window_start=NOW()），used<5 硬上限不许放宽")
    void resetWindowOnInboundMessage() throws Exception {
        Method m = KfSendBudgetMapper.class.getMethod("resetWindow", String.class, Long.class);
        String sql = String.join(" ", m.getAnnotation(Insert.class).value());
        assertThat(sql).contains("ON CONFLICT (session_id) DO UPDATE")
                .contains("used = 0")
                .contains("window_start = NOW()");
        assertThat(m.getAnnotation(InterceptorIgnore.class).tenantLine()).isEqualTo("true");

        // 重置窗口 ≠ 放宽上限：每条客户消息仍然最多 5 条
        String tryConsumeSql = String.join(" ", KfSendBudgetMapper.class
                .getMethod("tryConsume", String.class, Long.class).getAnnotation(Insert.class).value());
        assertThat(tryConsumeSql).contains("kf_send_budget.used < 5");
    }
}
