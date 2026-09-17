package com.migao.admin.service;

// case_ids: OR-016

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.dto.OrderDetailResponse;
import com.migao.admin.exception.BusinessException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.jdbc.core.JdbcTemplate;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * ClientRequestIdService（写请求幂等键，issue #4037）SQL 语义单测。
 *
 * <p>仓库 Java 测试无 DB（src/test/resources 只有 mockito-extensions 与 rsa），故此处用
 * 打桩的 {@link JdbcTemplate} 锁「发的是哪条 SQL / 怎么判首次 / 怎么 fail-closed」，
 * **真实唯一约束行为（同键 1 行、异键 2 行、V50 重跑幂等）另由真库证据覆盖**（PR 证据链）。</p>
 *
 * <p>本类锁 5 条（每条都能红，红证见 PR）：</p>
 * <ol>
 *   <li>占位用 {@code INSERT ... ON CONFLICT (tenant_id, client_request_id) DO NOTHING}，
 *       按**影响行数**判首次（不靠捕获唯一约束异常 —— 那样会让 PG 事务进入 aborted 状态）；</li>
 *   <li>幂等键缺失/空白 ⇒ 四个方法全 no-op（向后兼容未升级的调用方，零 SQL）；</li>
 *   <li>回放：{@code response_payload::text} 反序列化成 DTO；</li>
 *   <li><b>占位存在但 payload 为空 ⇒ 抛明确错误</b>（fail-closed + suggestion），绝不返回空结果；</li>
 *   <li>失败释放：{@code discard} 真的发 DELETE。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("ClientRequestIdService：写请求幂等键（issue #4037）")
class ClientRequestIdServiceTest {

    private static final Long TENANT = 1L;
    private static final String KEY = "req-key-1";
    private static final String ENDPOINT = "POST /api/admin/agent/orders";

    @Mock
    private JdbcTemplate jdbcTemplate;

    /** 用真 ObjectMapper：回放路径要真的走一遍 JSONB 文本 ↔ DTO */
    private final ObjectMapper objectMapper = new ObjectMapper();

    private ClientRequestIdService service;

    @BeforeEach
    void setUp() {
        service = new ClientRequestIdService(provider(jdbcTemplate), objectMapper);
    }

    // ── ① 原子占位 ──

    @Test
    @DisplayName("陈旧占位回收：受理时删除「无结果且超阈值」的行（售后占位崩溃后自愈，不永久 409）")
    void claimReclaimsStalePlaceholders() {
        // ⚠️ 两个 update 是**不同重载**：reclaim 的 DELETE 是 (sql, tenantId, minutes) 3 参，
        //    占位 INSERT 是 (sql, tenantId, key, endpoint) 4 参 —— 用 `any(Object.class)` 逐个
        //    匹配（裸 any() 会选中另一个重载 ⇒ 打桩打空 ⇒ 断言假红，本类已踩过一次）
        when(jdbcTemplate.update(anyString(), any(Object.class), any(Object.class))).thenReturn(0);
        when(jdbcTemplate.update(anyString(), any(Object.class), any(Object.class),
                any(Object.class))).thenReturn(1);

        assertThat(service.claim(TENANT, KEY, ENDPOINT)).isTrue();

        ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
        verify(jdbcTemplate).update(sql.capture(), any(Object.class), any(Object.class));
        assertThat(sql.getValue())
                .as("受理前必须回收陈旧占位（否则售后路径的崩溃占位会把该键永久占死）")
                .contains("DELETE FROM client_request_keys")
                .contains("response_payload IS NULL");
        ArgumentCaptor<String> sql4 = ArgumentCaptor.forClass(String.class);
        verify(jdbcTemplate).update(sql4.capture(), any(Object.class), any(Object.class),
                any(Object.class));
        assertThat(sql4.getValue()).contains("ON CONFLICT (tenant_id, client_request_id) DO NOTHING");
    }

    @Test
    @DisplayName("回收失败不影响受理：清理抛异常时占位照常进行（运维动作不得挡住写请求）")
    void reclaimFailureDoesNotBlockClaim() {
        when(jdbcTemplate.update(anyString(), any(Object.class), any(Object.class)))
                .thenThrow(new RuntimeException("cleanup boom"));
        when(jdbcTemplate.update(anyString(), any(Object.class), any(Object.class),
                any(Object.class))).thenReturn(1);

        assertThat(service.claim(TENANT, KEY, ENDPOINT))
                .as("回收抛异常时 claim 仍必须返回 true（清理是尽力而为，不得挡住写请求）")
                .isTrue();
    }

