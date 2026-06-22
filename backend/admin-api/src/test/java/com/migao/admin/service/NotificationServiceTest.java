package com.migao.admin.service;

import com.migao.admin.dto.CreateNotificationRequest;
import com.migao.admin.dto.NotificationDTO;
import com.migao.admin.dto.NotificationQueryRequest;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.dto.UnreadCountResponse;
import com.migao.admin.entity.Notification;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.NotificationMapper;
import com.migao.admin.mapper.NotificationTemplateMapper;
import com.migao.admin.mapper.NotificationRuleMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import org.junit.jupiter.api.Disabled;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * NotificationService 单元测试
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("NotificationService 通知服务测试")
class NotificationServiceTest {

    @Mock
    private NotificationMapper notificationMapper;

    @Mock
    private NotificationTemplateMapper notificationTemplateMapper;

    @Mock
    private NotificationRuleMapper notificationRuleMapper;

    @InjectMocks
    private NotificationService notificationService;

    @Test
    @DisplayName("createNotification — 创建通知")
    void createNotification_createsEntity() {
        when(notificationMapper.insert(any(Notification.class))).thenReturn(1);

        CreateNotificationRequest request = new CreateNotificationRequest();
        request.setRecipientId("user-1");
        request.setRecipientType("employee");
        request.setTitle("测试通知");
        request.setContent("通知内容");

        NotificationDTO result = notificationService.createNotification(1L, request);

        verify(notificationMapper).insert(any(Notification.class));
        assertThat(result).isNotNull();
    }

    @Test
    @DisplayName("queryNotifications — 返回分页通知列表")
    void queryNotifications_returnsPageResponse() {
        Notification n = new Notification();
        n.setId("1");
        n.setTitle("测试通知");
        n.setStatus("sent");

        Page<Notification> page = new Page<>(1, 10);
        page.setTotal(1);
        page.setRecords(List.of(n));
        when(notificationMapper.selectByRecipientId(any(), any(), any(), any(Page.class)))
                .thenReturn((com.baomidou.mybatisplus.core.metadata.IPage<Notification>) page);

        NotificationQueryRequest queryRequest = new NotificationQueryRequest();
        queryRequest.setPage(1L);
        queryRequest.setSize(10L);

        PageResponse<NotificationDTO> result = notificationService.queryNotifications(
                "user-1", queryRequest);

        assertThat(result.getTotal()).isEqualTo(1);
        assertThat(result.getItems().get(0).getTitle()).isEqualTo("测试通知");
    }

    @Test
    @DisplayName("markAsRead — 标记单条通知已读")
    void markAsRead_updatesTimestamp() {
        Notification n = new Notification();
        n.setId("notif-1");
        n.setTenantId(1L);
        n.setRecipientId("user-1");
        n.setStatus("unread");
        when(notificationMapper.selectById("notif-1")).thenReturn(n);
        when(notificationMapper.updateById(any(Notification.class))).thenReturn(1);

        notificationService.markAsRead(1L, "user-1", "notif-1");

        verify(notificationMapper).updateById(any(Notification.class));
    }

    @Test
    @Disabled("markAllAsRead 内部使用 LambdaUpdateWrapper 需要 MyBatis-Plus Spring 容器初始化，纯 Mockito 单测无法覆盖；该方法在集成测试中验证")
    @DisplayName("markAllAsRead — 标记全部未读通知为已读")
    void markAllAsRead_updatesAllUnread() {
        when(notificationMapper.update(any(), any(LambdaQueryWrapper.class))).thenReturn(5);

        notificationService.markAllAsRead(1L, "user-1");

        verify(notificationMapper).update(any(), any(LambdaQueryWrapper.class));
    }

    @Test
    @DisplayName("getUnreadCount — 返回未读数量")
    void getUnreadCount_returnsCount() {
        when(notificationMapper.countUnread(anyString())).thenReturn(3L);

        UnreadCountResponse result = notificationService.getUnreadCount("user-1");

        assertThat(result.getCount()).isEqualTo(3L);
    }

    // ======================== 删除通知测试 ========================

