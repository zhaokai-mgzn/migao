package com.migao.admin.controller;

import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.CustomerProfile;
import com.migao.admin.entity.CustomerTag;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.service.CustomerService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;
import java.util.Map;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * CustomerController 单元测试
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("CustomerController 客户管理测试")
class CustomerControllerTest extends BaseControllerTest {

    private MockMvc mockMvc;

    @Mock
    private CustomerService customerService;

    @InjectMocks
    private CustomerController customerController;

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        mockMvc = buildMockMvc(customerController);
    }

    @Override
    @AfterEach
    void baseTearDown() {
        super.baseTearDown();
    }

    @Nested
    @DisplayName("GET /api/admin/customers")
    class GetCustomers {

        @Test
        @DisplayName("分页查询客户列表 -> 200")
        void getCustomersPaginated() throws Exception {
            PageResponse<CustomerProfile> page = new PageResponse<>();
            page.setItems(List.of());
            page.setTotal(0L);
            when(customerService.getCustomerPage(anyLong(), anyLong(), any(), any(), any(), anyLong()))
                    .thenReturn(page);

            mockMvc.perform(get("/api/admin/customers"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true))
                    .andExpect(jsonPath("$.data.items").isArray());
        }

        @Test
        @DisplayName("支持渠道筛选 -> 200")
        void channelFilter() throws Exception {
            when(customerService.getCustomerPage(anyLong(), anyLong(), any(), any(), any(), anyLong()))
                    .thenReturn(new PageResponse<>());

            mockMvc.perform(get("/api/admin/customers").param("sourceChannel", "wechat_mini"))
                    .andExpect(status().isOk());
        }

        @Test
        @DisplayName("支持 VIP 等级筛选 -> 200")
        void vipLevelFilter() throws Exception {
            when(customerService.getCustomerPage(anyLong(), anyLong(), any(), any(), any(), anyLong()))
                    .thenReturn(new PageResponse<>());

            mockMvc.perform(get("/api/admin/customers").param("vipLevel", "vip1"))
                    .andExpect(status().isOk());
        }
    }

    @Nested
    @DisplayName("GET /api/admin/customers/{id}")
    class GetCustomer {

        @Test
        @DisplayName("查询客户详情 -> 200")
        void getCustomerDetail() throws Exception {
            Map<String, Object> detail = Map.of("id", "cust-1", "wechatNickname", "测试用户");
            when(customerService.getCustomerDetail(anyString())).thenReturn(detail);

            mockMvc.perform(get("/api/admin/customers/cust-1"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true));
        }
    }

    @Nested
    @DisplayName("PUT /api/admin/customers/{id}")
    class UpdateCustomer {

        @Test
        @DisplayName("更新客户信息 -> 200")
        void updateCustomer() throws Exception {
            when(customerService.updateCustomer(anyString(), any(CustomerProfile.class))).thenReturn(new CustomerProfile());

            Map<String, Object> body = Map.of("remark", "重要客户");

            mockMvc.perform(put("/api/admin/customers/cust-1")
                            .contentType("application/json")
                            .content(objectMapper.writeValueAsString(body)))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true));
        }
    }

    @Nested
    @DisplayName("GET /api/admin/customer-tags")
    class GetTags {

        @Test
        @DisplayName("获取标签列表 -> 200")
        void getTags() throws Exception {
            CustomerTag tag = new CustomerTag();
            tag.setId("tag-1");
            tag.setName("VIP");
            tag.setColor("blue");
            when(customerService.getCustomerTags(anyLong())).thenReturn(List.of(tag));

            mockMvc.perform(get("/api/admin/customer-tags"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true))
                    .andExpect(jsonPath("$.data").isArray());
        }
    }

    @Nested
    @DisplayName("POST /api/admin/customer-tags")
    class CreateTag {

        @Test
        @DisplayName("创建标签 -> 200")
        void createTag() throws Exception {
            CustomerTag tag = new CustomerTag();
            tag.setId("tag-new");
            when(customerService.createTag(any(CustomerTag.class))).thenReturn(tag);

            Map<String, String> body = Map.of("name", "新标签", "color", "red");

            mockMvc.perform(post("/api/admin/customer-tags")
                            .contentType("application/json")
                            .content(objectMapper.writeValueAsString(body)))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true));
        }
    }

    @Nested
    @DisplayName("PUT /api/admin/customer-tags/{id}")
    class UpdateTag {

        @Test
        @DisplayName("更新标签 -> 200")
        void updateTag() throws Exception {
            when(customerService.updateTag(anyString(), any(CustomerTag.class))).thenReturn(new CustomerTag());

            Map<String, String> body = Map.of("name", "已更新");

            mockMvc.perform(put("/api/admin/customer-tags/tag-1")
                            .contentType("application/json")
                            .content(objectMapper.writeValueAsString(body)))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true));
        }
    }

    @Nested
    @DisplayName("DELETE /api/admin/customer-tags/{id}")
    class DeleteTag {

        @Test
        @DisplayName("删除标签 -> 200")
        void deleteTag() throws Exception {
            doNothing().when(customerService).deleteTag(anyString());

            mockMvc.perform(delete("/api/admin/customer-tags/tag-1"))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.success").value(true));
        }
    }

    // ==================== 错误路径 ====================

    @Nested
    @DisplayName("错误路径")
    class ErrorPaths {

        @Test
        @DisplayName("查询不存在的客户 -> 404")
        void customerNotFound() throws Exception {
            when(customerService.getCustomerDetail("nonexistent"))
                    .thenThrow(new BusinessException("NOT_FOUND", "客户不存在", 404));

            mockMvc.perform(get("/api/admin/customers/nonexistent"))
                    .andExpect(status().isNotFound())
                    .andExpect(jsonPath("$.error.code").value("NOT_FOUND"));
        }

        @Test
        @DisplayName("更新不存在的客户 -> 404")
        void updateNotFound() throws Exception {
            when(customerService.updateCustomer(eq("nonexistent"), any(CustomerProfile.class)))
                    .thenThrow(new BusinessException("NOT_FOUND", "客户不存在", 404));

            mockMvc.perform(put("/api/admin/customers/nonexistent")
                            .contentType("application/json")
                            .content("{\"remark\":\"test\"}"))
                    .andExpect(status().isNotFound());
        }
    }

    // ==================== 租户隔离 ====================

    @Nested
    @DisplayName("租户隔离验证")
    class TenantIsolation {

        @Test
        @DisplayName("列表查询携带租户 ID")
        void listPassesTenantId() throws Exception {
            when(customerService.getCustomerPage(anyLong(), anyLong(), isNull(), isNull(), isNull(), eq(TEST_TENANT_ID)))
                    .thenReturn(new PageResponse<>());

            mockMvc.perform(get("/api/admin/customers"));

            verify(customerService).getCustomerPage(anyLong(), anyLong(), isNull(), isNull(), isNull(), eq(TEST_TENANT_ID));
        }

        @Test
        @DisplayName("标签列表携带租户 ID")
        void tagsPassesTenantId() throws Exception {
            when(customerService.getCustomerTags(eq(TEST_TENANT_ID))).thenReturn(List.of());

            mockMvc.perform(get("/api/admin/customer-tags"));

            verify(customerService).getCustomerTags(eq(TEST_TENANT_ID));
        }
    }
}
