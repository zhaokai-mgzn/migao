package com.migao.admin.service.kf;

import com.migao.admin.entity.KfChannel;
import com.migao.admin.mapper.KfChannelMapper;
import com.migao.admin.mapper.KfInboxMapper;
import com.migao.admin.mapper.KfSyncCursorMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Service;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 微信客服回调：验签 → 解密 → 落 {@code kf_inbox}（msg_signature 唯一）→ 置 sync dirty。
 *
 * <p>回调在 5 秒内必须应答；这里只做短事务，不做会话归并/租户解析之外的业务。</p>
 */
@Slf4j
@Service
@ConditionalOnProperty(prefix = "wechat.kf", name = "enabled", havingValue = "true")
public class KfCallbackService {

    private static final Pattern ENCRYPT = Pattern.compile(
            "<Encrypt>(?:<!\\[CDATA\\[)?(.*?)(?:\\]\\]>)?</Encrypt>", Pattern.DOTALL);

    private final KfChannelMapper channelMapper;
    private final KfInboxMapper inboxMapper;
    private final KfSyncCursorMapper cursorMapper;
    private final String token;
    private final String aesKey;
    private final String receiveId;
    private volatile WeChatKfCrypto crypto;

    public KfCallbackService(KfChannelMapper channelMapper,
                             KfInboxMapper inboxMapper,
                             KfSyncCursorMapper cursorMapper,
                             @Value("${wechat.kf.token:}") String token,
                             @Value("${wechat.kf.encoding-aes-key:}") String aesKey,
                             @Value("${wechat.kf.receive-id:}") String receiveId) {
        this.channelMapper = channelMapper;
        this.inboxMapper = inboxMapper;
        this.cursorMapper = cursorMapper;
        this.token = token;
        this.aesKey = aesKey;
        this.receiveId = receiveId;
    }

    public boolean isConfigured() {
        return token != null && !token.isBlank() && aesKey != null && aesKey.length() == 43;
    }

    private WeChatKfCrypto crypto() {
        WeChatKfCrypto c = crypto;
        if (c == null) {
            synchronized (this) {
                c = crypto;
                if (c == null) {
                    c = new WeChatKfCrypto(token, aesKey, receiveId);
                    crypto = c;
                }
            }
        }
        return c;
    }

    /** URL 验证：企业微信要求 1 秒内返回明文 echostr。 */
    public String verifyUrl(String signature, String timestamp, String nonce, String echostr) {
        return crypto().decryptEchostr(signature, timestamp, nonce, echostr);
    }

    /** POST 回调：返回 true 表示已受理（含重复回调）；异常由控制器转 4xx/5xx。 */
    public boolean handle(String rawBody, String signature, String timestamp, String nonce) {
        String encrypt = extract(rawBody, ENCRYPT);
        if (encrypt == null || !crypto().verifySignature(signature, timestamp, nonce, encrypt)) {
            throw new IllegalArgumentException("回调签名不合法");
        }
        String xml = crypto().decrypt(encrypt).message();
        String corpId = tag(xml, "ToUserName");
        String openKfid = tag(xml, "OpenKfId");
        if (openKfid == null) {
            openKfid = tag(xml, "OpenKfid");
        }
        if (corpId == null || openKfid == null) {
            log.warn("[kf-callback] 报文缺少 corpId/openKfid，已忽略");
            return true;
        }
        KfChannel channel = channelMapper.selectByCorpAndOpenKfid(corpId, openKfid);
        if (channel == null) {
            log.warn("[kf-callback] 未登记的渠道 corpId={} openKfid={}，已忽略", corpId, openKfid);
            return true;
        }
        try {
            inboxMapper.insertIgnore(signature, corpId, channel.getTenantId(), openKfid, xml);
        } catch (Exception e) {
            log.error("[kf-callback] 落 inbox 失败 corpId={} openKfid={}", corpId, openKfid, e);
            throw e;
        }
        // 重复回调也必须置 dirty（回调只当加速器，真实消息以 sync_msg 为准）
        cursorMapper.markDirty(channel.getTenantId(), openKfid);
        return true;
    }

    private static String extract(String xml, Pattern p) {
        Matcher m = p.matcher(xml == null ? "" : xml);
        return m.find() ? m.group(1).trim() : null;
    }

    private static String tag(String xml, String name) {
        Pattern p = Pattern.compile("<" + name + ">(?:<!\\[CDATA\\[)?(.*?)(?:\\]\\]>)?</" + name + ">",
                Pattern.DOTALL);
        return extract(xml, p);
    }
}
