package com.migao.admin.controller;

import com.migao.admin.dto.NotificationDTO;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.dto.UnreadCountResponse;
import com.migao.admin.service.NotificationService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * NotificationController 单元测试
 * 覆盖 getNotifications / getUnreadCount 两个端点，
 * 验证 tenant_id 移除后接口仍正常工作。
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("NotificationController 通知管理测试")
class NotificationControllerTest extends BaseControllerTest {

    private MockMvc mockMvc;

    @Mock
    private NotificationService notificationService;

    @InjectMocks
    private NotificationController notificationController;

    private static final String BASE = "/api/admin/notifications";

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        mockMvc = buildMockMvc(notificationController);
    }

    @Override
    @org.junit.jupiter.api.AfterEach
    void baseTearDown() {
        super.baseTearDown();
    }

    @Test
    @DisplayName("getNotifications — 查询通知列表 → 200")
    void getNotifications_returnsPageResponse() throws Exception {
        NotificationDTO dto = new NotificationDTO();
        dto.setId("notif-1");
        dto.setTitle("测试通知");
        dto.setStatus("sent");

        PageResponse<NotificationDTO> page = PageResponse.of(1L, 1L, 20L, List.of(dto));
        when(notificationService.queryNotifications(eq(TEST_USER_ID), any()))
                .thenReturn(page);

        mockMvc.perform(get(BASE).param("page", "1").param("size", "20"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.total").value(1))
                .andExpect(jsonPath("$.data.items[0].title").value("测试通知"));

        verify(notificationService).queryNotifications(eq(TEST_USER_ID), any());
    }

    @Test
    @DisplayName("getNotifications — 带筛选条件 → 200")
    void getNotifications_withFilters() throws Exception {
        PageResponse<NotificationDTO> page = PageResponse.of(0L, 1L, 20L, List.of());
        when(notificationService.queryNotifications(eq(TEST_USER_ID), any()))
                .thenReturn(page);

        mockMvc.perform(get(BASE)
                        .param("page", "1")
                        .param("size", "10")
                        .param("status", "sent")
                        .param("channel", "internal"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.items").isEmpty());

        verify(notificationService).queryNotifications(eq(TEST_USER_ID), any());
    }

    @Test
    @DisplayName("getUnreadCount — 获取未读数 → 200")
    void getUnreadCount_returnsCount() throws Exception {
        when(notificationService.getUnreadCount(TEST_USER_ID))
                .thenReturn(new UnreadCountResponse(5L));

        mockMvc.perform(get(BASE + "/unread-count"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.count").value(5));

        verify(notificationService).getUnreadCount(TEST_USER_ID);
    }
}
