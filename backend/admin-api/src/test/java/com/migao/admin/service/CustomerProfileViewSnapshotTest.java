// case_ids: CU-010

package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.migao.admin.entity.CustomerProfile;
import com.migao.admin.mapper.CustomerProfileMapper;
import com.migao.admin.mapper.CustomerSegmentMapper;
import com.migao.admin.mapper.CustomerSegmentMemberMapper;
import com.migao.admin.mapper.CustomerTagMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.SessionMapper;
import com.migao.admin.mapper.SessionMessageMapper;
import com.migao.admin.support.fieldtruth.CustomerProfileFieldTruth;
import com.migao.admin.support.fieldtruth.FieldTruth;
import com.migao.admin.support.fieldtruth.FieldTruthRegistry;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

/**
 * 客户画像视图的**装配腿**（族 3 · 包 3，issue #5456）—— admin-api 侧判据。
 *
 * <p>视图语义（逐字段三态 / 「未知」≠「0」/ 确定性 / 租户回显）的判据在 ai-agent 侧的
 * {@code backend/ai-agent-service/tests/test_briefing_customer_profile.py}；本文件盯的是**装配契约**：</p>
 *
 * <ol>
 *   <li><b>声明的运输由 #5362 的注册表现取</b>：字段集 / 真值侧 / 证据化原因逐字段一致
 *       （装配层与视图两侧都不许另写一份）；</li>
 *   <li><b>行键集 ≡ 声明的字段集</b>（含**线上 JSON 形态** ⇒ 视图侧按声明的字段名取值一定取得到）。
 *       ⚠️ 这条判据**实测红过一次**：最初把实体直接交给 Jackson 序列化时，{@code getRScore} 这类
 *       getter 被折叠成全小写（{@code rscore}）⇒ 与声明对不上（#5456 现场教训）；</li>
 *   <li>🔴 <b>「无真值」的字段在读面被遮蔽</b>（DB 列默认值 / 建档种子不得以真值形态流出去），
 *       而「有真值」的字段**原样保留**（不得整表一刀切）；</li>
 *   <li><b>有界 + 截断显式</b>（行数上限收敛到内核上限，多取一行只为判定截断）。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
class CustomerProfileViewSnapshotTest {

    @InjectMocks
    private CustomerService customerService;

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

    /** 真实 ObjectMapper：判据 2 要的正是「线上 JSON 后的键集」（mock 掉它等于把判据测没了）。 */
    private final ObjectMapper objectMapper = new ObjectMapper().registerModule(new JavaTimeModule());

    private static final TypeReference<Map<String, Object>> ROW_TYPE = new TypeReference<>() {
    };

    private static final String TABLE = CustomerProfileFieldTruth.TABLE;

    private static CustomerProfile profile(String id) {
        return CustomerProfile.builder()
                .id(id)
                .tenantId(1L)
                .wechatNickname("张三")
                .phone("13800138000")
                .build();
    }

    /** 行在**线上**的形态（JSON 往返一次）：键集/值域都要与内存里的一致。 */
    private Map<String, Object> onWire(Map<String, Object> row) throws Exception {
        return objectMapper.readValue(objectMapper.writeValueAsString(row), ROW_TYPE);
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> block(Map<String, Object> snapshot, String key) {
        return (Map<String, Object>) snapshot.get(key);
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> arrayMeta(Map<String, Object> snapshot) {
        return (Map<String, Object>) block(snapshot, "row_meta").get(TABLE);
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> rowsOf(Map<String, Object> snapshot) {
        return (List<Map<String, Object>>) snapshot.get(TABLE);
    }

    @SuppressWarnings("unchecked")
    private static Set<String> declaredInSnapshot(Map<String, Object> snapshot) {
        return new TreeSet<>((Collection<String>) block(snapshot, "row_fields").get(TABLE));
    }

    private Map<String, Object> snapshotOf(List<CustomerProfile> profiles, int limit) {
        when(customerProfileMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(profiles);
        return customerService.profileViewSnapshot(1L, limit);
    }

    // ── 判据 1：声明的运输由注册表现取 ──────────────────────────────────────

    @Test
    @DisplayName("真值声明的运输：字段集 / 真值侧 / 原因逐字段等于 #5362 的注册表声明")
    void payload_is_rendered_from_the_registry_declaration() {
        FieldTruth.Declaration declaration = FieldTruthRegistry.customerProfile();
        Map<String, Object> payload = declaration.payload();

        // 注册表就是从那份声明装配来的（不是第二份）：同号同源
        assertThat(FieldTruthRegistry.customerProfile()).isSameAs(CustomerProfileFieldTruth.declaration());
        assertThat(payload.keySet()).isEqualTo(declaration.declaredFields());
        for (String field : declaration.declaredFields()) {
            Map<?, ?> item = (Map<?, ?>) payload.get(field);
            assertThat(item.get("truth")).as("%s 的真值侧", field)
                    .isEqualTo(declaration.truthOf(field).wireName());
            assertThat(item.get("reason")).as("%s 的证据化原因", field)
                    .isEqualTo(declaration.entry(field).reason());
        }
        // 两侧都必须非空：整表当有真值 / 整表当无真值都会让这里红（「不得整表一刀切」的机制前提）
        assertThat(declaration.hasTruthFields()).isNotEmpty();
        assertThat(declaration.noTruthFields()).isNotEmpty();
        assertThat(declaration.hasTruthFields()).doesNotContainAnyElementsOf(declaration.noTruthFields());
    }

    // ── 判据 2：行键集 ≡ 声明的字段集（含线上 JSON 形态）──────────────────

    @Test
    @DisplayName("快照形态齐全；行键集（内存 + 线上 JSON）逐字等于声明的字段集")
    void snapshot_shape_and_row_keys_follow_the_declaration() throws Exception {
        Map<String, Object> snapshot = snapshotOf(List.of(profile("c1")), 50);

        assertThat(snapshot).containsKeys("row_fields", "row_meta", "field_truth", TABLE);
        assertThat(declaredInSnapshot(snapshot))
                .isEqualTo(CustomerProfileFieldTruth.declaration().declaredFields());
        assertThat(block(snapshot, "field_truth").keySet()).containsExactly(TABLE);
        assertThat(rowsOf(snapshot)).hasSize(1);

        Set<String> declared = CustomerProfileFieldTruth.declaration().declaredFields();
        assertThat(new TreeSet<>(rowsOf(snapshot).get(0).keySet())).as("内存行键集").isEqualTo(declared);
        // 🔴 线上形态也要对得上：视图侧是按**声明的字段名**去行里取值的
        assertThat(new TreeSet<>(onWire(rowsOf(snapshot).get(0)).keySet())).as("线上行键集").isEqualTo(declared);
    }

    // ── 判据 3：无真值遮蔽 + 有真值保留（两个方向都钉）─────────────────────

    @Test
    @DisplayName("🔴 无真值的字段在读面一律 null（DB 默认值不得冒充真值）；有真值的字段原样保留")
    void no_truth_fields_are_masked_and_has_truth_fields_survive() {
        FieldTruth.Declaration declaration = FieldTruthRegistry.customerProfile();
        CustomerProfile dirty = profile("c1");
        // #5362 点名的形态：DB 列默认值 / 建档种子常量（客服没填也「有值」）
        dirty.setRScore(0);
        dirty.setTotalOrders(0);
        dirty.setAvgOrderValue(BigDecimal.ZERO);
        dirty.setLifecycleStage("new");

        Map<String, Object> snapshot = snapshotOf(List.of(dirty), 50);
        Map<String, Object> row = rowsOf(snapshot).get(0);

        for (String field : declaration.noTruthFields()) {
            assertThat(row.get(field)).as("无真值字段 %s 不得以真值形态出现", field).isNull();
        }
        // 反向：有真值的字段**不得**被一起抹掉（整表一刀切的形态判据）
        assertThat(row).containsEntry("phone", "13800138000");
        assertThat(row).containsEntry("wechatNickname", "张三");
    }

    // ── 判据 4：有界 + 截断显式 ────────────────────────────────────────────

    @Test
    @DisplayName("有界：行数上限收敛到内核上限；截断显式（多取一行只为判定截断）")
    void rows_are_bounded_and_truncation_is_explicit() {
        List<CustomerProfile> many = new ArrayList<>();
        for (int index = 0; index < 51; index++) {
            many.add(profile("c" + index));
        }

        Map<String, Object> snapshot = snapshotOf(many, 50);

        assertThat(rowsOf(snapshot)).hasSize(50);
        assertThat(arrayMeta(snapshot)).containsEntry("limit", 50)
                .containsEntry("count", 50)
                .containsEntry("truncated", true);
    }

    @Test
    @DisplayName("有界：limit 超过内核上限时收敛（<1 收敛到 1）—— 上游传什么都不许无界")
    void limit_is_clamped_to_the_kernel_bound() {
        Map<String, Object> clamped = snapshotOf(List.of(profile("c1")), 100000);
        assertThat(arrayMeta(clamped)).containsEntry("limit", DailyBriefingService.SNAPSHOT_ROW_LIMIT);
        assertThat(arrayMeta(clamped)).containsEntry("truncated", false);

        Map<String, Object> floor = snapshotOf(List.of(profile("c1")), 0);
        assertThat(arrayMeta(floor)).containsEntry("limit", 1);
        // 只有一行、上限被收敛到 1 ⇒ 没被截断（截断判据不是「上限小就等于截断」）
        assertThat(arrayMeta(floor)).containsEntry("truncated", false);
    }
}