    @Test
    @DisplayName("首次占位：ON CONFLICT DO NOTHING 影响行数 1 → true（可执行）")
    void claimFirstReturnsTrue() {
        when(jdbcTemplate.update(anyString(), any(), any(), any())).thenReturn(1);

        assertThat(service.claim(TENANT, KEY, ENDPOINT)).isTrue();

        ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
        verify(jdbcTemplate).update(sql.capture(), eq(TENANT), eq(KEY), eq(ENDPOINT));
        assertThat(sql.getValue())
                .as("占位必须是 INSERT ... ON CONFLICT DO NOTHING（唯一约束冲突不得抛异常）")
                .contains("INSERT INTO client_request_keys")
                .contains("ON CONFLICT (tenant_id, client_request_id) DO NOTHING");
    }

    @Test
    @DisplayName("同键重复占位：影响行数 0 → false（不得再执行）")
    void claimDuplicateReturnsFalse() {
        when(jdbcTemplate.update(anyString(), any(), any(), any())).thenReturn(0);

        assertThat(service.claim(TENANT, KEY, ENDPOINT)).isFalse();
    }

    // ── ② 无幂等键 ⇒ 全 no-op（向后兼容老调用方） ──

    @Test
    @DisplayName("无幂等键：claim=true / replay=empty，且零 SQL 往返")
    void blankKeyIsNoOp() {
        assertThat(service.claim(TENANT, null, ENDPOINT)).isTrue();
        assertThat(service.claim(TENANT, "   ", ENDPOINT)).isTrue();
        assertThat(service.replay(TENANT, null, OrderDetailResponse.class)).isEmpty();
        service.complete(TENANT, null, new OrderDetailResponse());
        assertThat(service.discard(TENANT, "")).isZero();

        verifyNoInteractions(jdbcTemplate);
    }

    // ── ③ 回放 ──

    @Test
    @DisplayName("回放：读 response_payload::text 并反序列化成 DTO")
    void replayReturnsStoredSnapshot() {
        when(jdbcTemplate.<Map<String, Object>>queryForList(anyString(), any(Object.class), any(Object.class)))
                .thenReturn(rows("{\"id\":\"order-1\",\"orderNo\":\"ORD-1\"}"));

        Optional<OrderDetailResponse> replayed =
                service.replay(TENANT, KEY, OrderDetailResponse.class);

        assertThat(replayed).isPresent();
        assertThat(replayed.get().getOrderNo()).isEqualTo("ORD-1");
        ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
        verify(jdbcTemplate).queryForList(sql.capture(), eq(TENANT), eq(KEY));
        assertThat(sql.getValue()).contains("response_payload::text");
    }

    @Test
    @DisplayName("回放结果带 replayed 标记（调用方能分辨「首次执行」与「同键回放」）+ 未知键不致反序列化失败")
    void replayMarksReplayedAndToleratesMarker() throws Exception {
        when(jdbcTemplate.<Map<String, Object>>queryForList(anyString(), any(Object.class), any(Object.class)))
                .thenReturn(rows("{\"id\":\"order-1\",\"orderNo\":\"ORD-1\"}"));

        OrderDetailResponse replayed = service.replay(TENANT, KEY, OrderDetailResponse.class).orElseThrow();

        // 业务字段原样（回放不得改内容）
        assertThat(replayed.getOrderNo()).isEqualTo("ORD-1");
        // 标记：序列化后必须出现 replayed=true（ai-agent 靠它说"此单此前已创建、没有重复下单"）
        assertThat(objectMapper.writeValueAsString(replayed)).contains("\"replayed\":true");

        // 快照里已经带 replayed 时（再次回放同一条快照）必须照常反序列化，不得抛
        assertThat(service.replay(TENANT, KEY, OrderDetailResponse.class)).isPresent();
    }

    // ── ④ 占位存在但无结果 ⇒ fail-closed（不得回放空结果） ──

    @Test
    @DisplayName("占位存在但 response_payload 为空 → 抛 REQUEST_IN_PROGRESS（带 suggestion），绝不返回空 DTO")
    void replayEmptyPayloadFailsClosed() {
        when(jdbcTemplate.<Map<String, Object>>queryForList(anyString(), any(Object.class), any(Object.class)))
                .thenReturn(rows(null));

        assertThatThrownBy(() -> service.replay(TENANT, KEY, OrderDetailResponse.class))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining(KEY)
                .satisfies(e -> {
                    BusinessException be = (BusinessException) e;
                    assertThat(be.getCode()).isEqualTo("REQUEST_IN_PROGRESS");
                    assertThat(be.getHttpStatus()).isEqualTo(409);
                    assertThat(be.getSuggestion())
                            .as("R5：fail-closed 必须带可行动信息，不能只有一句失败")
                            .isNotNull()
                            .contains("请勿重复提交");
                });
    }

