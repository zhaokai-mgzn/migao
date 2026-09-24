// case_ids: CU-002, CU-010

package com.migao.admin.controller;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.databind.BeanDescription;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.migao.admin.entity.CustomerProfile;
import com.migao.admin.mapper.CustomerProfileMapper;
import com.migao.admin.mapper.CustomerSegmentMapper;
import com.migao.admin.mapper.CustomerSegmentMemberMapper;
import com.migao.admin.mapper.CustomerTagMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.SessionMapper;
import com.migao.admin.mapper.SessionMessageMapper;
import com.migao.admin.service.CustomerService;
import com.migao.admin.support.fieldtruth.CustomerProfileFieldTruth;
import com.migao.admin.support.fieldtruth.FieldTruth;
import com.migao.admin.support.fieldtruth.FieldTruthRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.http.converter.json.MappingJackson2HttpMessageConverter;

import java.lang.reflect.Field;
import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.OffsetDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 客户画像字段在**多个接口面**上的键名对账（issue #5459）。
 *
 * <p><b>缺陷形态</b>：同一批字段在两个面上名字不同 —— 画像视图（{@code GET /api/admin/customers/profile-view}）
 * 的行键集由构造保证等于 #5362 的**声明字段名**（{@code rScore}），而既有列表 / 详情 / PUT 面把实体直接交给
 * Jackson，默认 Bean 命名会把「前两个字母都大写」的 getter（{@code getRScore()}）折叠成全小写
 * （{@code rscore}）⇒ 同一字段两个名字，消费方要写两套键名，写错一处就静默取不到值
 * （与「同一真值两处投影」同族）。</p>
 *
 * <p><b>本文件钉住的关系</b>（全部**现取**，不手抄字段名、不另写一份台账）：</p>
 * <ol>
 *   <li><b>四个面 × 声明字段名逐字相等</b>（列表 / 详情 / PUT 响应 / 画像视图，经真实 controller +
 *       真实 service 的 MockMvc 响应体，全部派生自**同一个实体实例** ⇒ 两侧同刻取数）；</li>
 *   <li><b>类级元守卫</b>：注册表 {@link FieldTruthRegistry} 里**每一张表**的声明字段名都必须等于
 *       Jackson 会用的线上键名 —— 新登记一张表/新加一个缩写字段**自动**纳入，不需要改本判据
 *       （射程边界：未登记真值声明的实体不在本判据面内，如实登记）；</li>
 *   <li><b>线上形态</b>（{@code application.yml} 的 {@code default-property-inclusion: non_null}
 *       + #5362 的读面遮蔽）：可见键必须**恰好**是声明的「有真值」字段集 —— 既防非声明键名，
 *       也防遮蔽口径漂移（无真值字段在线上**无键**，不是 {@code key: null}；如实登记，
 *       与 {@code customer-list.detail-shape} 文案里「key 不删、值为 null」的说法不一致）；</li>
 *   <li><b>输入方向</b>：实体同时是 {@code PUT /api/admin/customers/{id}} 的 {@code @RequestBody}
 *       ⇒ 声明字段名必须能被反序列化接住（只改输出 = 半个修）；</li>
 *   <li><b>前提自证</b>：线上没有任何命名策略配置（否则本判据所用的默认命名 mapper 不再等价于线上）。</li>
 * </ol>
 *
 * <p>⚠️ 判据 1 刻意用**保留 null** 的序列化器：那三个被折叠的字段恰好都属「无真值」⇒ 线上被遮蔽成
 * null ⇒ 又被 {@code non_null} 丢弃 ⇒ **在线上根本看不到键**（这正是该缺陷长期没被发现的藏身处）。
 * 键名维度只在「键仍在、值为 null」的形态下可观察 —— 判据 3 负责钉线上形态。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("客户画像字段键名对账（issue #5459）：列表 / 详情 / PUT / 画像视图 ≡ #5362 声明字段名")
