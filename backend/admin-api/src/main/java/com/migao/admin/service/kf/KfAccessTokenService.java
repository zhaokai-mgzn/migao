package com.migao.admin.service.kf;

import com.migao.admin.entity.KfChannel;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Service;

import java.util.concurrent.ConcurrentHashMap;

/** access_token 进程内缓存（单实例 7200s 有效期；多实例各自缓存，过期前 200s 刷新）。 */
@Slf4j
@Service
@ConditionalOnProperty(prefix = "wechat.kf", name = "enabled", havingValue = "true")
public class KfAccessTokenService {

    private final SecretCipher cipher;
    private final WechatKfClient client;
    private final ConcurrentHashMap<String, Cached> cache = new ConcurrentHashMap<>();

    public KfAccessTokenService(SecretCipher cipher, WechatKfClient client) {
        this.cipher = cipher;
        this.client = client;
    }

    /** @return null = 渠道没配 secret / 解不开（调用方跳过并释放 claim，不重试到死） */
    public String token(KfChannel channel) {
        if (channel.getSecretEnc() == null || channel.getSecretEnc().isBlank()) {
            return null;
        }
        Cached cached = cache.get(channel.getCorpId());
        if (cached != null && cached.expiresAtMillis > System.currentTimeMillis() + 200_000L) {
            return cached.token;
        }
        String secret;
        try {
            secret = cipher.decrypt(channel.getSecretEnc());
        } catch (RuntimeException e) {
            log.error("[kf-token] 渠道 {} secret 解密失败，跳过", channel.getOpenKfid(), e);
            return null;
        }
        String token = client.getAccessToken(channel.getCorpId(), secret);
        cache.put(channel.getCorpId(), new Cached(token, System.currentTimeMillis() + 7_000_000L));
        return token;
    }

    private record Cached(String token, long expiresAtMillis) {
    }
}