    @Test
    @DisplayName("deleteNotification — 删除通知成功")
    void deleteNotification_Success() {
        // given
        Notification n = new Notification();
        n.setId("notif-delete");
        n.setTenantId(1L);
        n.setRecipientId("user-1");
        n.setStatus("read");

        when(notificationMapper.selectById("notif-delete")).thenReturn(n);
        when(notificationMapper.deleteById("notif-delete")).thenReturn(1);

        // when
        notificationService.deleteNotification(1L, "user-1", "notif-delete");

        // then
        verify(notificationMapper).deleteById("notif-delete");
    }

    @Test
    @DisplayName("deleteNotification — 通知不存在")
    void deleteNotification_NotFound() {
        // given
        when(notificationMapper.selectById("nonexistent")).thenReturn(null);

        // when & then
        assertThatThrownBy(() -> notificationService.deleteNotification(1L, "user-1", "nonexistent"))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                });
    }

    @Test
    @DisplayName("deleteNotification — 跨租户操作被拒绝")
    void deleteNotification_CrossTenantRejected() {
        // given: 通知属于租户 2，但请求是租户 1
        Notification n = new Notification();
        n.setId("notif-cross");
        n.setTenantId(2L);
        n.setRecipientId("user-1");

        when(notificationMapper.selectById("notif-cross")).thenReturn(n);

        // when & then
        assertThatThrownBy(() -> notificationService.deleteNotification(1L, "user-1", "notif-cross"))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("PERMISSION_DENIED");
                });
    }

    @Test
    @DisplayName("deleteNotification — 非本人通知不可删除")
    void deleteNotification_WrongRecipient() {
        // given: 通知的接收人是 user-2，但请求是 user-1
        Notification n = new Notification();
        n.setId("notif-other");
        n.setTenantId(1L);
        n.setRecipientId("user-2");

        when(notificationMapper.selectById("notif-other")).thenReturn(n);

        // when & then
        assertThatThrownBy(() -> notificationService.deleteNotification(1L, "user-1", "notif-other"))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("PERMISSION_DENIED");
                });
    }

    // ======================== 通过模板创建通知测试 ========================

    @Test
    @DisplayName("createFromTemplate — 模板存在，创建通知并替换变量")
    void createFromTemplate_Success() {
        // given
        com.migao.admin.entity.NotificationTemplate template =
                new com.migao.admin.entity.NotificationTemplate();
        template.setId("tpl-001");
        template.setName("order_notify");
        template.setChannel("internal");
        template.setTemplateContent("订单{{orderId}}金额为{{amount}}元");
        template.setStatus("active");

        when(notificationTemplateMapper.selectOne(any(LambdaQueryWrapper.class)))
                .thenReturn(template);
        when(notificationMapper.insert(any(Notification.class))).thenReturn(1);

        java.util.Map<String, String> vars = java.util.Map.of("orderId", "ORD-001", "amount", "299.00");

        // when
        NotificationDTO result = notificationService.createFromTemplate(1L, "order_notify", "user-1", "employee", vars);

        // then
        assertThat(result).isNotNull();
        verify(notificationMapper).insert(any(Notification.class));
    }

    @Test
    @DisplayName("createFromTemplate — 模板不存在返回 null")
    void createFromTemplate_TemplateNotFound() {
        // given
        when(notificationTemplateMapper.selectOne(any(LambdaQueryWrapper.class)))
                .thenReturn(null);

        // when
        NotificationDTO result = notificationService.createFromTemplate(1L, "nonexistent", "user-1", "employee", null);

        // then
        assertThat(result).isNull();
        verify(notificationMapper, never()).insert(any(Notification.class));
    }

    // ======================== markAsRead 错误情况测试 ========================

    @Test
    @DisplayName("markAsRead — 通知不存在")
    void markAsRead_NotFound() {
        // given
        when(notificationMapper.selectById("nonexistent")).thenReturn(null);

        // when & then
        assertThatThrownBy(() -> notificationService.markAsRead(1L, "user-1", "nonexistent"))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                });
    }

    @Test
    @DisplayName("markAsRead — 跨租户操作被拒绝")
    void markAsRead_CrossTenant() {
        // given
        Notification n = new Notification();
        n.setId("notif-1");
        n.setTenantId(2L);
        n.setRecipientId("user-1");
        when(notificationMapper.selectById("notif-1")).thenReturn(n);

        // when & then
        assertThatThrownBy(() -> notificationService.markAsRead(1L, "user-1", "notif-1"))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("PERMISSION_DENIED");
                });
    }
}