class CustomerProfileWireKeyParityTest extends BaseControllerTest {

    /** 真值面：判据两侧的字段名都从这里现取（声明 = 键名的唯一基准）。 */
    private static final FieldTruth.Declaration DECLARATION = CustomerProfileFieldTruth.declaration();
    private static final Set<String> DECLARED = DECLARATION.declaredFields();

    /** 读响应体用：只解析 JSON、不改键名（对账的读数必须来自原样响应）。 */
    private static final ObjectMapper READER = new ObjectMapper();

    private static final String CUSTOMER_ID = "cust-key-001";

    @Mock
    private CustomerProfileMapper customerProfileMapper;
    @Mock
    private CustomerTagMapper customerTagMapper;
    @Mock
    private CustomerSegmentMapper customerSegmentMapper;
    @Mock
    private CustomerSegmentMemberMapper customerSegmentMemberMapper;
    @Mock
    private OrderMapper orderMapper;
    @Mock
    private SessionMapper sessionMapper;
    @Mock
    private SessionMessageMapper sessionMessageMapper;

    @InjectMocks
    private CustomerService customerService;

    /** 保留 null 的序列化器（键名维度必须可观察，见类注释的 ⚠️）。 */
    private MockMvc mockMvc;
    /** 镜像 {@code application.yml}（{@code default-property-inclusion: non_null}）的序列化器。 */
    private MockMvc productionMockMvc;

    /** 同一个实体实例：四个面都由它派生（两侧同刻取数，避免「一边快照一边实时」）。 */
    private CustomerProfile row;

    @BeforeEach
    void setUpSurfaces() {
        row = fullyPopulated();
        row.setId(CUSTOMER_ID);
        row.setTenantId(TEST_TENANT_ID);
        row.setPhone("13800138000");
        // tags 是 Object：详情/列表会走 resolveCustomerTags（按标签 ID 过滤），空列表最省一次标签查询
        row.setTags(List.of());

        Page<CustomerProfile> page = new Page<>(1, 10);
        page.setRecords(List.of(row));
        page.setTotal(1);

        when(customerProfileMapper.selectPage(any(Page.class), any())).thenReturn(page);
        when(customerProfileMapper.selectById(anyString())).thenReturn(row);
        when(customerProfileMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(row));
        when(customerProfileMapper.updateById(any(CustomerProfile.class))).thenReturn(1);
        when(orderMapper.selectList(any())).thenReturn(List.of());
        when(sessionMapper.selectList(any())).thenReturn(List.of());

        mockMvc = mockMvcWith(false);
        productionMockMvc = mockMvcWith(true);
    }

    // ── 判据 1：四个面 ≡ 声明字段名（实例判据）──────────────────────────────

    @Test
    @DisplayName("列表 / 详情 / PUT / 画像视图：四个面经真实接口取回的键名逐字等于声明字段名")
    void everySurfaceCarriesTheDeclaredFieldNames() throws Exception {
        Map<String, String> responses = new LinkedHashMap<>();
        responses.put("列表 GET /api/admin/customers",
                getJson(mockMvc, "/api/admin/customers"));
        responses.put("详情 GET /api/admin/customers/{id}",
                getJson(mockMvc, "/api/admin/customers/" + CUSTOMER_ID));
        responses.put("PUT /api/admin/customers/{id}",
                putJson(mockMvc, "/api/admin/customers/" + CUSTOMER_ID));
        responses.put("画像视图 GET /api/admin/customers/profile-view",
                getJson(mockMvc, "/api/admin/customers/profile-view"));

        Map<String, Set<String>> surfaces = new LinkedHashMap<>();
        surfaces.put("列表 GET /api/admin/customers", keys(response(responses.get("列表 GET /api/admin/customers"), "data", "items", "0")));
        surfaces.put("详情 GET /api/admin/customers/{id}", keys(response(responses.get("详情 GET /api/admin/customers/{id}"), "data", "profile")));
        surfaces.put("PUT /api/admin/customers/{id}", keys(response(responses.get("PUT /api/admin/customers/{id}"), "data")));
        surfaces.put("画像视图 GET /api/admin/customers/profile-view",
                keys(response(responses.get("画像视图 GET /api/admin/customers/profile-view"), "data", DECLARATION.table(), "0")));

        for (Map.Entry<String, Set<String>> surface : surfaces.entrySet()) {
            System.out.println("[#5459 键名对账] " + census(surface.getKey(), DECLARED, surface.getValue()));
        }
        // 读数先全打出来再断言：判红时不许「第一个面挂了 ⇒ 另外三个面的读数看不到」
        for (Map.Entry<String, Set<String>> surface : surfaces.entrySet()) {
            assertThat(surface.getValue())
                    .as("issue #5459：%s —— 键名必须逐字等于声明字段名（实得读数：%s）",
                            surface.getKey(), census(surface.getKey(), DECLARED, surface.getValue()))
                    .isEqualTo(DECLARED);
        }
    }

