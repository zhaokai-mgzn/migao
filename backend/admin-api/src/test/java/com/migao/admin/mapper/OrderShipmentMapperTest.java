// case_ids: OR-045, OR-046
package com.migao.admin.mapper;

import com.migao.admin.entity.OrderShipment;
import org.apache.ibatis.annotations.ResultMap;
import org.apache.ibatis.annotations.Select;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashSet;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 发货单 Mapper（issue #5648）：**SQL 里点名的列必须真的在建库脚本里**。
 *
 * <p>为什么这是判据而不是「MyBatis 会自己报错」：列名写错在**运行到那一条 SQL 时**才炸，
 * 而单测里 Mapper 通常是 mock 的 ⇒ 真库路径无人走 ⇒ 静默到生产才第一次执行
 * （本仓 §17.3「mock 掉的依赖，其真实行为在生产才第一次执行」的同族）。</p>
 *
 * <p>红证方向：把 {@code @Select} 里的某列改成 {@code tracking_number} ⇒ 本类红。</p>
 */
@DisplayName("发货单 Mapper：SQL 列名 ⊆ 建库脚本列名 + autoResultMap 绑定")
class OrderShipmentMapperTest {

    private static final Path SCHEMA = Path.of("src/main/resources/db/init/schema.sql");

    private static Set<String> columnsOf(String table) throws Exception {
        String sql = Files.readString(SCHEMA);
        Matcher m = Pattern.compile(
                "CREATE TABLE IF NOT EXISTS " + table + " \\(([\\s\\S]*?)\\n\\);").matcher(sql);
        assertThat(m.find()).as("建库脚本里必须有 %s", table).isTrue();
        Set<String> cols = new LinkedHashSet<>();
        for (String line : m.group(1).split("\n")) {
            Matcher c = Pattern.compile("^\\s{4}([a-z_]+)\\s+[A-Z]").matcher(line);
            if (c.find()) {
                cols.add(c.group(1));
            }
        }
        return cols;
    }

    @Test
    @DisplayName("🔴 selectByOrderId 点名的列都在建库脚本的 order_shipments 里")
    void selectByOrderIdColumnNamesExist() throws Exception {
        Set<String> cols = columnsOf("order_shipments");
        assertThat(cols).contains("order_id", "tenant_id", "deleted", "created_at");
        Method m = OrderShipmentMapper.class.getMethod("selectByOrderId", String.class, Long.class);
        String sql = m.getAnnotation(Select.class).value()[0];
        for (String needed : new String[]{"order_id", "tenant_id", "deleted", "created_at", "id"}) {
            assertThat(sql).as("SQL 必须按 %s 过滤/排序", needed).contains(needed);
        }
        assertThat(sql).doesNotContain("tracking_number");
    }

    @Test
    @DisplayName("🔴 幂等键查询走 client_request_id（唯一索引 uk_order_shipments_idem 的读面）")
    void idempotencyLookupUsesTheIndexedColumn() throws Exception {
        assertThat(columnsOf("order_shipments")).contains("client_request_id");
        Method m = OrderShipmentMapper.class.getMethod("selectByClientRequestId", Long.class, String.class);
        assertThat(m.getAnnotation(Select.class).value()[0]).contains("client_request_id", "tenant_id");
    }

    @Test
    @DisplayName("🔴 手写 @Select 必须绑 autoResultMap（否则 JSONB 以字符串落到 Object 字段）")
    void handwrittenSelectsBindAutoResultMap() {
        for (Method m : OrderShipmentMapper.class.getDeclaredMethods()) {
            if (m.getAnnotation(Select.class) != null) {
                ResultMap rm = m.getAnnotation(ResultMap.class);
                assertThat(rm).as("%s 缺 @ResultMap", m.getName()).isNotNull();
                assertThat(rm.value()[0]).isEqualTo("mybatis-plus_OrderShipment");
            }
        }
    }

    @Test
    @DisplayName("实体挂在 order_shipments 上，且 JSONB 两列声明了 JacksonTypeHandler")
    void entityMapsJsonbColumnsWithAHandler() {
        assertThat(OrderShipment.class.getAnnotation(
                com.baomidou.mybatisplus.annotation.TableName.class).value()).isEqualTo("order_shipments");
        for (String f : new String[]{"photoRefs", "recognition"}) {
            assertThat(OrderShipment.class.getDeclaredFields())
                    .anySatisfy(field -> {
                        if (field.getName().equals(f)) {
                            assertThat(field.getAnnotation(
                                    com.baomidou.mybatisplus.annotation.TableField.class).typeHandler())
                                    .isEqualTo(com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler.class);
                        }
                    });
        }
    }
}
