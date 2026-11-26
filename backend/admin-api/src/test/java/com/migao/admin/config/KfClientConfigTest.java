// case_ids: KF-014
package com.migao.admin.config;

import com.migao.admin.service.kf.SecretCipher;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class KfClientConfigTest {

    @Test
    @DisplayName("client bean + SecretCipher bean 可创建并往返")
    void beans() {
        KfClientConfig config = new KfClientConfig();
        assertThat(config.wechatKfClient()).isNotNull();
        SecretCipher cipher = config.kfSecretCipher("master-key");
        assertThat(cipher.decrypt(cipher.encrypt("secret"))).isEqualTo("secret");
    }
}
