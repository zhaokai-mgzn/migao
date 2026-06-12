package com.migao.admin.config;

import com.baomidou.mybatisplus.annotation.DbType;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.PaginationInnerInterceptor;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import net.sf.jsqlparser.expression.Expression;
import net.sf.jsqlparser.expression.LongValue;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.Arrays;
import java.util.List;

/**
 * MyBatis-Plus 配置类
 * 配置多租户拦截器、分页插件等
 */
@Configuration
public class MybatisPlusConfig {

    /**
     * 不需要进行租户过滤的表
     */
    private static final List<String> IGNORE_TENANT_TABLES = Arrays.asList(
            "tenants",
            "tenant_applications"
    );

    /**
     * 配置 MybatisPlusInterceptor
     *
     * @return MybatisPlusInterceptor
     */
    @Bean
    public MybatisPlusInterceptor mybatisPlusInterceptor() {
        MybatisPlusInterceptor interceptor = new MybatisPlusInterceptor();

        // 添加多租户拦截器
        interceptor.addInnerInterceptor(tenantLineInnerInterceptor());

        // 添加分页插件
        interceptor.addInnerInterceptor(paginationInnerInterceptor());

        return interceptor;
    }

    /**
     * 多租户拦截器配置
     *
     * @return TenantLineInnerInterceptor
     */
    @Bean
    public TenantLineInnerInterceptor tenantLineInnerInterceptor() {
        return new TenantLineInnerInterceptor(new TenantLineHandler() {
            @Override
            public Expression getTenantId() {
                Long tenantId = TenantContext.getTenantId();
                if (tenantId == null) {
                    throw new RuntimeException("Tenant context not initialized - possible unauthenticated access");
                }
                return new LongValue(tenantId);
            }

            @Override
            public String getTenantIdColumn() {
                return "tenant_id";
            }

            @Override
            public boolean ignoreTable(String tableName) {
                // 忽略租户表本身，不进行租户过滤
                return IGNORE_TENANT_TABLES.contains(tableName.toLowerCase());
            }
        });
    }

    /**
     * 分页插件配置
     *
     * @return PaginationInnerInterceptor
     */
    @Bean
    public PaginationInnerInterceptor paginationInnerInterceptor() {
        PaginationInnerInterceptor paginationInterceptor = new PaginationInnerInterceptor();
        // 数据库类型
        paginationInterceptor.setDbType(DbType.POSTGRE_SQL);
        // 设置请求的页面大于最大页后操作，true调回到首页，false继续请求，默认false
        paginationInterceptor.setOverflow(false);
        // 设置最大单页限制数量，默认500条，-1不受限制
        paginationInterceptor.setMaxLimit(500L);
        return paginationInterceptor;
    }
}
