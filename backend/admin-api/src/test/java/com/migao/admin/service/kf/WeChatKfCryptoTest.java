// case_ids: KF-002
package com.migao.admin.service.kf;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import javax.crypto.Cipher;
import javax.crypto.spec.IvParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import java.io.ByteArrayOutputStream;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.Base64;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class WeChatKfCryptoTest {

    private static final String TOKEN = "test-token";
    private static byte[] key() {
        byte[] k = new byte[32];
        for (int i = 0; i < k.length; i++) {
            k[i] = (byte) ('a' + (i % 26));
        }
        return k;
    }

    private static String aesKey() {
        return Base64.getEncoder().encodeToString(key()).substring(0, 43);
    }

    private static final String RECEIVE_ID = "suite-1";

    private final WeChatKfCrypto crypto = new WeChatKfCrypto(TOKEN, aesKey(), RECEIVE_ID);

    @Test
    @DisplayName("合法签名 + 合法密文 ⇒ 明文逐字相等")
    void decryptOk() {
        String msg = "<xml><ToUserName>corp-1</ToUserName><OpenKfId>wk-1</OpenKfId></xml>";
        String encrypt = encrypt(msg, RECEIVE_ID);
        String ts = "1700000000";
        String nonce = "n1";
        String sig = sign(TOKEN, ts, nonce, encrypt);

        assertThat(crypto.verifySignature(sig, ts, nonce, encrypt)).isTrue();
        assertThat(crypto.decrypt(encrypt).message()).isEqualTo(msg);
        assertThat(crypto.decrypt(encrypt).receiveId()).isEqualTo(RECEIVE_ID);
    }

    @Test
    @DisplayName("签名错 / receiveid 不匹配 ⇒ 拒绝")
    void rejectsBadSignatureAndReceiveId() {
        String encrypt = encrypt("<xml/>", RECEIVE_ID);
        assertThat(crypto.verifySignature("deadbeef", "1", "n", encrypt)).isFalse();
        assertThatThrownBy(() -> crypto.decryptEchostr("deadbeef", "1", "n", encrypt))
                .isInstanceOf(IllegalArgumentException.class);

        String wrongReceive = encrypt("<xml/>", "other-suite");
        String ts = "1";
        String nonce = "n";
        String sig = sign(TOKEN, ts, nonce, wrongReceive);
        assertThatThrownBy(() -> crypto.decrypt(wrongReceive))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("receiveid");
        assertThat(crypto.verifySignature(sig, ts, nonce, wrongReceive)).isTrue();
    }

    private static String encrypt(String msg, String receiveId) {
        try {
            byte[] random16 = new byte[16];
            byte[] msgBytes = msg.getBytes(StandardCharsets.UTF_8);
            byte[] recv = receiveId.getBytes(StandardCharsets.UTF_8);
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            out.write(random16);
            out.write(ByteBuffer.allocate(4).putInt(msgBytes.length).array());
            out.write(msgBytes);
            out.write(recv);
            byte[] plain = out.toByteArray();
            int pad = 32 - (plain.length % 32);
            byte[] padded = Arrays.copyOf(plain, plain.length + pad);
            Arrays.fill(padded, plain.length, padded.length, (byte) pad);

            Cipher cipher = Cipher.getInstance("AES/CBC/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, new SecretKeySpec(key(), "AES"),
                    new IvParameterSpec(Arrays.copyOfRange(key(), 0, 16)));
            return Base64.getEncoder().encodeToString(cipher.doFinal(padded));
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    private static String sign(String token, String ts, String nonce, String encrypt) {
        String[] arr = {token, ts, nonce, encrypt};
        Arrays.sort(arr);
        try {
            byte[] d = MessageDigest.getInstance("SHA-1").digest(String.join("", arr).getBytes(StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder();
            for (byte b : d) {
                sb.append(String.format("%02x", b));
            }
            return sb.toString();
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }
}
