package com.migao.admin.service.kf;

import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Base64;

/**
 * 最小信封加密（issue #9161 / #9171）：AES-256-GCM，密文格式 {@code v1:<keyId>:<base64(iv|ct|tag)>}。
 *
 * <p>本仓此前没有任何加密工具，{@code tenant_apps.app_secret} 是明文列。微信客服的
 * {@code corpsecret / permanent_code} 不能再明文落库，故引入这一个类；不引 KMS、不加依赖。</p>
 *
 * <p><b>主密钥来源</b>：env {@code KF_SECRET_MASTER_KEY}（任意长度字符串，内部 SHA-256 派生 32 字节）。
 * 未配置时构造即失败（fail-closed），避免“看起来加密了、其实用空 key”。</p>
 */
public class SecretCipher {

    private static final String VERSION = "v1";
    private static final int IV_LEN = 12;
    private static final int TAG_BITS = 128;

    private final SecretKeySpec key;
    private final String keyId;
    private final SecureRandom random = new SecureRandom();

    public SecretCipher(String masterKey, String keyId) {
        if (masterKey == null || masterKey.isBlank()) {
            throw new IllegalStateException("KF_SECRET_MASTER_KEY 未配置：拒绝以空密钥加密");
        }
        this.key = new SecretKeySpec(sha256(masterKey), "AES");
        this.keyId = (keyId == null || keyId.isBlank()) ? "default" : keyId;
    }

    public String encrypt(String plaintext) {
        if (plaintext == null) {
            throw new IllegalArgumentException("plaintext 不能为 null");
        }
        try {
            byte[] iv = new byte[IV_LEN];
            random.nextBytes(iv);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, key, new GCMParameterSpec(TAG_BITS, iv));
            byte[] ct = cipher.doFinal(plaintext.getBytes(StandardCharsets.UTF_8));
            byte[] out = new byte[iv.length + ct.length];
            System.arraycopy(iv, 0, out, 0, iv.length);
            System.arraycopy(ct, 0, out, iv.length, ct.length);
            return VERSION + ":" + keyId + ":" + Base64.getEncoder().encodeToString(out);
        } catch (Exception e) {
            throw new IllegalStateException("加密失败", e);
        }
    }

    public String decrypt(String ciphertext) {
        if (ciphertext == null || ciphertext.isBlank()) {
            throw new IllegalArgumentException("密文不能为空");
        }
        String[] parts = ciphertext.split(":", 3);
        if (parts.length != 3 || !VERSION.equals(parts[0])) {
            throw new IllegalArgumentException("不支持的密文格式");
        }
        if (!keyId.equals(parts[1])) {
            throw new IllegalArgumentException("密钥版本不匹配：" + parts[1]);
        }
        try {
            byte[] all = Base64.getDecoder().decode(parts[2]);
            if (all.length <= IV_LEN) {
                throw new IllegalArgumentException("密文长度非法");
            }
            byte[] iv = new byte[IV_LEN];
            System.arraycopy(all, 0, iv, 0, IV_LEN);
            byte[] ct = new byte[all.length - IV_LEN];
            System.arraycopy(all, IV_LEN, ct, 0, ct.length);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, key, new GCMParameterSpec(TAG_BITS, iv));
            return new String(cipher.doFinal(ct), StandardCharsets.UTF_8);
        } catch (IllegalArgumentException e) {
            throw e;
        } catch (Exception e) {
            throw new IllegalArgumentException("解密失败（密文被篡改或密钥不对）", e);
        }
    }

    private static byte[] sha256(String s) {
        try {
            return MessageDigest.getInstance("SHA-256").digest(s.getBytes(StandardCharsets.UTF_8));
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }
}
