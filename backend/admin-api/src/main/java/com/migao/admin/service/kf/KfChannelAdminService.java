package com.migao.admin.service.kf;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.migao.admin.entity.KfChannel;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.KfChannelMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.stream.StreamSupport;

/**
 * 微信客服渠道自助接入（issue #9230）。
 *
 * <p>产品面只暴露「商户自己的 corp_id / open_kfid / secret」；secret 加密落库，
 * 任何读面都不回传 secret / cipher / callback token。接入自检 = gettoken + 客服账号列表
 * 必须包含该 open_kfid（把「填错账号」与「消息发送失败」分开）。</p>
 *
 * <p>回调 Token / EncodingAESKey 仍是部署级配置（`wechat.kf.token` / `encoding-aes-key`），
 * 本服务不伪造每租户独立回调密钥；页面给出回调 URL 与部署侧配置说明。</p>
 */
@Service
@RequiredArgsConstructor
@ConditionalOnProperty(prefix = "wechat.kf", name = "enabled", havingValue = "true")
public class KfChannelAdminService {

    private final KfChannelMapper channelMapper;
    private final SecretCipher secretCipher;
    private final WechatKfClient client;

    public List<ChannelView> list(Long tenantId) {
        return channelMapper.selectList(new LambdaQueryWrapper<KfChannel>()
                        .eq(KfChannel::getTenantId, tenantId)
                        .orderByDesc(KfChannel::getCreatedAt))
                .stream().map(KfChannelAdminService::view).toList();
    }

    /** 先落 unauthorized 再自检；自检失败仍保留渠道，返回 verified=false + 可执行原因。 */
    public CreateResult create(Long tenantId, CreateCommand command) {
        String corpId = trim(command.corpId());
        String openKfid = trim(command.openKfid());
        String secret = trim(command.secret());
        if (corpId.isEmpty() || openKfid.isEmpty() || secret.isEmpty()) {
            throw BusinessException.validationError("corp_id / open_kfid / secret 都必须填写");
        }
        KfChannel existing = channelMapper.selectOne(new LambdaQueryWrapper<KfChannel>()
                .eq(KfChannel::getCorpId, corpId).eq(KfChannel::getOpenKfid, openKfid).last("LIMIT 1"));
        if (existing != null) {
            throw BusinessException.conflict("该企业微信客服账号已接入", "换一个 open_kfid，或先在列表里停用旧渠道");
        }
        KfChannel channel = KfChannel.builder()
                .tenantId(tenantId)
                .corpId(corpId)
                .openKfid(openKfid)
                .authMode("self_built")
                .secretEnc(secretCipher.encrypt(secret))
                .secretKeyId("default")
                .status("unauthorized")
                .build();
        channelMapper.insert(channel);
        try {
            return new CreateResult(verify(tenantId, channel.getId()), true, "接入成功，客服账号已在线");
        } catch (BusinessException e) {
            KfChannel saved = require(tenantId, channel.getId());
            return new CreateResult(view(saved), false, e.getMessage());
        }
    }

    public ChannelView verify(Long tenantId, String id) {
        KfChannel channel = require(tenantId, id);
        try {
            String secret = secretCipher.decrypt(channel.getSecretEnc());
            String token = client.getAccessToken(channel.getCorpId(), secret);
            JsonNode accounts = client.listAccounts(token);
            boolean matched = StreamSupport.stream(accounts.path("account_list").spliterator(), false)
                    .anyMatch(a -> channel.getOpenKfid().equals(a.path("open_kfid").asText()));
            if (!matched) {
                throw new BusinessException("VALIDATION_ERROR",
                        "自检失败：这个 open_kfid 不在该企业微信的客服账号列表里", 422,
                        "确认 corp_id / open_kfid 属于同一个企业微信；并确认应用已获「微信客服」API 权限");
            }
            channel.setStatus("active");
            channelMapper.updateById(channel);
            return view(channel);
        } catch (BusinessException e) {
            markUnauthorized(channel);
            throw e;
        } catch (RuntimeException e) {
            markUnauthorized(channel);
            throw new BusinessException("VALIDATION_ERROR",
                    "自检失败：" + e.getMessage(), 422,
                    "检查 corp_id / secret 是否正确、该应用是否已开通微信客服 API 权限");
        }
    }

    public ChannelView disable(Long tenantId, String id) {
        KfChannel channel = require(tenantId, id);
        channel.setStatus("revoked");
        channelMapper.updateById(channel);
        return view(channel);
    }

    /** 生成客服链接（scene_param 用于一店一码归因；≤128B）。 */
    public String link(Long tenantId, String id, String sceneParam) {
        String scene = trim(sceneParam);
        if (scene.length() > 128) {
            throw BusinessException.validationError("scene_param 不能超过 128 字节");
        }
        KfChannel channel = require(tenantId, id);
        String secret = secretCipher.decrypt(channel.getSecretEnc());
        String token = client.getAccessToken(channel.getCorpId(), secret);
        return client.createContactWay(token, channel.getOpenKfid(), scene);
    }

    private KfChannel require(Long tenantId, String id) {
        KfChannel channel = channelMapper.selectOne(new LambdaQueryWrapper<KfChannel>()
                .eq(KfChannel::getId, id).eq(KfChannel::getTenantId, tenantId).last("LIMIT 1"));
        if (channel == null) {
            throw BusinessException.notFound("微信客服渠道");
        }
        return channel;
    }

    private void markUnauthorized(KfChannel channel) {
        channel.setStatus("unauthorized");
        channelMapper.updateById(channel);
    }

    private static ChannelView view(KfChannel c) {
        return new ChannelView(c.getId(), c.getCorpId(), c.getOpenKfid(), c.getAuthMode(),
                c.getStatus(), c.getCreatedAt() == null ? null : c.getCreatedAt().toString(),
                c.getUpdatedAt() == null ? null : c.getUpdatedAt().toString());
    }

    private static String trim(String value) {
        return value == null ? "" : value.trim();
    }

    public record CreateCommand(String corpId, String openKfid, String secret) {
    }

    public record CreateResult(ChannelView channel, boolean verified, String message) {
    }

    public record ChannelView(String id, String corpId, String openKfid, String authMode,
                              String status, String createdAt, String updatedAt) {
    }
}
