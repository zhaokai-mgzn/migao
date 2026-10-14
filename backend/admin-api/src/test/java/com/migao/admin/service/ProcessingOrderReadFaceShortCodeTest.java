// case_ids: PG-018
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ProcessingOrderResponse;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyCollection;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * 加工单读面的**两键** {@code short_code} / {@code scan_url}（V155，issue #6867 / B3；设计
 * {@code docs/design/worker-h5-scan-and-report.md} §11.3「后端 · 读面键」+ §11.9 的 B3 行）。
 *
 * <p>判据对象 = 商家侧加工单读路 `getDetail`（详情）与 `list`（列表）**共用的那一段映射**
 * （`ProcessingOrderService.toResponse`）——两条路径都走它，故两键在两条路径上一致。</p>
 *
 * <h3>红证（改坏 ⇒ 必红，逐条对应一个真实缺陷形态）</h3>
 * <ul>
 *   <li><b>DTO 上无码省字段</b>（`if (hasText) resp.setShortCode(...)`）⇒
 *       {@code missingShortCodeStillCarriesBothKeysAsNull} 红（负控①：DTO 对象上两键必须**都在且为 null**）。
 *       🔴 **但线上 JSON 上「键缺席」与「值为 null」不可区分**：全局 `non_null` 策略下两者都不下发 ⇒
 *       消费方（`processingOrder?.short_code ?? null`）一律拿到「没有码」，**不得编造**
 *       （issue #6890 的实测发现 + 订正，见 {@code missingShortCodeKeysAreAbsentInJsonUnderProductionInclusion}）；</li>
 *   <li><b>无码时折成 `""`</b>（`shortCode == null ? "" : shortCode`）⇒ 同一条判据红（负控②：
 *       空串会印出一个**空二维码**内容，而不是「无码」占位）；</li>
 *   <li><b>拼出 `/o/null`</b>（少了 `hasText` 判断，直接 `base + "/o/" + po.getShortCode()`）⇒
 *       {@code missingShortCodeNeverProducesAFakeScanUrl} 红（负控③：印出去就是**扫不开也输不进**
 *       的假码 —— 纸面一旦打印不可回收）；</li>
 *   <li><b>基址写死/漏规范化</b>（硬编码域名、或不去尾斜杠 ⇒ 产出 `…com//o/…`）⇒
 *       {@code scanUrlIsAssembledServerSideFromTheExistingConfigSource} 红；</li>
 *   <li><b>为这两键新增一次 DB 查询</b>（例如改成 `processingOrderMapper.selectByShortCode(...)`
 *       或再 `selectById`）⇒ {@code readFaceAddsNoQueryForTheTwoKeys} 红（计数不增）；</li>
 *   <li><b>租户隔离被绕过</b>（把 `tenantId` 从解析条件里删掉 / 不做租户过滤）⇒
 *       {@code crossTenantCannotReadTheTwoKeys} 红。</li>
 * </ul>
 *
 * <h3>与既有判据的分工</h3>
 * <p>码**本体**（分配 / 补码 / 撤销不碰短码）由 B1 的
 * {@code ProductionServiceShortCodeTest} 判；`/o/{短码}` 的 302/404/410 由 B2 判；
 * 本文件只判**读面下发的形态**（无码时两键在 **DTO 对象**上恒在且为 null、值正确、零新增查询、租户隔离）。</p>
 *
 * <p>🔴 <b>线上 JSON 形态（issue #6890 订正）</b>：全局 {@code spring.jackson.default-property-inclusion: non_null}
 * （{@code backend/admin-api/src/main/resources/application.yml}）⇒ 无码时两键在 JSON 上**缺席**
 * （不是 {@code key: null}）；与「值为 null」在消费方**语义等价**（{@code ?? null}）。
 * 故凡断言线上 JSON 形态的判据一律用 {@code productionMapper}（镜像该配置），不用裸 {@code new ObjectMapper()}。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("加工单读面两键 short_code / scan_url（issue #6867 / B3）")
class ProcessingOrderReadFaceShortCodeTest {

