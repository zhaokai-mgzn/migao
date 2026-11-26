package com.migao.admin.service.kf;

import javax.crypto.Cipher;
import javax.crypto.spec.IvParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import java.io.ByteArrayOutputStream;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.Base64;

/**
 * 企业微信回调加解密（issue #9171）：签名校验 + AES-256-CBC/PKCS7 解密 + receiveid 校验。
 *
 * <p>协议：{@code msg_signature = sha1(sort(token, timestamp, nonce, encrypt))}；
 * AES key = Base64(EncodingAESKey + "=")，IV = key 前 16 字节；
 * 明文 = 16 字节随机数 + 4 字节 msg_len(网络序) + msg + receiveid。</p>
 *
 * <p>receiveid：自建应用 = corpid；第三方应用 = suiteid。构造时传入期望值，解密后逐字校验。</p>
 */
public class WeChatKfCrypto {

    private final String token;
    private final byte[] aesKey;
    private final String expectedReceiveId;

    public WeChatKfCrypto(String token, String encodingAesKey, String expectedReceiveId) {
        if (token == null || token.isBlank()) {
            throw new IllegalStateException("回调 Token 未配置");
        }
        if (encodingAesKey == null || encodingAesKey.length() != 43) {
            throw new IllegalStateException("EncodingAESKey 必须是 43 位");
        }
        this.token = token;
        this.aesKey = Base64.getDecoder().decode(encodingAesKey + "=");
        this.expectedReceiveId = expectedReceiveId == null ? "" : expectedReceiveId;
    }

    public boolean verifySignature(String signature, String timestamp, String nonce, String encrypt) {
        if (signature == null || timestamp == null || nonce == null || encrypt == null) {
            return false;
        }
        String[] arr = {token, timestamp, nonce, encrypt};
        Arrays.sort(arr);
        String raw = String.join("", arr);
        return MessageDigest.isEqual(sha1Hex(raw).getBytes(StandardCharsets.UTF_8),
                signature.toLowerCase().getBytes(StandardCharsets.UTF_8));
    }

    public DecryptResult decrypt(String encrypt) {
        try {
            byte[] cipherBytes = Base64.getDecoder().decode(encrypt);
            Cipher cipher = Cipher.getInstance("AES/CBC/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, new SecretKeySpec(aesKey, "AES"),
                    new IvParameterSpec(Arrays.copyOfRange(aesKey, 0, 16)));
            byte[] plain = unpad(cipher.doFinal(cipherBytes));
            if (plain.length < 20) {
                throw new IllegalArgumentException("明文长度非法");
            }
            int msgLen = ByteBuffer.wrap(plain, 16, 4).getInt();
            if (msgLen < 0 || 20 + msgLen > plain.length) {
                throw new IllegalArgumentException("msg_len 非法");
            }
            String msg = new String(plain, 20, msgLen, StandardCharsets.UTF_8);
            String receiveId = new String(plain, 20 + msgLen, plain.length - 20 - msgLen, StandardCharsets.UTF_8);
            if (!expectedReceiveId.isEmpty() && !expectedReceiveId.equals(receiveId)) {
                throw new IllegalArgumentException("receiveid 不匹配");
            }
            return new DecryptResult(msg, receiveId);
        } catch (IllegalArgumentException e) {
            throw e;
        } catch (Exception e) {
            throw new IllegalArgumentException("回调解密失败", e);
        }
    }

    public String decryptEchostr(String signature, String timestamp, String nonce, String echostr) {
        if (!verifySignature(signature, timestamp, nonce, echostr)) {
            throw new IllegalArgumentException("URL 验证签名不合法");
        }
        return decrypt(echostr).message();
    }

    public record DecryptResult(String message, String receiveId) {
    }

    private static byte[] unpad(byte[] data) {
        if (data.length == 0) {
            throw new IllegalArgumentException("空明文");
        }
        int pad = data[data.length - 1] & 0xFF;
        if (pad < 1 || pad > 32 || pad > data.length) {
            throw new IllegalArgumentException("PKCS7 padding 非法");
        }
        for (int i = data.length - pad; i < data.length; i++) {
            if ((data[i] & 0xFF) != pad) {
                throw new IllegalArgumentException("PKCS7 padding 非法");
            }
        }
        return Arrays.copyOfRange(data, 0, data.length - pad);
    }

    private static String sha1Hex(String s) {
        try {
            byte[] d = MessageDigest.getInstance("SHA-1").digest(s.getBytes(StandardCharsets.UTF_8));
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
