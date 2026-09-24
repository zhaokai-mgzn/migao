// case_ids: CU-002

package com.migao.admin.service;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.CustomerProfile;
import com.migao.admin.entity.CustomerSegmentMember;
import com.migao.admin.mapper.CustomerProfileMapper;
import com.migao.admin.mapper.CustomerSegmentMemberMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.SessionMapper;
import com.migao.admin.mapper.SessionMessageMapper;
import com.migao.admin.support.fieldtruth.CustomerProfileFieldTruth;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

/**
 * 暴露面：声明为「无真值」的字段<b>不得以真值形态</b>出现在对外返回体里（issue #5362）。
 *
 * <p><b>缺陷形态（修前）</b>：{@code r_score} 等列的 DDL 是 {@code DEFAULT 0}，
 * 而 {@code GET /api/admin/customers} 直接把实体序列化出去 ⇒ 任何消费方（页面 / Agent / 第三方）
 * 拿到的 {@code rfmTotalScore: 0}、{@code totalConsumption: 0.00}、
 * {@code nextPurchasePredictionDays: 30} 都是「看起来像真数据」的占位值。
 * {@code product_skus.avg_cost} 的既有口径（{@code NULL = 未知，不猜 0}）就是本单照抄的答案。
 *
 * <p><b>本文件断言的是行为</b>（走 {@link CustomerService} 的真实读路径），
 * 声明与源码写入点的一致性由 {@code CustomerProfileFieldTruthGateTest} 机械核对 ——
 * 两份产物互相独立，任一方漂移都会红。
 */
@ExtendWith(MockitoExtension.class)
class CustomerProfileTruthExposureTest extends BaseServiceTest {

    private static final ObjectMapper JSON = new ObjectMapper();

    @InjectMocks
    private CustomerService customerService;

    @Mock
    private CustomerProfileMapper customerProfileMapper;
    @Mock
    private CustomerSegmentMemberMapper customerSegmentMemberMapper;
    @Mock
    private OrderMapper orderMapper;
    @Mock
    private SessionMapper sessionMapper;
    @Mock
    private SessionMessageMapper sessionMessageMapper;

    /** 读路径返回的行：无真值字段一律带「DB 列默认值 / 建档种子」形态的值（= 修前商家与 Agent 看到的东西）。 */
    private static CustomerProfile dbDefaultShapedRow() {
        return CustomerProfile.builder()
                .id("cust-001")
                .tenantId(1L)
                .wechatNickname("测试客户")
                .phone("13800138000")
                .vipLevel("normal")
                .customerStatus("active")
                .sourceChannel("wechat_mini")
                // ↓ schema.sql 的 DEFAULT：r_score/f_score/m_score/rfm_total_score = 0、
                //   total_consumption/total_refund_amount/avg_order_value = 0.00、
                //   repurchase_rate/churn_risk_score = 0.0000、next_purchase_prediction_days = 30
                .rScore(0).fScore(0).mScore(0).rfmTotalScore(0)
                .totalOrders(1)
                .totalConsumption(BigDecimal.ZERO)
                .totalRefundAmount(BigDecimal.ZERO)
                .avgOrderValue(BigDecimal.ZERO)
                .repurchaseRate(new BigDecimal("0.0000"))
                .churnRiskScore(new BigDecimal("0.0000"))
                .nextPurchasePredictionDays(30)
                .lifecycleStage("new")
                .build();
    }

    private static Page<CustomerProfile> pageOf(CustomerProfile row) {
        Page<CustomerProfile> page = new Page<>(1, 10);
        page.setRecords(List.of(row));
        page.setTotal(1);
        return page;
    }

    private static Set<String> noTruthFields() {
        return CustomerProfileFieldTruth.declaration().noTruthFields();
    }

    @Test
    @DisplayName("客户列表：无真值字段一律回 null，有真值字段原样保留（不是整表一刀切）")
    void customerListHidesNoTruthFields() {
        when(customerProfileMapper.selectPage(any(Page.class), any()))
                .thenReturn(pageOf(dbDefaultShapedRow()));

        PageResponse<CustomerProfile> response = customerService.getCustomerPage(1, 10, null, null, null, 1L);
        CustomerProfile row = response.getItems().get(0);

        for (String field : noTruthFields()) {
            assertThat(valueOf(row, field))
                    .as("字段 %s 已声明「无真值」⇒ 读面必须回 null（未知），"
                            + "不得把 DB 默认值 0 / 30 / 'new' 当成真数据", field)
                    .isNull();
        }
        // 同表并存：有真值字段一个都不许被抹掉
        assertThat(row.getVipLevel()).isEqualTo("normal");
        assertThat(row.getCustomerStatus()).isEqualTo("active");
        assertThat(row.getSourceChannel()).isEqualTo("wechat_mini");
        assertThat(row.getPhone()).isEqualTo("13800138000");
        assertThat(row.getWechatNickname()).isEqualTo("测试客户");
        assertThat(row.getId()).isEqualTo("cust-001");
    }