    private static final Long TENANT = 1L;
    private static final Long OTHER_TENANT = 2L;
    /** 稳定域名（配置缺省值；与 {@code ProductionServicePartCodeTest.STABLE_BASE} 同源同字面）。 */
    private static final String STABLE_BASE = "https://app.migaozn.com";
    private static final String SHORT_CODE = "7K3M9QP2";

    @Mock
    private ProcessingOrderMapper processingOrderMapper;
    @Mock
    private OrderMapper orderMapper;
    @Mock
    private OrderItemMapper orderItemMapper;
    @Mock
    private ProcessingItemMapper processingItemMapper;
    @Mock
    private OrderService orderService;
    @Mock
    private ProductionService productionService;
    @Mock
    private ProductionOperationQueryService productionOperationQueryService;
    @Mock
    private ProductionOperationQtyClient productionOperationQtyClient;

    private final ObjectMapper objectMapper = new ObjectMapper();

    /**
     * **线上同源** mapper：镜像 {@code backend/admin-api/src/main/resources/application.yml} 的
     * {@code spring.jackson.default-property-inclusion: non_null}（Spring Boot 落到
     * {@code ObjectMapper.setSerializationInclusion(NON_NULL)} ⇒ null 属性与 null Map 值都不下发）。
     *
     * <p>⚠️ 裸 {@code new ObjectMapper()} 的 inclusion 是 {@code ALWAYS}，**不是**线上形态 ——
     * 「无码 ⇒ 键仍在且为 null」只在裸 mapper 上成立（issue #6890 实测：单测绿、线上形态相反）。</p>
     */
    private final ObjectMapper productionMapper =
            new ObjectMapper().setSerializationInclusion(JsonInclude.Include.NON_NULL);

    private ProcessingOrderService service;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        // LambdaQueryWrapper 构建需 TableInfo（同 ProcessingOrderServiceTest / 详情端点测试的做法）
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(assistant, Order.class);
        TableInfoHelper.initTableInfo(assistant, ProcessingOrder.class);

        service = new ProcessingOrderService(
                processingOrderMapper, orderMapper, orderItemMapper, processingItemMapper,
                orderService, objectMapper, productionService,
                productionOperationQueryService, productionOperationQtyClient);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ────────────────────────────────────────────── 夹具

    /** 本租户的加工单（`shortCode` 为 null = 存量行 / 未实例化）。 */
    private ProcessingOrder po(String shortCode) {
        return ProcessingOrder.builder()
                .id("po-1")
                .tenantId(TENANT)
                .orderId("order-001")
                .processingOrderNo("JG-20260912-0001")
                .status("issued")
                .shortCode(shortCode)
                .qrToken("0123456789abcdef0123456789abcdef")
                .build();
    }

    private Order order() {
        return Order.builder()
                .id("order-001")
                .tenantId(TENANT)
                .orderNo("ORD-20260912-0001")
                .status("producing")
                .customerName("张三")
                .build();
    }

    // ────────────────────────────────────────────── ① 有码 ⇒ 两键逐值正确

    @Test
    @DisplayName("① 有码：short_code = 短码本体；scan_url = {base}/o/{短码}（服务端拼装）")
    void bothKeysCarryTheCodeWhenItExists() {
        when(processingOrderMapper.selectOne(any())).thenReturn(po(SHORT_CODE));
        when(orderMapper.selectById("order-001")).thenReturn(order());

        ProcessingOrderResponse resp = service.getDetail("po-1", TENANT);

        assertThat(resp.getShortCode()).isEqualTo(SHORT_CODE);
        assertThat(resp.getScanUrl()).isEqualTo(STABLE_BASE + "/o/" + SHORT_CODE);
    }