    // ── 判据 2：类级元守卫（注册表里每一张表都自动纳入）────────────────────

    @Test
    @DisplayName("类级元守卫：注册表里每一张表的每个声明字段，Jackson 键名都必须等于声明名")
    void everyRegisteredDeclarationMatchesJacksonNaming() {
        ObjectMapper introspector = new ObjectMapper();
        Map<Class<?>, FieldTruth.Declaration> registered = FieldTruthRegistry.all();
        assertThat(registered).as("注册表为空 ⇒ 本判据没有覆盖面（机制前提）").isNotEmpty();

        for (FieldTruth.Declaration declaration : registered.values()) {
            BeanDescription description = introspector.getSerializationConfig()
                    .introspect(introspector.constructType(declaration.entity()));
            Set<String> wireNames = new TreeSet<>();
            description.findProperties().forEach(property -> wireNames.add(property.getName()));

            String census = census("表 " + declaration.table()
                    + "（实体 " + declaration.entity().getSimpleName() + "）", declaration.declaredFields(), wireNames);
            System.out.println("[#5459 键名对账] " + census);
            assertThat(wireNames)
                    .as("issue #5459 类级判据：%s —— 线上键名必须逐字等于声明字段名（实得读数：%s）", declaration.table(), census)
                    .isEqualTo(declaration.declaredFields());
        }
    }

    // ── 判据 3：线上形态（non_null）：可见键一律是声明名 ────────────────────

    @Test
    @DisplayName("线上形态：可见键一律是声明名；无真值字段在线上无键（不许出现非声明名）")
    void productionWireNeverInventsKeyNames() throws Exception {
        Map<String, String> responses = new LinkedHashMap<>();
        responses.put("列表", getJson(productionMockMvc, "/api/admin/customers"));
        responses.put("详情", getJson(productionMockMvc, "/api/admin/customers/" + CUSTOMER_ID));
        responses.put("画像视图", getJson(productionMockMvc, "/api/admin/customers/profile-view"));

        Set<String> listKeys = keys(response(responses.get("列表"), "data", "items", "0"));
        Set<String> detailKeys = keys(response(responses.get("详情"), "data", "profile"));
        Set<String> viewKeys = keys(response(responses.get("画像视图"), "data", DECLARATION.table(), "0"));

        Map<String, Set<String>> onWire = new LinkedHashMap<>();
        onWire.put("列表", listKeys);
        onWire.put("详情", detailKeys);
        onWire.put("画像视图", viewKeys);

        for (Map.Entry<String, Set<String>> surface : onWire.entrySet()) {
            System.out.println("[#5459 键名对账] " + census("线上 " + surface.getKey(), DECLARED, surface.getValue()));
        }
        for (Map.Entry<String, Set<String>> surface : onWire.entrySet()) {
            String census = census("线上 " + surface.getKey(), DECLARED, surface.getValue());
            assertThat(surface.getValue())
                    .as("issue #5459：线上 %s 不得出现非声明键名（实得读数：%s）", surface.getKey(), census)
                    .isSubsetOf(DECLARED);
            // 夹具每个字段都有值 ⇒ 线上可见键**恰好**是「有真值」那一侧：既要防非声明名（改名/凭空多键），
            // 也要防遮蔽口径漂移（无真值字段漏出去 / 有真值字段被吞）—— 宽松形态（只判 ⊆）漏得过后两者。
            assertThat(surface.getValue())
                    .as("issue #5459：线上 %s 可见键必须恰好等于声明的「有真值」字段集（实得读数：%s）",
                            surface.getKey(), census)
                    .isEqualTo(DECLARATION.hasTruthFields());
        }
    }

