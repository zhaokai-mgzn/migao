// case_ids: KF-001
package com.migao.admin.service.kf;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class SecretCipherTest {

    @Test
    @DisplayName("AES-GCM 往返：明文逐字相等，密文带版本前缀")
    void roundTrip() {
        SecretCipher cipher = new SecretCipher("unit-test-master-key", "k1");
        String plain = "corp-secret-中文-\u0000-tail";
        String enc = cipher.encrypt(plain);
        assertThat(enc).startsWith("v1:k1:");
        assertThat(cipher.decrypt(enc)).isEqualTo(plain);
        assertThat(cipher.encrypt(plain)).isNotEqualTo(enc);
    }

    @Test
    @DisplayName("篡改密文 / 换主密钥 ⇒ 解密必失败")
    void tamperAndWrongKey() {
        SecretCipher cipher = new SecretCipher("unit-test-master-key", "k1");
        String enc = cipher.encrypt("secret");
        char last = enc.charAt(enc.length() - 1);
        String tampered = enc.substring(0, enc.length() - 1) + (last == 'A' ? 'B' : 'A');
        assertThatThrownBy(() -> cipher.decrypt(tampered)).isInstanceOf(IllegalArgumentException.class);

        SecretCipher other = new SecretCipher("another-master-key", "k1");
        assertThatThrownBy(() -> other.decrypt(enc)).isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    @DisplayName("空主密钥 ⇒ 构造即失败（fail-closed）")
    void blankMasterKey() {
        assertThatThrownBy(() -> new SecretCipher("", "k1")).isInstanceOf(IllegalStateException.class);
    }
}
