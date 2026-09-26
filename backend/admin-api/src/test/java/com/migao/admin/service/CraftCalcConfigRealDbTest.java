// case_ids: CH-036, OR-032
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.MybatisSqlSessionFactoryBuilder;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.CraftCalcConfig;
import com.migao.admin.mapper.CraftCalcConfigMapper;
import net.sf.jsqlparser.expression.Expression;
import net.sf.jsqlparser.expression.LongValue;
import org.apache.ibatis.mapping.Environment;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.apache.ibatis.transaction.jdbc.JdbcTransactionFactory;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.web.client.RestTemplate;

import javax.sql.DataSource;
import java.lang.reflect.Field;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.Statement;
import java.util.LinkedHashMap;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import org.mockito.ArgumentCaptor;

/**
 * 🔴 <b>判据 5 的**真栈**半边（issue #4945 处 1）</b>：真 PG + 真 {@code craft_calc_configs} 行 +
 * 真 MyBatis 读 + 真 {@code CraftCalcClient} 注入。
 *
 * <h2>为什么必须真库（函数级判据结构上测不到这一层）</h2>
 * issue #4945 登记的风险是「一旦两侧的**入口接线**（谁把 config 送进引擎）再次漂移，函数级判据不会红」。
 * 「入口接线」在 Java 这一侧有三跳，**每一跳都只在真库 + 真装配下才存在**：
 * <ol>
 *   <li><b>行真的读得回来</b>：{@code CraftCalcConfigMapper.selectActiveByTenant} 的
 *       {@code tenant_id} + {@code deleted = 0} 谓词、列名、软删过滤、JSONB 列的 Jackson 反序列化 ——
 *       mock 面（{@code CraftCalcClientTest} 用 {@code mock(CraftCalcConfigMapper.class)}）
 *       结构上看不见「列名写错 / 表未纳管 / JSONB 解不出来」这三类真问题；</li>
 *   <li><b>行值真的变成引擎能吃的 config</b>：{@code CraftCalcConfig#toConfigMap()} 的键集与取值
 *       直接决定引擎拿到的口径（键名漂移 ⇒ 引擎静默回落默认值 = 米宝一个数、落库另一个数）；</li>
 *   <li><b>最后那一跳真的发生</b>：{@code CraftCalcClient.withTenantConfig} 把 config **放进请求体**
 *       发给 {@code POST /api/internal/production/craft-calc} —— 本类捕获**真实出参**逐值核对。</li>
 * </ol>
 *
 * <h2>与 AI 侧判据的关系（同一租户、同一入参）</h2>
 * 米宝工具路径侧的判据是
 * {@code backend/ai-agent-service/tests/test_production/test_tenant_craft_calc_config.py}（纯函数级 +
 * 响应形状镜像）。两侧的**同一 config** 由本类与那条判据各自的 {@code TENANT_CONFIG_JSON} 声明，
 * 逐值一致性由 {@code tests/unit_ci_workflows/test_craft_calc_config_contract.py} 的判据 9 **机械钉住**
 * （改一侧不改另一侧 ⇒ CI 必红）。
 *
 * <h2>仍然不覆盖的（如实登记，不冒充已覆盖）</h2>
 * <b>跨进程的那一跳</b>（{@code RestTemplate} 真的连上 ai-agent 并让引擎算出米数）不在本类内 ——
 * 它需要「DB + admin-api + ai-agent」同时活着的腿，而 PR 触发的 job 里没有这样一条（本类是
 * {@code admin-api-test} job，无 Python 运行时）。本类证明的是「**发给引擎的那份 config == 库里那一行**」；
 * 「同一 config ⇒ 两条路径米数逐值相等」由 AI 侧判据证明（同一引擎唯一实现）。两者的**拼接**是论证，
 * 不是一次真跑 —— 缺口与重启条件登记在 issue #4945。
 *
 * <h2>环境</h2>
 * 一次性真 PG 集群（{@code initdb} + {@code pg_ctl}，随机端口、跑完即停；收口在 {@link PgCluster}，
 * 失败/中止路径也会停库），schema 取自 {@code backend/admin-api/src/main/resources/db/init/schema.sql}
 * （bootstrap 终态，**不手抄列清单**）。缺 PG ⇒ {@link PgCluster#startOrAbort()}：
 * CI（{@code MIGAO_REQUIRE_REALDB=1}）⇒ 判**红**；本机未设该标记 ⇒ 显式 skip（「没跑」长得像「没跑」）。
 */
@DisplayName("#4945 处1 真栈：真库配置行 → 真 mapper → 真 toConfigMap → 真 CraftCalcClient 注入（逐值）")
class CraftCalcConfigRealDbTest {

