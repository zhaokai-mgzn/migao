package com.migao.admin.mapper;

// case_ids: FN-001

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.FinanceTransaction;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * FinanceTransactionMapper 验证测试
 * 无自定义 SQL，标准 CRUD 由 TenantLineInnerInterceptor 自动注入租户过滤。
 */
@DisplayName("FinanceTransactionMapper 验证")
class FinanceTransactionMapperTest {

    @Test
    @DisplayName("继承 BaseMapper — 标准 CRUD 由租户拦截器覆盖")
    void extendsBaseMapper_standardCrudCoveredByInterceptor() {
        assertThat(BaseMapper.class.isAssignableFrom(FinanceTransactionMapper.class))
                .as("FinanceTransactionMapper should extend BaseMapper<FinanceTransaction>")
                .isTrue();
    }
}
