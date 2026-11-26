// case_ids: KF-030
package com.migao.admin.service.kf;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.KfChannel;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.KfChannelMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class KfChannelAdminServiceTest {

    private KfChannelMapper mapper;
    private SecretCipher cipher;
    private WechatKfClient client;
    private KfChannelAdminService service;

    @BeforeEach
    void setUp() {
        mapper = mock(KfChannelMapper.class);
        cipher = mock(SecretCipher.class);
        client = mock(WechatKfClient.class);
        service = new KfChannelAdminService(mapper, cipher, client);
    }

    @Test
    @DisplayName("接入成功：secret 加密落库，自检命中 open_kfid ⇒ active")
    void createAndVerifyOk() {
        when(cipher.encrypt("sec")).thenReturn("v1:default:enc");
        when(cipher.decrypt("v1:default:enc")).thenReturn("sec");
        when(client.getAccessToken("corp", "sec")).thenReturn("tok");
        var accounts = new ObjectMapper().createObjectNode();
        accounts.putArray("account_list").addObject().put("open_kfid", "wk-1");
        when(client.listAccounts("tok")).thenReturn(accounts);
        when(mapper.selectOne(any())).thenReturn(null);
        when(mapper.selectById(anyString())).thenReturn(null);

        // create() 内部 verify() 会按 id 重新查一次 ⇒ 用 insert 回调把实体回填
        org.mockito.Mockito.doAnswer(inv -> {
            KfChannel c = inv.getArgument(0);
            c.setId("ch-1");
            when(mapper.selectOne(any())).thenReturn(c);
            return 1;
        }).when(mapper).insert(any(KfChannel.class));

        var result = service.create(1L, new KfChannelAdminService.CreateCommand("corp", "wk-1", "sec"));

        assertThat(result.verified()).isTrue();
        assertThat(result.channel().status()).isEqualTo("active");
        assertThat(result.channel().openKfid()).isEqualTo("wk-1");
        verify(cipher).encrypt("sec");
        verify(mapper).updateById(any(KfChannel.class));
    }

    @Test
    @DisplayName("自检不命中 open_kfid ⇒ unauthorized + verified=false（仍保留渠道）")
    void createSelfCheckMiss() {
        when(cipher.encrypt("sec")).thenReturn("enc");
        when(cipher.decrypt("enc")).thenReturn("sec");
        when(client.getAccessToken("corp", "sec")).thenReturn("tok");
        var accounts = new ObjectMapper().createObjectNode();
        accounts.putArray("account_list").addObject().put("open_kfid", "other");
        when(client.listAccounts("tok")).thenReturn(accounts);
        when(mapper.selectOne(any())).thenReturn(null);
        org.mockito.Mockito.doAnswer(inv -> {
            KfChannel c = inv.getArgument(0);
            c.setId("ch-1");
            when(mapper.selectOne(any())).thenReturn(c);
            return 1;
        }).when(mapper).insert(any(KfChannel.class));

        var result = service.create(1L, new KfChannelAdminService.CreateCommand("corp", "wk-1", "sec"));

        assertThat(result.verified()).isFalse();
        assertThat(result.channel().status()).isEqualTo("unauthorized");
        assertThat(result.message()).contains("不在该企业微信的客服账号列表");
    }

    @Test
    @DisplayName("重复 corp_id + open_kfid ⇒ 409，不插入")
    void duplicateRejected() {
        when(mapper.selectOne(any())).thenReturn(KfChannel.builder().id("old").build());

        assertThatThrownBy(() -> service.create(1L,
                new KfChannelAdminService.CreateCommand("corp", "wk-1", "sec")))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("已接入");
        verify(mapper, org.mockito.Mockito.never()).insert(any(KfChannel.class));
    }

    @Test
    @DisplayName("生成客服链接：scene_param 透传；>128B 拒绝")
    void link() {
        KfChannel channel = KfChannel.builder().id("ch-1").tenantId(1L)
                .corpId("corp").openKfid("wk-1").secretEnc("enc").status("active").build();
        when(mapper.selectOne(any())).thenReturn(channel);
        when(cipher.decrypt("enc")).thenReturn("sec");
        when(client.getAccessToken("corp", "sec")).thenReturn("tok");
        when(client.createContactWay("tok", "wk-1", "tenant:1")).thenReturn("https://kf.example/q");

        assertThat(service.link(1L, "ch-1", "tenant:1")).isEqualTo("https://kf.example/q");
        assertThatThrownBy(() -> service.link(1L, "ch-1", "x".repeat(129)))
                .isInstanceOf(BusinessException.class);
    }

    @Test
    @DisplayName("停用 ⇒ revoked；列表不回传 secret")
    void disableAndListView() {
        KfChannel channel = KfChannel.builder().id("ch-1").tenantId(1L)
                .corpId("corp").openKfid("wk-1").secretEnc("enc").authMode("self_built")
                .status("active").build();
        when(mapper.selectOne(any())).thenReturn(channel);
        when(mapper.selectList(any())).thenReturn(java.util.List.of(channel));

        assertThat(service.disable(1L, "ch-1").status()).isEqualTo("revoked");
        var views = service.list(1L);
        assertThat(views).hasSize(1);
        assertThat(views.get(0).toString()).doesNotContain("enc");
    }
}