    /** 有配置行的租户（= AI 侧判据的 TENANT_ID 同值：7 —— 见下方 TENANT_ID 注释）。 */
    private static final Long TENANT_WITH_ROW = 7L;
    /** **无**配置行的租户 ⇒ 零回归那一半（缺行 = 不传 config，与改动前逐值一致）。 */
    private static final Long TENANT_WITHOUT_ROW = 4946L;
    private static final String ROW_ID = "ccc-4945-real-row";

    /**
     * 真库那一行的配置值 —— 与
     * {@code backend/ai-agent-service/tests/test_production/test_tenant_craft_calc_config.py} 的
     * {@code TENANT_CONFIG_JSON} **逐值相同**（判据 9 机械钉住）。
     *
     * <p>与引擎默认值的两处**实质不同**：{@code default_formula}（pleat → fullness）与
     * {@code meters_rounding_step}（0.1 → 0.5）⇒ 米数 13.2 → 13.5（不是「相同数字换了个来源」，
     * 否则「接线生效」这条判据是恒真的空断言）。</p>
     */
    private static final String TENANT_CONFIG_JSON = """
            {
              "per_fold_single": 0.25,
              "per_fold_mixed_times": {"1": 0.65, "2": 1.2},
              "margin_single": 0.2,
              "margin_multi": 0.3,
              "min_fullness": 1.5,
              "tiers": {
                "standard": {"fullness": 2.0, "label": "标准工艺"},
                "economy": {"fullness": 1.8, "label": "经济工艺"}
              },
              "default_formula": "fullness",
              "hem_margin": 0.3,
              "meters_rounding_step": 0.5
            }
            """;

    /** V114 起 `toConfigMap()` 多出的两个**企业阈值参数**（不在上面那份 JSON 里，本类单独钉）。 */
    private static final Map<String, String> OVERSIZE_COLUMNS = Map.of(
            "oversize_width_threshold", "5.5",
            "oversize_height_threshold", "3.5");

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private static PgCluster cluster;
    private static DataSource dataSource;
    private static SqlSession session;
    private static CraftCalcConfigMapper craftCalcConfigMapper;

    @BeforeAll
    static void startRealPostgresWithTenantConfigRow() throws Exception {
        cluster = PgCluster.startOrAbort();
        dataSource = cluster.dataSource();
        try (Connection conn = dataSource.getConnection(); Statement st = conn.createStatement()) {
            st.execute(Files.readString(Path.of(
                    "src/main/resources/db/init/schema.sql")));
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT_WITH_ROW + ", 'ccc-4945', 'ccc-4945')");
            st.execute("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES ("
                    + TENANT_WITHOUT_ROW + ", 'ccc-4946', 'ccc-4946')");
            // **真的**一行配置（列值取自上面那份 JSON ⇒ 写完立刻回读核对，判据 1）
            st.execute("INSERT INTO craft_calc_configs (id, tenant_id, per_fold_single,"
                    + " per_fold_mixed_times, margin_single, margin_multi, min_fullness, tiers,"
                    + " default_formula, hem_margin, meters_rounding_step,"
                    + " oversize_width_threshold, oversize_height_threshold, status, deleted)"
                    + " VALUES ('" + ROW_ID + "', " + TENANT_WITH_ROW + ", 0.25,"
                    + " '{\"1\": 0.65, \"2\": 1.2}'::jsonb, 0.2, 0.3, 1.5,"
                    + " '{\"standard\": {\"fullness\": 2.0, \"label\": \"标准工艺\"},"
                    + " \"economy\": {\"fullness\": 1.8, \"label\": \"经济工艺\"}}'::jsonb,"
                    + " 'fullness', 0.3, 0.5, " + OVERSIZE_COLUMNS.get("oversize_width_threshold")
                    + ", " + OVERSIZE_COLUMNS.get("oversize_height_threshold") + ", 'active', 0)");
            // 本租户**已软删**的一行 ⇒ 读面必须看不到它（软删过滤是真库才有的语义）
            st.execute("INSERT INTO craft_calc_configs (id, tenant_id, per_fold_single,"
                    + " deleted) VALUES ('ccc-4945-soft-deleted', " + TENANT_WITH_ROW + ", 0.9, 1)");
        }