    // ── 判据 4：输入方向（PUT 请求体也是这个实体）────────────────────────────

    @Test
    @DisplayName("输入方向：声明字段名必须能被反序列化接住（只修序列化 = 半个修）")
    void declaredNamesAreAcceptedOnTheInputSide() throws Exception {
        // 实体同时是 PUT /api/admin/customers/{id} 的 @RequestBody ⇒ 键名关系有两个方向：
        // 只把输出改名、输入仍认旧名（或反之）都是「同一字段两个名字」。
        ObjectMapper mapper = new ObjectMapper()
                .registerModule(new JavaTimeModule())
                .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);

        List<String> covered = new java.util.ArrayList<>();
        StringBuilder json = new StringBuilder("{");
        for (String name : DECLARED) {
            Field field = CustomerProfile.class.getDeclaredField(name);
            Object value = inputSample(field.getType());
            if (value == null) {
                continue; // 日期类型：输入形态另有约定（date-format），不在本判据面内 —— 如实登记
            }
            json.append(json.length() > 1 ? "," : "")
                    .append(mapper.writeValueAsString(name)).append(":")
                    .append(mapper.writeValueAsString(value));
            covered.add(name);
        }
        json.append("}");

        CustomerProfile parsed = mapper.readValue(json.toString(), CustomerProfile.class);
        System.out.println("[#5459 键名对账] 输入方向（PUT 请求体）：声明字段 " + covered.size()
                + " 个按声明名下发，反序列化接住 " + covered.size() + " 个");
        for (String name : covered) {
            Field field = CustomerProfile.class.getDeclaredField(name);
            field.setAccessible(true);
            assertThat(field.get(parsed))
                    .as("issue #5459：PUT 请求体里按声明名 %s 下发的值必须落到该字段（实得 null ⇒ 该键名不被承认）", name)
                    .isEqualTo(inputSample(field.getType()));
        }
    }

    // ── 判据 5：前提自证（判据所用的 mapper 必须等价于线上命名）──────────────

    @Test
    @DisplayName("前提自证：线上未配置命名策略（否则本判据的 mapper 不再等价于线上）")
    void premiseProductionConfiguresNoPropertyNamingStrategy() throws Exception {
        Path config = Path.of("src/main/resources/application.yml");
        assertThat(Files.exists(config)).as("前提自证失败：找不到 %s（surefire 工作目录应为模块根）", config).isTrue();

        String yaml = Files.readString(config);
        assertThat(yaml)
                .as("前提自证：%s 里一旦出现命名策略，本判据所用的默认命名 mapper 就不再等价于线上（需同批改判）", config)
                .doesNotContain("property-naming-strategy");
    }

    // ── 夹具与读数工具 ─────────────────────────────────────────────────────

    /**
     * 按**声明**逐字段填样本值（反射，不手抄字段名）⇒ 键名对账不因「某个字段恰为 null 而少一个键」失真。
     * 填完自证一次：每个声明字段都非空（否则判据会退化成「缺键也算过」的空断言）。
     */
    private static CustomerProfile fullyPopulated() {
        CustomerProfile profile = new CustomerProfile();
        for (String name : DECLARED) {
            try {
                Field field = CustomerProfile.class.getDeclaredField(name);
                field.setAccessible(true);
                field.set(profile, sample(field.getType(), name));
            } catch (ReflectiveOperationException e) {
                throw new IllegalStateException("声明字段在实体里读不出（声明与实体漂移）：" + name, e);
            }
        }
        for (String name : DECLARED) {
            try {
                Field field = CustomerProfile.class.getDeclaredField(name);
                field.setAccessible(true);
                if (field.get(profile) == null) {
                    throw new IllegalStateException("夹具缺值（会让键名对账退化成空断言）：" + name
                            + "（类型 " + field.getType().getSimpleName() + " 未覆盖）");
                }
            } catch (ReflectiveOperationException e) {
                throw new IllegalStateException(e);
            }
        }
        return profile;
    }

    private static Object sample(Class<?> type, String name) {
        if (type == String.class) {
            return "样本-" + name;
        }
        if (type == Integer.class) {
            return 7;
        }
        if (type == Long.class) {
            return 7L;
        }
        if (type == BigDecimal.class) {
            return new BigDecimal("7.00");
        }
        if (type == OffsetDateTime.class) {
            return OffsetDateTime.parse("2024-01-02T03:04:05+08:00");
        }
        if (type == Boolean.class || type == boolean.class) {
            return true;
        }
        // Object（tags / customFields / craftProfile）：列表最省事，序列化形态稳定
        return List.of();
    }

    /**
     * 输入方向（反序列化）的样本值：只覆盖**往返精确**的类型。
     * 日期类型返回 {@code null} = 不在本判据面内（Jackson 的日期输入形态另有约定，避免用「形态差异」冒充缺陷）。
     */
    private static Object inputSample(Class<?> type) {
        return type == OffsetDateTime.class ? null : sample(type, "输入样本");
    }

    private MockMvc mockMvcWith(boolean productionInclusion) {
        ObjectMapper mapper = new ObjectMapper()
                .registerModule(new JavaTimeModule())
                .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);
        if (productionInclusion) {
            mapper.setSerializationInclusion(JsonInclude.Include.NON_NULL);
        }
        return MockMvcBuilders.standaloneSetup(new CustomerController(customerService))
                .setMessageConverters(new MappingJackson2HttpMessageConverter(mapper))
                .build();
    }

    private static String getJson(MockMvc mvc, String url) throws Exception {
        return mvc.perform(get(url)).andExpect(status().isOk()).andReturn()
                .getResponse().getContentAsString();
    }

    private static String putJson(MockMvc mvc, String url) throws Exception {
        return mvc.perform(put(url).contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isOk()).andReturn()
                .getResponse().getContentAsString();
    }

    private static JsonNode response(String json, String... path) throws Exception {
        JsonNode node = READER.readTree(json);
        for (String step : path) {
            // 数组下标（行数组的第 0 行）与对象键共用同一串路径：数字步走下标，其余走键
            node = node == null ? null
                    : (node.isArray() && step.chars().allMatch(Character::isDigit)
                            ? node.get(Integer.parseInt(step))
                            : node.get(step));
        }
        assertThat(node).as("响应里取不到路径 %s（响应原文：%s）", String.join(".", path), json).isNotNull();
        return node;
    }

    private static Set<String> keys(JsonNode node) {
        Set<String> keys = new TreeSet<>();
        node.fieldNames().forEachRemaining(keys::add);
        return keys;
    }

    /** 可归因读数：键数 / 声明数 / 非声明名（= 被改名或凭空多出来的键）/ 缺键。 */
    private static String census(String surface, Set<String> declared, Set<String> actual) {
        Set<String> invented = new TreeSet<>(actual);
        invented.removeAll(declared);
        Set<String> missing = new TreeSet<>(declared);
        missing.removeAll(actual);
        return String.format("%s：键 %d 个／声明 %d 个；非声明名=%s；缺键=%s",
                surface, actual.size(), declared.size(), invented, missing);
    }
}