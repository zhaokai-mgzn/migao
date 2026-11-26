// case_ids: KF-004
package com.migao.admin.service.kf;

import com.migao.admin.entity.KfChannel;
import com.migao.admin.mapper.KfChannelMapper;
import com.migao.admin.mapper.KfInboxMapper;
import com.migao.admin.mapper.KfSyncCursorMapper;
import org.junit.jupiter.api.BeforeEach;
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
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class KfCallbackServiceTest {

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

    private KfChannelMapper channelMapper;
    private KfInboxMapper inboxMapper;
    private KfSyncCursorMapper cursorMapper;
    private KfCallbackService service;

    @BeforeEach
    void setUp() {
        channelMapper = mock(KfChannelMapper.class);
        inboxMapper = mock(KfInboxMapper.class);
        cursorMapper = mock(KfSyncCursorMapper.class);
        service = new KfCallbackService(channelMapper, inboxMapper, cursorMapper, TOKEN, aesKey(), RECEIVE_ID);
    }

    @Test
    @DisplayName("合法回调 ⇒ 落 inbox + 置 dirty")
    void handleOk() {
        KfChannel channel = KfChannel.builder().tenantId(7L).corpId("corp-1").openKfid("wk-1").build();
        when(channelMapper.selectByCorpAndOpenKfid("corp-1", "wk-1")).thenReturn(channel);
        when(inboxMapper.insertIgnore(anyString(), anyString(), anyLong(), anyString(), anyString())).thenReturn(1);

        String xml = "<xml><ToUserName><![CDATA[corp-1]]></ToUserName>"
                + "<OpenKfId><![CDATA[wk-1]]></OpenKfId></xml>";
        String encrypt = encrypt(xml);
        String ts = "1700000000";
        String nonce = "n1";
        String sig = sign(TOKEN, ts, nonce, encrypt);

        assertThat(service.handle(wrap(encrypt), sig, ts, nonce)).isTrue();
        verify(inboxMapper).insertIgnore(eq(sig), eq("corp-1"), eq(7L), eq("wk-1"), contains("corp-1"));
        verify(cursorMapper).markDirty(7L, "wk-1");
    }

    @Test
    @DisplayName("重复回调（inbox 返回 0）⇒ 仍置 dirty")
    void duplicateStillDirty() {
        when(channelMapper.selectByCorpAndOpenKfid("corp-1", "wk-1"))
                .thenReturn(KfChannel.builder().tenantId(7L).build());
        when(inboxMapper.insertIgnore(anyString(), anyString(), anyLong(), anyString(), anyString())).thenReturn(0);

        String encrypt = encrypt("<xml><ToUserName>corp-1</ToUserName><OpenKfId>wk-1</OpenKfId></xml>");
        String ts = "1";
        String nonce = "n";
        service.handle(wrap(encrypt), sign(TOKEN, ts, nonce, encrypt), ts, nonce);

        verify(cursorMapper).markDirty(7L, "wk-1");
    }

    @Test
    @DisplayName("签名不合法 ⇒ 拒绝且不落库")
    void badSignature() {
        assertThatThrownBy(() -> service.handle(wrap(encrypt("<xml/>")), "bad", "1", "n"))
                .isInstanceOf(IllegalArgumentException.class);
        verify(inboxMapper, never()).insertIgnore(anyString(), anyString(), anyLong(), anyString(), anyString());
    }

    @Test
    @DisplayName("未登记渠道 ⇒ 受理但不落库（避免平台重试风暴）")
    void unknownChannelAck() {
        when(channelMapper.selectByCorpAndOpenKfid(anyString(), anyString())).thenReturn(null);
        String encrypt = encrypt("<xml><ToUserName>unknown</ToUserName><OpenKfId>wk-x</OpenKfId></xml>");
        String ts = "1";
        String nonce = "n";
        assertThat(service.handle(wrap(encrypt), sign(TOKEN, ts, nonce, encrypt), ts, nonce)).isTrue();
        verify(inboxMapper, never()).insertIgnore(anyString(), anyString(), anyLong(), anyString(), anyString());
    }

    private static String wrap(String encrypt) {
        return "<xml><Encrypt><![CDATA[" + encrypt + "]]></Encrypt></xml>";
    }

    private static String encrypt(String msg) {
        try {
            byte[] msgBytes = msg.getBytes(StandardCharsets.UTF_8);
            byte[] recv = RECEIVE_ID.getBytes(StandardCharsets.UTF_8);
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            out.write(new byte[16]);
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
            byte[] d = MessageDigest.getInstance("SHA-1")
                    .digest(String.join("", arr).getBytes(StandardCharsets.UTF_8));
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