        MybatisConfiguration configuration = new MybatisConfiguration();
        configuration.setMapUnderscoreToCamelCase(true);
        configuration.setEnvironment(
                new Environment("ccc-4945", new JdbcTransactionFactory(), dataSource));
        MybatisPlusInterceptor tenantLine = new MybatisPlusInterceptor();
        tenantLine.addInnerInterceptor(new TenantLineInnerInterceptor(new TenantLineHandler() {
            @Override
            public Expression getTenantId() {
                return new LongValue(TenantContext.getTenantId() == null
                        ? TENANT_WITH_ROW : TenantContext.getTenantId());
            }

            @Override
            public String getTenantIdColumn() {
                return "tenant_id";
            }

            @Override
            public boolean ignoreTable(String tableName) {
                return false;
            }
        }));
        configuration.addInterceptor(tenantLine);
        configuration.addMapper(CraftCalcConfigMapper.class);
        SqlSessionFactory factory = new MybatisSqlSessionFactoryBuilder().build(configuration);
        session = factory.openSession(true);
        craftCalcConfigMapper = session.getMapper(CraftCalcConfigMapper.class);
    }

    @AfterAll
    static void stopRealPostgres() {
        if (session != null) {
            session.close();
        }
        if (cluster != null) {
            cluster.stop();
        }
        TenantContext.clear();
    }

    // ─────────────────────────────────────────── 判据 1：真库那一行读得回来、键集与取值逐值对

    @Test
    @DisplayName("判据1 真库行 → 真 mapper → toConfigMap()：声明的那 9 个键**逐值相等**，软删行看不到")
    void realDbRowIsReadBackAndMapsToTheDeclaredConfig() throws Exception {
        TenantContext.setTenantId(TENANT_WITH_ROW);
        CraftCalcConfig row = craftCalcConfigMapper.selectActiveByTenant(TENANT_WITH_ROW);
        assertThat(row).as("真库里的活跃配置行没读回来（谓词 / 列名 / 软删过滤）").isNotNull();
        assertThat(row.getId()).isEqualTo(ROW_ID);

        Map<String, Object> config = row.toConfigMap();
        JsonNode declared = MAPPER.readTree(TENANT_CONFIG_JSON);
        declared.properties().forEach(entry -> {
            String key = entry.getKey();
            assertThat(config).as("toConfigMap() 缺键 " + key + " ⇒ 引擎拿不到该口径").containsKey(key);
            // ⚠️ **按值**比较（`canonical` 去标度）：库列 `NUMERIC(6,3)` 读回来是 `0.250`，
            // 而 JSON 字面量是 `0.25` —— 直接比 JsonNode 会因**标度**不同假红（BigDecimal.equals
            // 是标度敏感的）。数值口径才是本判据的对象。
            JsonNode actual = canonical(MAPPER.valueToTree(config.get(key)));
            assertThat(actual)
                    .as("键 " + key + " 的真库取值与声明不符（改了库或改了声明，另一侧没跟）")
                    .isEqualTo(canonical(entry.getValue()));
        });
        // V114 的两个企业阈值参数：值来自**行**（不是常量），本类单独钉住
        OVERSIZE_COLUMNS.forEach((key, expected) -> assertThat(
                String.valueOf(config.get(key))).startsWith(expected));
        // 软删那一行（per_fold_single = 0.9）**不得**参与读取 —— 单行表的口径由部分唯一索引保证
        assertThat(String.valueOf(config.get("per_fold_single"))).isNotEqualTo("0.9");
    }

    // ─────────────────────────────────────────── 判据 2：真 client 把那一行**逐值**发进引擎请求体

    @Test
    @DisplayName("判据2 CraftCalcClient 出参：请求体的 config **逐值等于**真库那一行（含 URL 与 token 头）")
    void craftCalcClientSendsExactlyTheDatabaseRowToTheEngine() throws Exception {
        TenantContext.setTenantId(TENANT_WITH_ROW);
        CraftCalcConfig row = craftCalcConfigMapper.selectActiveByTenant(TENANT_WITH_ROW);
        assertThat(row).isNotNull();

        RestTemplate restTemplate = mock(RestTemplate.class);
        when(restTemplate.exchange(anyString(), eq(HttpMethod.POST), any(HttpEntity.class),
                eq(String.class))).thenReturn(ResponseEntity.ok(engineOkBody()));
        CraftCalcClient client = new CraftCalcClient(restTemplate, craftCalcConfigMapper);
        inject(client, "baseUrl", "http://agent:8000");
        inject(client, "serviceToken", "svc-token-4945");

        client.calc(calcRequest());

        @SuppressWarnings("rawtypes")
        ArgumentCaptor<HttpEntity> captor = ArgumentCaptor.forClass(HttpEntity.class);
        org.mockito.Mockito.verify(restTemplate)
                .exchange(anyString(), eq(HttpMethod.POST), captor.capture(), eq(String.class));
        @SuppressWarnings("unchecked")
        Map<String, Object> payload = (Map<String, Object>) captor.getValue().getBody();

        // 出参的 config 就是**库里那一行**（同一份 toConfigMap ⇒ 逐值相等，不是「形状相似」）
        assertThat(payload.get("config"))
                .as("发给引擎的 config ≠ 真库那行的 toConfigMap() ⇒ 两侧入口接线已漂移")
                .isEqualTo(row.toConfigMap());
        assertThat(((Map<?, ?>) payload.get("config")).keySet())
                .as("config 的键集必须覆盖引擎的全部配置键（缺键 ⇒ 引擎静默回落默认口径）")
                .isEqualTo(row.toConfigMap().keySet());
        // 调用方**原样透传**的入参不被就地污染（withTenantConfig 返回新 map）
        Map<String, Object> request = calcRequest();
        client.calc(request);
        assertThat(request).as("withTenantConfig 就地改了调用方的 map（上游复用会被污染）")
                .doesNotContainKey("config");
    }

    // ─────────────────────────────────────────── 判据 2b：缺行 ⇒ **不传** config（零回归锁）

    @Test
    @DisplayName("判据2b 无配置行的租户 ⇒ 请求体**没有** config 键（未配置租户口径逐值不变）")
    void tenantWithoutRowSendsNoConfigKey() throws Exception {
        TenantContext.setTenantId(TENANT_WITHOUT_ROW);
        assertThat(craftCalcConfigMapper.selectActiveByTenant(TENANT_WITHOUT_ROW))
                .as("4946 号租户本来就不该有配置行（这是零回归那一半的前提）").isNull();

        RestTemplate restTemplate = mock(RestTemplate.class);
        when(restTemplate.exchange(anyString(), eq(HttpMethod.POST), any(HttpEntity.class),
                eq(String.class))).thenReturn(ResponseEntity.ok(engineOkBody()));
        CraftCalcClient client = new CraftCalcClient(restTemplate, craftCalcConfigMapper);
        inject(client, "baseUrl", "http://agent:8000");
        inject(client, "serviceToken", "svc-token-4945");

        client.calc(calcRequest());

        @SuppressWarnings("rawtypes")
        ArgumentCaptor<HttpEntity> captor = ArgumentCaptor.forClass(HttpEntity.class);
        org.mockito.Mockito.verify(restTemplate)
                .exchange(anyString(), eq(HttpMethod.POST), captor.capture(), eq(String.class));
        @SuppressWarnings("unchecked")
        Map<String, Object> payload = (Map<String, Object>) captor.getValue().getBody();
        // 缺行 ⇒ **不加** config 键（把默认值显式发过去 = 第二份会漂的默认值）
        assertThat(payload).doesNotContainKey("config");
    }

    // ─────────────────────────────────────────── 工装

    /**
     * JSON 树的**按值**规范化：数值节点 → 「去标度」的十进制文本（其余原样）。
     *
     * <p>为什么必须有：库列是 {@code NUMERIC(6,3)}（读回来 {@code 0.250}），而声明里写的是
     * JSON 字面量 {@code 0.25}；{@code BigDecimal.equals} 与 Jackson 的
     * {@code DoubleNode#equals(DecimalNode)} 都是**标度/类型敏感**的 ⇒ 直接比树会把
     * 「口径一致」误判成不一致（假红即坏断言）。本判据的对象是**数值口径**，不是标度。</p>
     */
    private static JsonNode canonical(JsonNode node) {
        if (node.isNumber()) {
            return MAPPER.getNodeFactory()
                    .textNode(node.decimalValue().stripTrailingZeros().toPlainString());
        }
        if (node.isObject()) {
            com.fasterxml.jackson.databind.node.ObjectNode out = MAPPER.createObjectNode();
            node.properties().forEach(e -> out.set(e.getKey(), canonical(e.getValue())));
            return out;
        }
        if (node.isArray()) {
            com.fasterxml.jackson.databind.node.ArrayNode out = MAPPER.createArrayNode();
            node.forEach(element -> out.add(canonical(element)));
            return out;
        }
        return node;
    }

    private static void inject(CraftCalcClient client, String field, String value) throws Exception {        Field f = CraftCalcClient.class.getDeclaredField(field);
        f.setAccessible(true);
        f.set(client, value);
    }

    /** 与 AI 侧判据同一入参：6.6m 窗 / 2.5m 高 / 打孔 / 单开 / 门幅 2.8。 */
    private static Map<String, Object> calcRequest() {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("width", 6.6);
        body.put("height", 2.5);
        body.put("mounting", "eyelet");
        body.put("open_count", 1);
        body.put("fabric_width", 2.8);
        return body;
    }

    /** 引擎最小合法回应（`fabric_meters` + `formula_text` 是 fail-closed 的两处必填键）。 */
    private static String engineOkBody() {
        return "{\"success\":true,\"data\":{\"fabric_meters\":13.5,\"pleat_count\":0,"
                + "\"per_panel_pleats\":0,\"per_fold\":0.25,\"fullness\":2.0,"
                + "\"formula_used\":\"fullness\",\"formula_text\":\"（引擎产出）\"}}";
    }
}
