// case_ids: DA-001, DA-006, DA-007

package com.migao.admin.mapper;

import net.sf.jsqlparser.parser.CCJSqlParserUtil;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.lang.reflect.Parameter;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * OrderItemMapper 自定义 SQL 验证测试
 * #2886：验证新增聚合查询 SQL（含加工待发货 JOIN / 商品排行 GROUP BY / 上期销量 IN 批量），
 * 且不包含手写 tenant_id（由 TenantLineInnerInterceptor 自动注入）。
 */
@DisplayName("OrderItemMapper SQL 验证")
class OrderItemMapperTest {

    @Test
    @DisplayName("selectProcessingPendingOrdersCount — JOIN 一次统计，无手写 tenant_id")
    void selectProcessingPendingOrdersCount_noManualTenantId() throws Exception {
        Method method = OrderItemMapper.class.getMethod("selectProcessingPendingOrdersCount");
        Select select = method.getAnnotation(Select.class);
        assertThat(select).isNotNull();
        String sql = String.join(" ", select.value());

        assertThat(sql).doesNotContainPattern("(?i)tenant_id");
        assertThat(sql).contains("COUNT(DISTINCT oi.order_id)");
        assertThat(sql).contains("JOIN orders o ON oi.order_id = o.id");
        assertThat(sql).contains("o.status IN ('confirmed','producing')");
        assertThat(sql).contains("oi.processing_info IS NOT NULL");
        assertThat(sql).contains("oi.deleted = 0");
    }

    @Test
    @DisplayName("selectProductRanking — SQL 聚合 + TOP-N 排序，无手写 tenant_id")
    void selectProductRanking_sqlAggregation() throws Exception {
        Method method = OrderItemMapper.class.getMethod(
                "selectProductRanking", java.time.OffsetDateTime.class, int.class);
        Select select = method.getAnnotation(Select.class);
        assertThat(select).isNotNull();
        String sql = String.join(" ", select.value());

        assertThat(sql).doesNotContainPattern("(?i)tenant_id");
        // GROUP BY product_id 一次聚合 + LIMIT 截断 topN（JOIN orders 后列名带 oi. 前缀限定，防与 orders 同名列冲突）
        assertThat(sql).startsWith("SELECT oi.product_id");
        assertThat(sql).contains("FROM order_items oi");
        assertThat(sql).contains("GROUP BY oi.product_id");
        assertThat(sql).contains("ORDER BY qty DESC");
        assertThat(sql).contains("LIMIT #{limit}");
        assertThat(sql).contains("COALESCE(SUM(oi.quantity), 0)");
        // FLOOR(subtotal) 与旧逻辑逐行 longValue() 截断语义一致
        assertThat(sql).contains("SUM(FLOOR(oi.subtotal))");
        assertThat(sql).contains("MAX(oi.product_name)");
        // #2984：排行只统计有效订单（已付款/在履行中），排除 pending(未付款)/cancelled(已取消)
        // JOIN orders 过滤状态（租户条件仍由 TenantLineInnerInterceptor 注入，与线上一致）
        assertThat(sql).contains("JOIN orders o ON oi.order_id = o.id");
        assertThat(sql).contains("o.status IN ('confirmed','producing','shipped','completed')");
        assertThat(sql).contains("o.deleted = 0");
        assertThat(sql).doesNotContain("'pending'");
        assertThat(sql).doesNotContain("'cancelled'");
        // #2989：排除 product_id 为 NULL/空 的幽灵明细（生产实证 276 条脏数据被 GROUP BY 聚合成不存在商品行）
        // #2994：`!=` 替代 `<>`（后者在 XML 上下文中非法；本方法为普通注解虽然安全，但保持两处口径一致）
        assertThat(sql).contains("oi.product_id IS NOT NULL");
        assertThat(sql).contains("oi.product_id != ''");
    }