    @Test
    @DisplayName("①b 键名是冻结的 snake_case（short_code / scan_url）—— 不是 Jackson 默认的 camelCase")
    void jsonKeysAreTheFrozenSnakeCaseNames() throws Exception {
        when(processingOrderMapper.selectOne(any())).thenReturn(po(SHORT_CODE));
        when(orderMapper.selectById("order-001")).thenReturn(order());

        JsonNode node = objectMapper.valueToTree(service.getDetail("po-1", TENANT));

        assertThat(node.has("short_code")).as("键名冻结：消费方读 processingOrder.short_code").isTrue();
        assertThat(node.has("scan_url")).as("键名冻结：消费方读 processingOrder.scan_url").isTrue();
        assertThat(node.get("short_code").asText()).isEqualTo(SHORT_CODE);
        assertThat(node.get("scan_url").asText()).isEqualTo(STABLE_BASE + "/o/" + SHORT_CODE);
        // 负控：camelCase 键**不得**同时存在（两套键名 = 第二份会漂的口径）
        assertThat(node.has("shortCode")).as("不得同时下发 camelCase 键").isFalse();
        assertThat(node.has("scanUrl")).as("不得同时下发 camelCase 键").isFalse();
    }

    @Test
    @DisplayName("①c 列表读路与详情读路同源：list 的每一行也带两键")
    void listCarriesBothKeysToo() {
        when(processingOrderMapper.selectList(any())).thenReturn(List.of(po(SHORT_CODE)));
        when(orderMapper.selectBatchIds(anyCollection())).thenReturn(List.of(order()));

        List<ProcessingOrderResponse> rows = service.list(null, null, TENANT);

        assertThat(rows).hasSize(1);
        assertThat(rows.get(0).getShortCode()).isEqualTo(SHORT_CODE);
        assertThat(rows.get(0).getScanUrl()).isEqualTo(STABLE_BASE + "/o/" + SHORT_CODE);
    }

    @Test
    @DisplayName("①d 域名走既有配置源：换 base（带尾斜杠）⇒ scan_url 跟着换，且不产出 `//`")
    void scanUrlIsAssembledServerSideFromTheExistingConfigSource() {
        ReflectionTestUtils.setField(service, "shortLinkBaseUrl", "https://staging.example.com/");
        when(processingOrderMapper.selectOne(any())).thenReturn(po(SHORT_CODE));
        when(orderMapper.selectById("order-001")).thenReturn(order());

        assertThat(service.getDetail("po-1", TENANT).getScanUrl())
                .as("拼装只此一份：换域名 ⇒ 纸上的码随之换（服务端拼，前端不拼）")
                .isEqualTo("https://staging.example.com/o/" + SHORT_CODE);
    }

    // ────── ② 无码：DTO 上两键恒在且为 null；**线上 JSON 上两键缺席**（全局 non_null）—— 负控

    @Test
    @DisplayName("② 无码（存量行 short_code = NULL）：两键**都在**且为 null —— 不省键、不折成 \"\"、不造 /o/null")
    void missingShortCodeStillCarriesBothKeysAsNull() {
        when(processingOrderMapper.selectOne(any())).thenReturn(po(null));
        when(orderMapper.selectById("order-001")).thenReturn(order());

        ProcessingOrderResponse resp = service.getDetail("po-1", TENANT);

        // 逐值：两键都在，且都是 null（不是 ""，也不是 "/o/null"）
        assertThat(resp.getShortCode()).as("无码 ⇒ short_code 为 null").isNull();
        assertThat(resp.getScanUrl()).as("无码 ⇒ scan_url 为 null（不造 /o/null 假码）").isNull();
    }

    @Test
    @DisplayName("②b 无码的**线上 JSON 形态**：全局 non_null ⇒ 两键**缺席**（不是 key: null）；消费方 ?? null 等价")
    void missingShortCodeKeysAreAbsentInJsonUnderProductionInclusion() throws Exception {
        when(processingOrderMapper.selectOne(any())).thenReturn(po(null));
        when(orderMapper.selectById("order-001")).thenReturn(order());

        JsonNode node = productionMapper.valueToTree(service.getDetail("po-1", TENANT));

        // 负控①：线上同源形态 —— 值为 null ⇒ 键缺席（`non_null`；实测 null 属性与 null Map 值都不下发）
        assertThat(node.has("short_code")).as("线上 non_null ⇒ 无码时 short_code 键缺席").isFalse();
        assertThat(node.has("scan_url")).as("线上 non_null ⇒ 无码时 scan_url 键缺席").isFalse();
        // 消费方负控：缺席解析成「没有码」——`path(...)` 给 MissingNode，`?? null` 给 null，两者等价
        assertThat(node.path("short_code").isMissingNode()).as("消费方视角：缺席 == null").isTrue();
        assertThat(node.path("short_code").asText("")).as("不得折成空串").isEmpty();
        // 负控②：拼出 /o/null ⇒ 红（原文里任何位置出现这个串都算）
        assertThat(node.toString()).as("绝不产出 /o/null 这种假码").doesNotContain("/o/null");
    }

