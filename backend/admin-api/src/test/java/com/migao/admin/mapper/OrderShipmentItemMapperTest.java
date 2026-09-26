// case_ids: OR-046, OR-053
package com.migao.admin.mapper;

import com.migao.admin.entity.OrderShipmentItem;
import org.apache.ibatis.annotations.ResultMap;
import org.apache.ibatis.annotations.Select;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashSet;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 发货明细 Mapper（issue #5648）：**「实发套/件/卷」的唯一真值载体**。
 *
 * <p>本类钉住三件事：① SQL 点名的列真的在建库脚本里；② 实发数量是**十进制**（不是 int ——
 * 截断成整数就是少记米数）；③ 三处「缺值不填 0」的列可空（`set_count` / `roll_count` /
 * `product_name`）—— 把可空列建成 NOT NULL 会让「这一维不适用」被迫写成 0。</p>
 */
@DisplayName("发货明细 Mapper：列名真值 + 十进制实发 + 缺值可空")
class OrderShipmentItemMapperTest {

    private static final Path SCHEMA = Path.of("src/main/resources/db/init/schema.sql");

    private static String tableBody(String table) throws Exception {
        Matcher m = Pattern.compile("CREATE TABLE IF NOT EXISTS " + table + " \\(([\\s\\S]*?)\\n\\);")
                .matcher(Files.readString(SCHEMA));
        assertThat(m.find()).as("建库脚本里必须有 %s", table).isTrue();
        return m.group(1);
    }

    private static Set<String> columnsOf(String table) throws Exception {
        Set<String> cols = new LinkedHashSet<>();
        for (String line : tableBody(table).split("\n")) {
            Matcher c = Pattern.compile("^\\s{4}([a-z_]+)\\s+[A-Z]").matcher(line);
            if (c.find()) {
                cols.add(c.group(1));
            }
        }
        return cols;
    }

    @Test
    @DisplayName("🔴 契约列齐备 + 实发数量是 NUMERIC(10,2)（截断成整数就是少记米数）")
    void contractColumnsAndDecimalQuantity() throws Exception {
        Set<String> cols = columnsOf("order_shipment_items");
        assertThat(cols).contains("id", "tenant_id", "shipment_id", "order_id", "order_item_id",
                "product_name", "shipped_quantity", "unit", "set_count", "roll_count");
        assertThat(tableBody("order_shipment_items"))
                .contains("shipped_quantity NUMERIC(10,2) NOT NULL")
                .contains("unit VARCHAR(16) NOT NULL");
        assertThat(OrderShipmentItem.class.getDeclaredField("shippedQuantity").getType())
                .isEqualTo(BigDecimal.class);
    }

    @Test
    @DisplayName("🔴 缺值不填 0：set_count / roll_count / product_name 必须可空")
    void missingDimensionsAreNullableNotZero() throws Exception {
        String body = tableBody("order_shipment_items");
        assertThat(body).contains("set_count INTEGER,");
        assertThat(body).contains("roll_count INTEGER,");
        assertThat(body).contains("product_name VARCHAR(255),");
        assertThat(body).doesNotContain("set_count INTEGER NOT NULL")
                .doesNotContain("roll_count INTEGER NOT NULL DEFAULT 0");
    }

    @Test
    @DisplayName("🔴 明细挂在发货单上：外键 + ON DELETE CASCADE（删单不留下孤儿明细）")
    void itemsAreCascadedFromTheShipment() throws Exception {
        assertThat(tableBody("order_shipment_items"))
                .contains("shipment_id VARCHAR(36) NOT NULL REFERENCES order_shipments(id) ON DELETE CASCADE");
    }

    @Test
    @DisplayName("🔴 两个读面的列名都在建库脚本里，且都绑 autoResultMap")
    void queryColumnsExistAndBindAutoResultMap() throws Exception {
        Set<String> cols = columnsOf("order_shipment_items");
        for (String name : new String[]{"selectByShipmentId", "selectByOrderId"}) {
            Method m = name.equals("selectByShipmentId")
                    ? OrderShipmentItemMapper.class.getMethod(name, String.class, Long.class)
                    : OrderShipmentItemMapper.class.getMethod(name, String.class, Long.class);
            String sql = m.getAnnotation(Select.class).value()[0];
            for (String needed : new String[]{"shipment_id", "order_id", "tenant_id", "deleted"}) {
                if (sql.contains(needed)) {
                    assertThat(cols).as("SQL 里的 %s 必须在建库脚本里", needed).contains(needed);
                }
            }
            assertThat(sql).contains("tenant_id", "deleted");
            assertThat(m.getAnnotation(ResultMap.class).value()[0])
                    .isEqualTo("mybatis-plus_OrderShipmentItem");
        }
    }

    @Test
    @DisplayName("实体挂在 order_shipment_items 上，且 tenant_id 在映射里（多租户插件会注入该列谓词）")
    void entityIsTenantScoped() throws Exception {
        assertThat(OrderShipmentItem.class.getAnnotation(
                com.baomidou.mybatisplus.annotation.TableName.class).value())
                .isEqualTo("order_shipment_items");
        assertThat(OrderShipmentItem.class.getDeclaredField("tenantId")).isNotNull();
    }
}