    @Test
    @DisplayName("selectPrevPeriodQuantities — IN 批量一次，无手写 tenant_id")
    void selectPrevPeriodQuantities_inBatch() throws Exception {
        Method method = OrderItemMapper.class.getMethod(
                "selectPrevPeriodQuantities", java.util.List.class,
                java.time.OffsetDateTime.class, java.time.OffsetDateTime.class);
        Select select = method.getAnnotation(Select.class);
        assertThat(select).isNotNull();
        String sql = String.join(" ", select.value());

        assertThat(sql).doesNotContainPattern("(?i)tenant_id");
        assertThat(sql).contains("<script>");
        assertThat(sql).contains("foreach");
        assertThat(sql).contains("product_id IN");
        assertThat(sql).contains("GROUP BY oi.product_id");
        // #2984：上期销量与本期同口径 —— JOIN orders 过滤有效状态，排除 pending/cancelled
        assertThat(sql).contains("JOIN orders o ON oi.order_id = o.id");
        assertThat(sql).contains("o.status IN ('confirmed','producing','shipped','completed')");
        assertThat(sql).contains("o.deleted = 0");
        assertThat(sql).doesNotContain("'pending'");
        assertThat(sql).doesNotContain("'cancelled'");
        // #2989：上期口径与本期一致 —— 排除 product_id 为 NULL/空 的幽灵明细
        assertThat(sql).contains("oi.product_id IS NOT NULL");
        assertThat(sql).contains("oi.product_id != ''");
        // #2994 回归：@Select(<script>) 内容是 XML，必须良构（`<>` 非法会导致镜像启动时
        // MyBatis 解析 mapper 崩溃、部署健康检查全挂——此前 `<> ''` 线上部署失败实证）
        String scriptBody = sql.substring(sql.indexOf("<script>") + "<script>".length(),
                sql.indexOf("</script>"));
        javax.xml.parsers.DocumentBuilderFactory factory =
                javax.xml.parsers.DocumentBuilderFactory.newInstance();
        try {
            factory.newDocumentBuilder()
                    .parse(new org.xml.sax.InputSource(new java.io.StringReader(
                            "<script>" + scriptBody + "</script>")));
        } catch (Exception e) {
            throw new AssertionError(
                    "selectPrevPeriodQuantities 的 <script> 动态 SQL 不是合法 XML（" + e.getMessage()
                            + "）。<script> 内禁止出现裸 < > 字符（如 <> 应写作 != 或 XML 转义）。", e);
        }
    }

    @Test
    @DisplayName("selectPrevPeriodQuantities — 无 tenantId 参数（租户由拦截器注入）")
    void selectPrevPeriodQuantities_noTenantParam() throws Exception {
        Method method = OrderItemMapper.class.getMethod(
                "selectPrevPeriodQuantities", java.util.List.class,
                java.time.OffsetDateTime.class, java.time.OffsetDateTime.class);
        for (Parameter param : method.getParameters()) {
            Param p = param.getAnnotation(Param.class);
            if (p != null) {
                assertThat(p.value()).isNotEqualTo("tenantId");
            }
        }
    }

    // ═══════════════════════════════════════════════════════════════════
    // #2989/#2994/#2996 事故回归：排行 SQL 必须能被 JSqlParser（MP 多租户
    // TenantLineInnerInterceptor 依赖）解析。
    // 事故链：`<> ''` 未转义 → MyBatis XML 解析 SAXParseException 启动崩溃（#2990）；
    // `&lt;&gt; ''` 转义后 MyBatis 放行，但租户插件 JSqlParser 收到 &lt;&gt; 字面量 →
    // ParseException: unexpected token "&" → 生产 product-ranking 500（#2994/#2995）。
    // 红线结论：非 <script> 注解 SQL 不得出现 XML 特殊字符/实体（<、&），
    // 比较运算符统一用 !=（#2996 已验证可行）。
    // ═══════════════════════════════════════════════════════════════════