    @Test
    @DisplayName("②b' 有码的线上 JSON 形态：两键都在且有值（正向对照，证明缺席不是「键从来没下发过」）")
    void presentShortCodeKeysAreInJsonUnderProductionInclusion() {
        when(processingOrderMapper.selectOne(any())).thenReturn(po(SHORT_CODE));
        when(orderMapper.selectById("order-001")).thenReturn(order());

        JsonNode node = productionMapper.valueToTree(service.getDetail("po-1", TENANT));

        assertThat(node.path("short_code").asText()).as("有码 ⇒ short_code 键在且有值").isEqualTo(SHORT_CODE);
        assertThat(node.path("scan_url").asText()).as("有码 ⇒ scan_url 键在且有值")
                .isEqualTo(STABLE_BASE + "/o/" + SHORT_CODE);
    }

    @Test
    @DisplayName("②c 无码的列表行同样两键恒在且为 null（不是「详情修了、列表漏了」）")
    void listRowsAlsoCarryBothKeysWhenCodeIsMissing() {
        when(processingOrderMapper.selectList(any())).thenReturn(List.of(po(null)));
        when(orderMapper.selectBatchIds(anyCollection())).thenReturn(List.of(order()));

        List<ProcessingOrderResponse> rows = service.list(null, null, TENANT);

        assertThat(rows).hasSize(1);
        assertThat(rows.get(0).getShortCode()).isNull();
        assertThat(rows.get(0).getScanUrl()).isNull();
    }

    @Test
    @DisplayName("②d 撤销（qr_token 置 NULL）**不**让两键变 null —— 已打印的纸不作废")
    void revokedTokenDoesNotBlankTheTwoKeys() {
        ProcessingOrder revoked = po(SHORT_CODE);
        revoked.setQrToken(null); // 撤销 = token 置 NULL，短码不碰（B1 的写面语义）
        when(processingOrderMapper.selectOne(any())).thenReturn(revoked);
        when(orderMapper.selectById("order-001")).thenReturn(order());

        ProcessingOrderResponse resp = service.getDetail("po-1", TENANT);

        assertThat(resp.getShortCode()).isEqualTo(SHORT_CODE);
        assertThat(resp.getScanUrl()).isEqualTo(STABLE_BASE + "/o/" + SHORT_CODE);
    }

    // ────────────────────────────────────────────── ③ 零新增查询

    @Test
    @DisplayName("③ 详情：两键装配**零新增 DB 查询**（既有两次读各一次，不多一次）")
    void readFaceAddsNoQueryForTheTwoKeys() {
        when(processingOrderMapper.selectOne(any())).thenReturn(po(SHORT_CODE));
        when(orderMapper.selectById("order-001")).thenReturn(order());

        service.getDetail("po-1", TENANT);

        // 既有查询的调用次数/形态**不增**：加工单一次、订单一次
        verify(processingOrderMapper, times(1)).selectOne(any());
        verify(orderMapper, times(1)).selectById("order-001");
        verify(orderMapper, never()).selectBatchIds(anyCollection());
        // 「为这两键新增一次查询」的形态全部为 0 次
        verify(processingOrderMapper, never()).selectByShortCode(anyString(), anyLong());
        verify(processingOrderMapper, never()).selectById(anyString());
        // 未实例化的读路一个 mapper 都不该碰（`po` 已在手 ⇒ 不存在「顺手查一下工序」）
        verifyNoInteractions(orderItemMapper, processingItemMapper);
    }