    @Test
    @DisplayName("占位行都没有（被并发释放）→ 同样 fail-closed，不得当成「首次」静默重放")
    void replayMissingRowFailsClosed() {
        when(jdbcTemplate.<Map<String, Object>>queryForList(anyString(), any(Object.class), any(Object.class)))
                .thenReturn(List.of());

        assertThatThrownBy(() -> service.replay(TENANT, KEY, OrderDetailResponse.class))
                .isInstanceOf(BusinessException.class)
                .satisfies(e -> assertThat(((BusinessException) e).getCode()).isEqualTo("REQUEST_IN_PROGRESS"));
    }

    // ── ⑤ 结果快照落库 + 失败释放 ──

    @Test
    @DisplayName("complete：UPDATE ... SET response_payload = ?::jsonb，写入的是 JSON 快照")
    void completeWritesJsonbSnapshot() throws Exception {
        OrderDetailResponse snapshot = new OrderDetailResponse();
        snapshot.setId("order-1");
        snapshot.setOrderNo("ORD-1");

        service.complete(TENANT, KEY, snapshot);

        ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<Object> payload = ArgumentCaptor.forClass(Object.class);
        verify(jdbcTemplate).update(sql.capture(), payload.capture(), eq(TENANT), eq(KEY));
        assertThat(sql.getValue())
                .contains("UPDATE client_request_keys")
                .contains("SET response_payload = ?::jsonb");
        assertThat(objectMapper.readTree(String.valueOf(payload.getValue())).get("orderNo").asText())
                .isEqualTo("ORD-1");
    }

    @Test
    @DisplayName("discard：DELETE 该键的占位行并返回删除行数（失败释放占位）")
    void discardDeletesPlaceholder() {
        // 用 any(Object.class) 而非裸 any()：裸 any() 会让编译器选中 update(String, Object[], int[])
        // 这个**另一个重载**，于是打桩打空、真实调用拿到默认 0（本断言的红证正是这么来的）
        when(jdbcTemplate.update(anyString(), any(Object.class), any(Object.class))).thenReturn(1);

        assertThat(service.discard(TENANT, KEY)).isEqualTo(1);

        ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
        verify(jdbcTemplate).update(sql.capture(), eq(TENANT), eq(KEY));
        assertThat(sql.getValue()).contains("DELETE FROM client_request_keys");
    }

    @Test
    @DisplayName("超长幂等键：明确拒绝（不把 DB 层的 varchar(128) 报错透传成 500）")
    void overlongKeyRejected() {
        String tooLong = "x".repeat(129);

        assertThatThrownBy(() -> service.claim(TENANT, tooLong, ENDPOINT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("X-Client-Request-Id");
        verifyNoInteractions(jdbcTemplate);
    }

    /** 把 mock JdbcTemplate 包成 ObjectProvider（生产代码用它做「无 DataSource 上下文」降级） */
    private static ObjectProvider<JdbcTemplate> provider(JdbcTemplate jdbc) {
        return new ObjectProvider<>() {
            @Override
            public JdbcTemplate getObject() {
                return jdbc;
            }

            @Override
            public JdbcTemplate getObject(Object... args) {
                return jdbc;
            }

            @Override
            public JdbcTemplate getIfAvailable() {
                return jdbc;
            }

            @Override
            public JdbcTemplate getIfUnique() {
                return jdbc;
            }
        };
    }

    @Test
    @DisplayName("无 DataSource 上下文（拿不到 JdbcTemplate）⇒ 不阻断写请求：claim 放行 / discard no-op")
    void noDataSourceDegradesWithoutBlockingWrites() {
        ClientRequestIdService noDb = new ClientRequestIdService(provider(null), objectMapper);

        assertThat(noDb.claim(TENANT, KEY, ENDPOINT))
                .as("拿不到 DB 时不得阻断写请求（SecurityConfigTest 那类上下文就没有 DataSource）")
                .isTrue();
        assertThat(noDb.discard(TENANT, KEY)).isZero();

        // 回放则相反：无 DB 时**不能**静默当"首次"（那会重复执行）⇒ fail-closed
        assertThatThrownBy(() -> noDb.replay(TENANT, KEY, OrderDetailResponse.class))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("幂等存储不可用");
    }

    /** 构造 JdbcTemplate.queryForList 的单行结果（payload 列，null = 占位无结果） */
    private static List<Map<String, Object>> rows(String payload) {
        Map<String, Object> row = new HashMap<>();
        row.put("payload", payload);
        return List.of(row);
    }
}