    @Test
    @DisplayName("selectProductRanking（非 script 注解）— 不含 XML 特殊字符 < 与 &，防 &lt;&gt; 类事故复发")
    void selectProductRanking_noXmlSensitiveChars() throws Exception {
        Method method = OrderItemMapper.class.getMethod(
                "selectProductRanking", java.time.OffsetDateTime.class, int.class);
        Select select = method.getAnnotation(Select.class);
        String sql = String.join(" ", select.value());

        // 非 <script> 注解 SQL 会原样交给 JSqlParser：任何 <（含实体 &lt;）与 & 都会解析失败
        assertThat(sql).doesNotContain("<");
        assertThat(sql).doesNotContain("&");
        assertThat(sql).contains("LIMIT #{limit}");
    }

    @Test
    @DisplayName("selectProductRanking — 最终 SQL 可被 JSqlParser 解析（模拟租户插件链路）")
    void selectProductRanking_parseableByJsqlParser() throws Exception {
        Method method = OrderItemMapper.class.getMethod(
                "selectProductRanking", java.time.OffsetDateTime.class, int.class);
        Select select = method.getAnnotation(Select.class);
        String sql = String.join(" ", select.value());

        String rendered = sql
                .replace("#{periodStart}", "'2026-09-01 00:00:00'")
                .replace("#{limit}", "10");

        parseByJsqlParser(rendered);
        // 追加租户条件（TenantLineInnerInterceptor 注入形态）也应可解析
        parseByJsqlParser("SELECT * FROM (" + rendered + ") t WHERE tenant_id = 1");
    }

    @Test
    @DisplayName("selectPrevPeriodQuantities（script 注解）— 渲染后可解析，幽灵过滤用 != 而非 <>/&lt;&gt;")
    void selectPrevPeriodQuantities_renderableAndParseable() throws Exception {
        Method method = OrderItemMapper.class.getMethod(
                "selectPrevPeriodQuantities", java.util.List.class,
                java.time.OffsetDateTime.class, java.time.OffsetDateTime.class);
        Select select = method.getAnnotation(Select.class);
        String sql = String.join(" ", select.value());

        // 事故红线：幽灵过滤条件必须是 !=，禁止回退到 <>/&lt;&gt;
        assertThat(sql).contains("oi.product_id != ''");
        assertThat(sql).doesNotContain("product_id <>");
        assertThat(sql).doesNotContain("&lt;&gt;");
        assertThat(sql).doesNotContain("product_id <");

        // 模拟 MyBatis 对 <script> 的渲染（剥动态标签 + XML 实体还原 + 参数字面量化），
        // 渲染结果必须能被 JSqlParser 解析（防租户插件解析崩溃 500）
        String rendered = renderScriptSql(sql);
        parseByJsqlParser(rendered);
    }

    /** 剥离 MyBatis <script> 动态标签并做 XML 实体还原，模拟 MyBatis 渲染后的最终 SQL */
    private static String renderScriptSql(String annotatedSql) {
        return annotatedSql
                .replace("<script>", "")
                .replace("</script>", "")
                .replaceAll("<foreach[^>]*>#\\{pid}</foreach>", "'p1'")
                // MyBatis 对 <script> 注解走 XML 解析：实体还原为运算符
                .replace("&lt;", "<")
                .replace("&gt;", ">")
                .replace("&amp;", "&")
                // 参数字面量化（仅语法解析，非实际绑定）
                .replace("#{prevStart}", "'2026-08-24 00:00:00'")
                .replace("#{periodStart}", "'2026-08-31 00:00:00'");
    }

    /** JSqlParser 语法解析：抛解析异常 → 测试失败（锁死租户插件解析事故） */
    private static void parseByJsqlParser(String sql) throws Exception {
        try {
            var stmt = CCJSqlParserUtil.parse(sql);
            org.junit.jupiter.api.Assertions.assertNotNull(stmt, "SQL 应为可解析语句");
        } catch (net.sf.jsqlparser.JSQLParserException e) {
            throw new AssertionError("SQL 无法被 JSqlParser 解析（MyBatis-Plus 租户插件会 500）：\n"
                    + sql + "\n原始错误: " + e.getMessage(), e);
        }
    }
}