    @Test
    @DisplayName("③b 列表：两键装配仍是一次批量取订单（不回归 N+1），短码不触发任何额外读")
    void listAddsNoQueryForTheTwoKeys() {
        when(processingOrderMapper.selectList(any())).thenReturn(List.of(po(SHORT_CODE), po(null)));
        when(orderMapper.selectBatchIds(anyCollection())).thenReturn(List.of(order()));

        service.list(null, null, TENANT);

        verify(orderMapper, times(1)).selectBatchIds(anyCollection());
        verify(orderMapper, never()).selectById(anyString());
        verify(processingOrderMapper, never()).selectByShortCode(anyString(), anyLong());
    }

    // ────────────────────────────────────────────── ④ 租户隔离

    @Test
    @DisplayName("④ 跨租户：别的租户解析不到这张加工单 ⇒ 既不返回两键、也不泄露短码")
    void crossTenantCannotReadTheTwoKeys() {
        // 租户过滤在解析里（TenantLineInnerInterceptor / 显式 tenant_id 条件）——
        // 本租户上下文下查别租户的 po ⇒ 解析为 null；订单也解析不到 ⇒ 404
        TenantContext.setTenantId(OTHER_TENANT);
        when(processingOrderMapper.selectOne(any())).thenReturn(null);
        when(orderMapper.selectOne(any())).thenReturn(null);

        try {
            service.getDetail("po-1", OTHER_TENANT);
            assertThat(false).as("跨租户读必须 404（不得静默返回 null 数据）").isTrue();
        } catch (com.migao.admin.exception.BusinessException ex) {
            assertThat(ex.getCode()).isEqualTo("NOT_FOUND");
        } finally {
            TenantContext.setTenantId(TENANT);
        }

        // 短码/scan_url 一个字节都没下发（不在任何响应里）
        verify(processingOrderMapper, never()).selectByShortCode(anyString(), anyLong());
    }

    @Test
    @DisplayName("④b 本租户有码、别租户上下文下读到的是「没有这张单」（不是别人的短码）")
    void otherTenantSeeingNoRowGetsNoCode() {
        // 行级隔离由 SQL 的 tenant_id 条件承担（④c 判它真进了条件）⇒ 这里模拟「别租户查不到行」：
        // 第 1 次解析（别租户）→ null、订单也解析不到 ⇒ data null；第 2 次（本租户）→ 有行。
        when(processingOrderMapper.selectOne(any())).thenReturn(null, po(SHORT_CODE));
        when(orderMapper.selectOne(any())).thenReturn(order());
        when(orderMapper.selectById("order-001")).thenReturn(order());

        assertThat(service.getDetail("po-1", OTHER_TENANT)).as("别租户：无行 ⇒ data null").isNull();

        ProcessingOrderResponse mine = service.getDetail("po-1", TENANT);
        assertThat(mine.getShortCode()).isEqualTo(SHORT_CODE);
        assertThat(mine.getScanUrl()).isEqualTo(STABLE_BASE + "/o/" + SHORT_CODE);
    }

    @Test
    @DisplayName("④c 租户 id 显式进解析条件（不是只靠拦截器兜底）")
    void tenantIdIsPartOfTheResolutionCondition() {
        when(processingOrderMapper.selectOne(any())).thenReturn(po(SHORT_CODE));
        when(orderMapper.selectById("order-001")).thenReturn(order());

        service.getDetail("po-1", TENANT);

        org.mockito.ArgumentCaptor<com.baomidou.mybatisplus.core.conditions.Wrapper<ProcessingOrder>> captor =
                org.mockito.ArgumentCaptor.forClass(com.baomidou.mybatisplus.core.conditions.Wrapper.class);
        verify(processingOrderMapper).selectOne(captor.capture());
        // 条件里必须出现 tenant_id 与 deleted（软删）；SQL 片段形状是既有形态，本包不改它
        String sql = captor.getValue().getCustomSqlSegment();
        assertThat(sql).as("解析必须显式带 tenant_id（不是只靠全局拦截器）").contains("tenant_id");
        assertThat(sql).as("解析必须显式带 deleted = 0").contains("deleted");
    }
}
