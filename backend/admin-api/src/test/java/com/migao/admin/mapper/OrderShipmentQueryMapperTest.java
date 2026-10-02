// case_ids: OR-056
package com.migao.admin.mapper;

import com.migao.admin.dto.ShipmentListRow;
import org.apache.ibatis.annotations.Select;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashSet;
import java.util.Set;
import java.util.TreeSet;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 发货单**列表**读面（issue #5939）的手写 SQL 契约。
 *
 * <h2>为什么这条 SQL 需要文本判据</h2>
 * <p>它是本单唯一一处手写 SQL（其余走 MyBatis-Plus wrapper），因此也是唯一一处
 * 「租户隔离、软删过滤、上限」都不会被类型系统挡住的地方：</p>
 * <ul>
 *   <li><b>租户维</b>：跨租户读是**数据泄漏**，不是过滤问题 —— 外层与明细聚合子查询都必须限定
 *       {@code tenant_id}；</li>
 *   <li><b>软删维</b>：{@code deleted = 0} 漏在子查询里 ⇒ 软删明细会把「明细行数」撑大
 *       （「单子对、数字错」这种自相矛盾的读数最难发现）；</li>
 *   <li><b>上限</b>：发货单是流水型单据，不做深分页也**不能无界返回**（同 {@code InboundOrderQueryMapper}
 *       的 {@code LIMIT #{limit}} 口径）；</li>
 *   <li><b>列名真值</b>：列名写错只在**运行到那一条 SQL 时**才炸，而单测里 Mapper 通常被 mock
 *       ⇒ 真库路径无人走、静默到生产才第一次执行（{@code OrderShipmentMapperTest} 的同族口径）。</li>
 * </ul>
 *
 * <h2>红证（把实现改坏 ⇒ 本类必红）</h2>
 * <ul>
 *   <li>去掉 {@code s.tenant_id = #{tenantId}} ⇒ {@code sqlIsTenantScoped} 红；</li>
 *   <li>子查询里去掉 {@code deleted = 0} ⇒ 同一条判据红；</li>
 *   <li>去掉 {@code LIMIT #{limit}} ⇒ {@code sqlIsBounded} 红；</li>
 *   <li>别名改成 {@code shipment_no}（不落 camelCase）⇒ {@code aliasesMatchDtoProperties} 红；</li>
 *   <li>把 {@code o.customer_name} 写成 {@code o.customer} ⇒ {@code referencedColumnsExistInSchema} 红。</li>
 * </ul>
 */
@DisplayName("发货单列表 Mapper：租户隔离 / 软删 / 上限 / 关键词 / 别名 ⇄ DTO / 列名真值")
class OrderShipmentQueryMapperTest {

    private static final Path SCHEMA = Path.of("src/main/resources/db/init/schema.sql");

    private static Method listMethod() throws NoSuchMethodException {
        return OrderShipmentQueryMapper.class.getMethod(
                "selectListRows", Long.class, String.class, int.class);
    }

    private static String sql() throws NoSuchMethodException {
        Select select = listMethod().getAnnotation(Select.class);
        assertThat(select).as("selectListRows 必须标 @Select").isNotNull();
        // 空白归一：SQL 是**多行文本块**，断言不该被换行/缩进绑架（否则「格式化一下」就判红）
        return String.join("\n", select.value()).replaceAll("\\s+", " ");
    }

    private static Set<String> columnsOf(String table) throws Exception {
        String ddl = Files.readString(SCHEMA);
        Matcher m = Pattern.compile("CREATE TABLE (?:IF NOT EXISTS )?" + table + " \\(([\\s\\S]*?)\\n\\);")
                .matcher(ddl);
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

    // ══════════════════════════════════════════════════════════════════════════
    // 判据 1：租户隔离（外层 + 明细聚合子查询）
    // ══════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("🔴 外层与明细聚合子查询都必须限定 tenant_id，且都排除软删行")
    void sqlIsTenantScoped() throws Exception {
        String sql = sql();
        assertThat(sql).contains("s.tenant_id = #{tenantId}");
        assertThat(sql).contains("s.deleted = 0");
        // 聚合子查询自己也要限定：漏了 ⇒ 软删/跨租户明细虚增「明细行数」
        Matcher sub = Pattern.compile("LEFT JOIN \\( (.*?) \\) a ON").matcher(sql);
        assertThat(sub.find()).as("SQL 里必须有 order_shipment_items 的聚合子查询").isTrue();
        String subquery = sub.group(1);
        assertThat(subquery).contains("COUNT(*)");
        assertThat(subquery).contains("tenant_id = #{tenantId}");
        assertThat(subquery).contains("deleted = 0");
        assertThat(subquery).contains("GROUP BY shipment_id");
    }

    @Test
    @DisplayName("🔴 客户名取自 orders 的连接：连接条件必须带租户维（不许跨租户取到别人的客户名）")
    void orderJoinIsTenantScoped() throws Exception {
        String sql = sql();
        assertThat(sql).contains("LEFT JOIN orders o ON o.id = s.order_id AND o.tenant_id = s.tenant_id AND o.deleted = 0");
        assertThat(sql).contains("o.customer_name");
    }

    // ══════════════════════════════════════════════════════════════════════════
    // 判据 2：上限与关键词
    // ══════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("必须有 LIMIT（无界返回会把整张发货流水表拉进内存）")
    void sqlIsBounded() throws Exception {
        assertThat(sql()).contains("LIMIT #{limit}");
    }

    @Test
    @DisplayName("关键词按 发货单号 / 订单号 / 客户名 模糊匹配（三列都要有）")
    void sqlSupportsKeyword() throws Exception {
        String sql = sql();
        assertThat(sql).contains("s.shipment_no ILIKE");
        assertThat(sql).contains("s.order_no ILIKE");
        assertThat(sql).contains("o.customer_name ILIKE");
        assertThat(sql).contains("keyword != null and keyword != ''");
    }

    @Test
    @DisplayName("排序：近的在前（shipped_at 优先，未发货退回 packed_at / created_at），同刻用 id 兜稳定序")
    void sqlIsOrderedNewestFirst() throws Exception {
        String sql = sql();
        assertThat(sql).contains("ORDER BY");
        assertThat(sql).contains("COALESCE(s.shipped_at, s.packed_at, s.created_at) DESC");
        assertThat(sql).contains("s.id DESC");
    }

    // ══════════════════════════════════════════════════════════════════════════
    // 判据 3：别名 ⇄ DTO 属性（写错 ⇒ 字段静默为 null）
    // ══════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("🔴 每个 DTO 字段都有同名 SQL 别名（别名写错 ⇒ 字段静默为 null，没有任何东西会红）")
    void aliasesMatchDtoProperties() throws Exception {
        String sql = sql();
        Set<String> missing = new TreeSet<>();
        for (Field f : ShipmentListRow.class.getDeclaredFields()) {
            if (Modifier.isStatic(f.getModifiers())) {
                continue;
            }
            // shippedTotals 由服务层装配（与 readShipment 的 shipped_totals 同源），不由 SQL 给
            if ("shippedTotals".equals(f.getName())) {
                continue;
            }
            if (!sql.contains("AS " + f.getName())) {
                missing.add(f.getName());
            }
        }
        assertThat(missing).as("这些 DTO 字段在 SQL 里没有同名别名").isEmpty();
    }

    @Test
    @DisplayName("别名集合不许比 DTO 多（多出来的列没人消费 = 第二份会漂移的投影）")
    void noExtraAliasesBeyondDto() throws Exception {
        String sql = sql();
        Set<String> aliases = new TreeSet<>();
        Matcher m = Pattern.compile("AS ([a-z][A-Za-z0-9_]*)").matcher(sql);
        while (m.find()) {
            aliases.add(m.group(1));
        }
        Set<String> dto = new TreeSet<>();
        for (Field f : ShipmentListRow.class.getDeclaredFields()) {
            if (!Modifier.isStatic(f.getModifiers()) && !"shippedTotals".equals(f.getName())) {
                dto.add(f.getName());
            }
        }
        assertThat(aliases).isEqualTo(dto);
    }

    // ══════════════════════════════════════════════════════════════════════════
    // 判据 4：SQL 点名的列必须真的在建库脚本里
    // ══════════════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("🔴 SQL 里 `s.` / `o.` 点名的每一列都在建库脚本里（列名写错 = 生产才第一次执行）")
    void referencedColumnsExistInSchema() throws Exception {
        String sql = sql();
        Set<String> shipments = columnsOf("order_shipments");
        Set<String> orders = columnsOf("orders");
        Set<String> items = columnsOf("order_shipment_items");

        Matcher m = Pattern.compile("\\b([so])\\.([a-z_]+)").matcher(sql);
        Set<String> bad = new TreeSet<>();
        Set<String> seen = new TreeSet<>();
        while (m.find()) {
            String alias = m.group(1);
            String col = m.group(2);
            seen.add(alias + "." + col);
            Set<String> owner = "s".equals(alias) ? shipments : orders;
            if (!owner.contains(col)) {
                bad.add(alias + "." + col);
            }
        }
        assertThat(seen).as("这条 SQL 必须真的引用两张表（否则判据本身空转）")
                .contains("s.shipment_no", "s.order_no", "o.customer_name");
        assertThat(bad).as("这些列不在建库脚本里").isEmpty();

        // 明细聚合子查询点名的列同样要对得上（shipment_id / tenant_id / deleted）
        assertThat(items).contains("shipment_id", "tenant_id", "deleted");
        assertThat(sql).contains("GROUP BY shipment_id");
    }
}
