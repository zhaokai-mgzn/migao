// case_ids: KF-012
package com.migao.admin.service.kf;

import com.migao.admin.entity.KfChannel;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class KfAccessTokenServiceTest {

    @Test
    @DisplayName("解密 secret → 换 token → 进程内缓存命中")
    void tokenCached() {
        SecretCipher cipher = new SecretCipher("master", "default");
        WechatKfClient client = mock(WechatKfClient.class);
        when(client.getAccessToken("corp", "secret")).thenReturn("tok");
        KfAccessTokenService service = new KfAccessTokenService(cipher, client);
        KfChannel channel = KfChannel.builder().corpId("corp")
                .secretEnc(cipher.encrypt("secret")).build();

        assertThat(service.token(channel)).isEqualTo("tok");
        assertThat(service.token(channel)).isEqualTo("tok");
        verify(client, times(1)).getAccessToken("corp", "secret");
    }

    @Test
    @DisplayName("secret 为空/解不开 ⇒ null（调用方跳过，不重试到死）")
    void badSecret() {
        KfAccessTokenService service = new KfAccessTokenService(
                new SecretCipher("master", "default"), mock(WechatKfClient.class));
        assertThat(service.token(KfChannel.builder().corpId("corp").build())).isNull();
        assertThat(service.token(KfChannel.builder().corpId("corp").secretEnc("not-a-cipher").build())).isNull();
    }
}
