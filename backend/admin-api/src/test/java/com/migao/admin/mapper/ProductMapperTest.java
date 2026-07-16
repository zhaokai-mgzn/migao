package com.migao.admin.mapper;

import com.migao.admin.entity.Product;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.lang.reflect.Parameter;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * ProductMapper 自定义 SQL 验证测试
 * 验证 @Select/@Update 注解中不包含手写 tenant_id（由 TenantLineInnerInterceptor 自动注入）
 */
@DisplayName("ProductMapper SQL 验证")
class ProductMapperTest {

    @Test
    @DisplayName("findLowStockByColor — SQL 不含手写 tenant_id")
    void findLowStockByColor_noManualTenantId() throws Exception {
        Method method = ProductMapper.class.getMethod(
                "findLowStockByColor", int.class, int.class);

        Select select = method.getAnnotation(Select.class);
        assertThat(select).isNotNull();
        String sql = String.join(" ", select.value());

        // SQL 不应该包含手写的 tenant_id
        assertThat(sql).doesNotContain("tenant_id = #{tenantId}");
        assertThat(sql).doesNotContain("p.tenant_id =");

        // 参数中不应该有 tenantId
        boolean hasTenantIdParam = false;
        for (Parameter param : method.getParameters()) {
            Param p = param.getAnnotation(Param.class);
            if (p != null && "tenantId".equals(p.value())) {
                hasTenantIdParam = true;
            }
        }
        assertThat(hasTenantIdParam).as("should not have tenantId parameter").isFalse();

        // 应该包含 JOIN 条件
        assertThat(sql).contains("JOIN products p ON ps.product_id = p.id");
        assertThat(sql).contains("p.deleted = 0");

        // #1396: 应包含 p.status = 'on_sale' 过滤（排除已下架商品下的 SKU）
        assertThat(sql)
                .as("#1396 findLowStockByColor 应过滤 status='on_sale'，排除已下架商品")
                .contains("p.status = 'on_sale'");

        // #1291: 应使用 <= 而非 < 操作符（与 Dashboard stats 口径一致）
        assertThat(sql)
                .as("low-stock-by-color 应使用 <= 操作符（含边界值，与 Dashboard stats 一致）")
                .contains("ps.stock <= #{threshold}");
        assertThat(sql)
                .as("不应使用 < 操作符（排除边界值 stock=threshold）")
                .doesNotContain("ps.stock < #{threshold}");
    }

    @Test
    @DisplayName("update 方法 — 不含 tenant_id，由拦截器覆盖")
    void updateMethods_noTenantId() {
        // increaseSales 和 decreaseSales 方法不需要 tenantId 参数
        // 它们只操作 productId + quantity/amount，tenant 隔离由拦截器保证
        Method[] methods = ProductMapper.class.getDeclaredMethods();
        for (Method method : methods) {
            if (method.getName().equals("increaseSales") || method.getName().equals("decreaseSales")) {
                for (Parameter param : method.getParameters()) {
                    Param p = param.getAnnotation(Param.class);
                    assertThat(p == null || !"tenantId".equals(p.value()))
                            .as(method.getName() + " should not have tenantId parameter")
                            .isTrue();
                }
            }
        }
    }

    @Test
    @DisplayName("#1396 countLowStockSkus — SQL 含 on_sale + deleted 过滤，含显式 tenantId")
    void countLowStockSkus_onSaleAndDeletedFilter() throws Exception {
        Method method = ProductMapper.class.getMethod(
                "countLowStockSkus", Long.class, int.class);

        Select select = method.getAnnotation(Select.class);
        assertThat(select).isNotNull();
        String sql = String.join(" ", select.value());

        // JOIN products 过滤已删除 + 已下架
        assertThat(sql).contains("JOIN products p ON ps.product_id = p.id");
        assertThat(sql)
                .as("应过滤 p.deleted = 0 排除已删除商品")
                .contains("p.deleted = 0");
        assertThat(sql)
                .as("应过滤 p.status = 'on_sale' 排除已下架商品")
                .contains("p.status = 'on_sale'");

        // 显式 tenantId 参数（不走拦截器，直接传参）
        assertThat(sql)
                .as("应包含显式 tenantId（SQL 直接使用 #{tenantId}，不走拦截器）")
                .contains("ps.tenant_id = #{tenantId}");

        // 阈值过滤
        assertThat(sql)
                .as("应使用 ps.stock <= #{threshold} 操作符")
                .contains("ps.stock <= #{threshold}");
        assertThat(sql)
                .as("应包含 ps.stock >= 0 确保非负库存")
                .contains("ps.stock >= 0");

        // 验证参数
        Parameter[] params = method.getParameters();
        assertThat(params).hasSize(2);
        assertThat(params[0].getType()).isEqualTo(Long.class);
        Param tenantParam = params[0].getAnnotation(Param.class);
        assertThat(tenantParam).isNotNull();
        assertThat(tenantParam.value()).isEqualTo("tenantId");

        assertThat(params[1].getType()).isEqualTo(int.class);
        Param thresholdParam = params[1].getAnnotation(Param.class);
        assertThat(thresholdParam).isNotNull();
        assertThat(thresholdParam.value()).isEqualTo("threshold");
    }

    @Test
    @DisplayName("继承 BaseMapper — 标准 CRUD 由拦截器覆盖")
    void extendsBaseMapper_standardCrudCoveredByInterceptor() {
        assertThat(BaseMapper.class.isAssignableFrom(ProductMapper.class))
                .as("ProductMapper should extend BaseMapper<Product>")
                .isTrue();
    }
}
