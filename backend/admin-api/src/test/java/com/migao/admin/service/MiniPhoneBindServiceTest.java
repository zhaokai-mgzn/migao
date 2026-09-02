// case_ids: OR-001, API-010
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.entity.User;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.UserMapper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * MiniPhoneBindService 单元测试 — 微信授权手机号绑定（小程序客户关联名下历史订单）。
 */
@ExtendWith(MockitoExtension.class)
class MiniPhoneBindServiceTest {

    @InjectMocks
    private MiniPhoneBindService miniPhoneBindService;

    @Mock
    private WechatService wechatService;

    @Mock
    private UserMapper userMapper;

    @Mock
    private OrderService orderService;

    @BeforeEach
    void setUp() {
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(assistant, User.class);
    }

    private WechatService.PhoneNumberResult phoneResult(String pure) {
        WechatService.PhoneNumberResult r = new WechatService.PhoneNumberResult();
        r.setPhoneNumber("+86" + pure);
        r.setPurePhoneNumber(pure);
        r.setCountryCode("86");
        return r;
    }

    private User miniUser() {
        return User.builder()
                .id("user-mini-001")
                .tenantId(1L)
                .nickname("微信用户")
                .role("customer")
                .status("active")
                .build();
    }

    @Test
    @DisplayName("绑定成功：换号 → 写 users.phone → 回填名下同手机号订单")
    void bind_BindsPhoneAndOrders() {
        User user = miniUser();
        when(userMapper.selectById("user-mini-001")).thenReturn(user);
        when(wechatService.getPhoneNumber("wx-phone-code-1"))
                .thenReturn(phoneResult("13900139000"));
        // 租户内无其他用户占用该手机号
        when(userMapper.selectCount(any(LambdaQueryWrapper.class))).thenReturn(0L);
        when(orderService.bindOrdersToUser(1L, "user-mini-001", "13900139000")).thenReturn(2);

        MiniPhoneBindService.BindResult result =
                miniPhoneBindService.bind("user-mini-001", 1L, "wx-phone-code-1");

        assertThat(result).isNotNull();
        assertThat(result.getPhone()).isEqualTo("13900139000");
        assertThat(result.getBoundOrders()).isEqualTo(2);
        org.mockito.ArgumentCaptor<User> userCaptor =
                org.mockito.ArgumentCaptor.forClass(User.class);
        verify(userMapper).updateById(userCaptor.capture());
        assertThat(userCaptor.getValue().getPhone()).isEqualTo("13900139000");
    }

    @Test
    @DisplayName("绑定失败：该手机号已被同租户其他用户占用 → 拒绝且不回填")
    void bind_PhoneOccupiedByOther_Rejects() {
        User user = miniUser();
        when(userMapper.selectById("user-mini-001")).thenReturn(user);
        when(wechatService.getPhoneNumber("code")).thenReturn(phoneResult("13900139000"));
        // 已有其他用户占用（count=1：除本人外）
        when(userMapper.selectCount(any(LambdaQueryWrapper.class))).thenReturn(1L);

        assertThatThrownBy(() -> miniPhoneBindService.bind("user-mini-001", 1L, "code"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("已被绑定");
        verify(userMapper, never()).updateById(any(User.class));
        verify(orderService, never()).bindOrdersToUser(anyLong(), anyString(), anyString());
    }

    @Test
    @DisplayName("绑定失败：手机号格式非法 → 拒绝")
    void bind_InvalidPhone_Rejects() {
        User user = miniUser();
        when(userMapper.selectById("user-mini-001")).thenReturn(user);
        when(wechatService.getPhoneNumber("code")).thenReturn(phoneResult("12345"));

        assertThatThrownBy(() -> miniPhoneBindService.bind("user-mini-001", 1L, "code"))
                .isInstanceOf(BusinessException.class);
        verify(orderService, never()).bindOrdersToUser(anyLong(), anyString(), anyString());
    }

    @Test
    @DisplayName("绑定失败：用户不存在/非本租户 → 拒绝")
    void bind_UserNotFound_Rejects() {
        when(userMapper.selectById("ghost-user")).thenReturn(null);

        assertThatThrownBy(() -> miniPhoneBindService.bind("ghost-user", 1L, "code"))
                .isInstanceOf(BusinessException.class);
        verify(wechatService, never()).getPhoneNumber(anyString());
    }

    @Test
    @DisplayName("重复绑定同一手机号（本人已绑定）→ 幂等成功且回填")
    void bind_SamePhoneIdempotent() {
        User user = miniUser();
        user.setPhone("13900139000");
        when(userMapper.selectById("user-mini-001")).thenReturn(user);
        when(wechatService.getPhoneNumber("code")).thenReturn(phoneResult("13900139000"));
        // 本人已绑同号 → 跳过占用检查（不查 count），幂等放行
        when(orderService.bindOrdersToUser(1L, "user-mini-001", "13900139000")).thenReturn(1);

        MiniPhoneBindService.BindResult result =
                miniPhoneBindService.bind("user-mini-001", 1L, "code");

        assertThat(result.getBoundOrders()).isEqualTo(1);
        verify(userMapper, never()).selectCount(any(LambdaQueryWrapper.class));
    }
}
