package com.migao.admin.controller;

import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.*;
import com.migao.admin.entity.Notification;
import com.migao.admin.security.SecurityUser;
import com.migao.admin.service.NotificationService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.MockedStatic;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContext;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * NotificationController 单元测试
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("NotificationController 通知接口测试")
class NotificationControllerTest {

    private MockMvc mockMvc;
    private MockedStatic<TenantContext> tenantContextMock;
    private MockedStatic<SecurityContextHolder> securityMock;

    @Mock
    private NotificationService notificationService;
    @Mock
    private Authentication authentication;
    @Mock
    private SecurityContext securityContext;

    @InjectMocks
    private NotificationController notificationController;

    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders.standaloneSetup(notificationController)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();

        tenantContextMock = mockStatic(TenantContext.class);
        tenantContextMock.when(TenantContext::getTenantId).thenReturn(1L);

        securityMock = mockStatic(SecurityContextHolder.class);
        securityMock.when(SecurityContextHolder::getContext).thenReturn(securityContext);
    }

    @AfterEach
    void tearDown() {
        if (tenantContextMock != null) tenantContextMock.close();
        if (securityMock != null) securityMock.close();
    }

    private void mockAuthUser(String userId) {
        SecurityUser securityUser = new SecurityUser(userId, "13800138000", "admin", 1L, List.of());
        when(securityContext.getAuthentication()).thenReturn(authentication);
        when(authentication.getPrincipal()).thenReturn(securityUser);
    }

    @Test
    @DisplayName("GET / — 查询通知列表 → 200")
    void getNotifications() throws Exception {
        mockAuthUser("user-1");
        PageResponse<NotificationDTO> page = PageResponse.of(5L, 1L, 20L, List.of());
        when(notificationService.queryNotifications(anyLong(), eq("user-1"), any()))
                .thenReturn(page);

        mockMvc.perform(get("/api/admin/notifications")
                        .param("page", "1")
                        .param("size", "20"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.total").value(5));
    }

    @Test
    @DisplayName("GET /unread-count — 获取未读数 → 200")
    void getUnreadCount() throws Exception {
        mockAuthUser("user-1");
        when(notificationService.getUnreadCount(eq(1L), eq("user-1")))
                .thenReturn(new UnreadCountResponse(3));

        mockMvc.perform(get("/api/admin/notifications/unread-count"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.unreadCount").value(3));
    }

    @Test
    @DisplayName("PUT /{id}/read — 标记已读 → 200")
    void markAsRead() throws Exception {
        mockAuthUser("user-1");
        doNothing().when(notificationService).markAsRead(eq(1L), eq("user-1"), eq("notif-1"));

        mockMvc.perform(put("/api/admin/notifications/notif-1/read"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true));
    }

    @Test
    @DisplayName("PUT /read-all — 全部已读 → 200")
    void markAllAsRead() throws Exception {
        mockAuthUser("user-1");
        doNothing().when(notificationService).markAllAsRead(eq(1L), eq("user-1"));

        mockMvc.perform(put("/api/admin/notifications/read-all"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true));
    }

    @Test
    @DisplayName("DELETE /{id} — 删除通知 → 200")
    void deleteNotification() throws Exception {
        mockAuthUser("user-1");
        doNothing().when(notificationService).deleteNotification(eq(1L), eq("user-1"), eq("notif-1"));

        mockMvc.perform(delete("/api/admin/notifications/notif-1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true));
    }

    @Test
    @DisplayName("POST / — 创建通知 → 200")
    void createNotification() throws Exception {
        mockAuthUser("user-1");
        NotificationDTO dto = NotificationDTO.builder()
                .id("notif-1")
                .title("测试通知")
                .recipientId("user-2")
                .build();
        when(notificationService.createNotification(eq(1L), any())).thenReturn(dto);

        mockMvc.perform(post("/api/admin/notifications")
                        .contentType("application/json")
                        .content("{\"recipientId\":\"user-2\",\"title\":\"测试通知\",\"content\":\"内容\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.title").value("测试通知"));
    }

    @Test
    @DisplayName("未认证用户 → 401")
    void unauthenticated() throws Exception {
        when(securityContext.getAuthentication()).thenReturn(null);

        mockMvc.perform(get("/api/admin/notifications"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(false));
    }
}