    @Test
    @DisplayName("客户详情：嵌套 profile 同样遮蔽（Agent 读的就是这一份）")
    void customerDetailHidesNoTruthFields() {
        when(customerProfileMapper.selectById("cust-001")).thenReturn(dbDefaultShapedRow());
        when(orderMapper.selectList(any())).thenReturn(List.of());
        when(sessionMapper.selectList(any())).thenReturn(List.of());

        Map<String, Object> detail = customerService.getCustomerDetail("cust-001");
        CustomerProfile profile = (CustomerProfile) detail.get("profile");

        assertThat(profile).isNotNull();
        assertThat(profile.getRfmTotalScore()).isNull();
        assertThat(profile.getTotalConsumption()).isNull();
        assertThat(profile.getNextPurchasePredictionDays()).isNull();
        assertThat(profile.getLifecycleStage()).isNull();
        assertThat(profile.getVipLevel()).isEqualTo("normal");
        assertThat(detail.get("orders")).isEqualTo(List.of());
    }

    @Test
    @DisplayName("更新客户：返回体同样遮蔽（否则 PUT 的响应又变成真值形态）")
    void updateCustomerResponseHidesNoTruthFields() {
        when(customerProfileMapper.selectById("cust-001")).thenReturn(dbDefaultShapedRow());
        when(customerProfileMapper.updateById(any(CustomerProfile.class))).thenReturn(1);

        CustomerProfile request = new CustomerProfile();
        request.setPhone("13900139000");

        CustomerProfile updated = customerService.updateCustomer("cust-001", request);

        assertThat(updated.getPhone()).as("有真值字段按原语义落库/返回").isEqualTo("13900139000");
        assertThat(updated.getTotalOrders()).isNull();
        assertThat(updated.getAvgOrderValue()).isNull();
        assertThat(updated.getLifecycleStage()).isNull();
    }

    @Test
    @DisplayName("分群成员列表：同一个实体走哪条读路径都遮蔽")
    void segmentMembersHideNoTruthFields() {
        when(customerSegmentMemberMapper.selectList(any()))
                .thenReturn(List.of(CustomerSegmentMember.builder().customerId("cust-001").build()));
        when(customerProfileMapper.selectPage(any(Page.class), any()))
                .thenReturn(pageOf(dbDefaultShapedRow()));

        PageResponse<CustomerProfile> response = customerService.getSegmentMembers("seg-001", 1, 10);

        assertThat(response.getItems().get(0).getRepurchaseRate()).isNull();
        assertThat(response.getItems().get(0).getChurnRiskScore()).isNull();
        assertThat(response.getItems().get(0).getVipLevel()).isEqualTo("normal");
    }

    @Test
    @DisplayName("对外返回体（JSON）：无真值字段是 null，不是 0 / 30 / \"new\"")
    void serializedBodyCarriesNullsNotPlaceholders() throws Exception {
        when(customerProfileMapper.selectPage(any(Page.class), any()))
                .thenReturn(pageOf(dbDefaultShapedRow()));
        CustomerProfile row = customerService.getCustomerPage(1, 10, null, null, null, 1L).getItems().get(0);

        // 裸 ObjectMapper 不注册 JavaTimeModule ⇒ 夹具刻意不设 OffsetDateTime 字段
        // （v1.51.0 §17.3：OffsetDateTime 经裸 ObjectMapper 当场抛）
        Map<String, Object> body = JSON.convertValue(row, new TypeReference<Map<String, Object>>() {
        });

        for (String field : noTruthFields()) {
            assertThat(body.get(field))
                    .as("响应体里的 %s 必须是 null（未知），否则消费方会把占位值当真值", field)
                    .isNull();
        }
        assertThat(body)
                .containsEntry("vipLevel", "normal")
                .containsEntry("customerStatus", "active")
                .containsEntry("phone", "13800138000");
    }

    @Test
    @DisplayName("边界：遮蔽只发生在读面 —— 建档路径的种子值照写（不改写入语义）")
    void creationSeedsAreUntouched() {
        when(customerProfileMapper.selectOne(any())).thenReturn(null);
        when(customerProfileMapper.insert(any(CustomerProfile.class))).thenAnswer(invocation -> {
            CustomerProfile inserted = invocation.getArgument(0);
            inserted.setId("cust-new");
            return 1;
        });

        CustomerProfile created = customerService.createFromSession(1L, "openid_new", "新客户", "wechat_mini");

        assertThat(created.getVipLevel()).isEqualTo("normal");
        assertThat(created.getCustomerStatus()).isEqualTo("active");
        assertThat(created.getLifecycleStage()).as("建档语义未改（A1 补计算时再动）").isEqualTo("new");
        assertThat(created.getTotalOrders()).isEqualTo(0);
        assertThat(created.getTotalConsumption()).isEqualByComparingTo(BigDecimal.ZERO);
    }

    private static Object valueOf(CustomerProfile profile, String field) {
        try {
            return CustomerProfile.class.getMethod("get" + Character.toUpperCase(field.charAt(0)) + field.substring(1))
                    .invoke(profile);
        } catch (ReflectiveOperationException e) {
            throw new IllegalStateException("字段 " + field + " 无 getter（声明与实体已漂移）", e);
        }
    }
}