package com.migao.admin.service.kf;

import com.migao.admin.mapper.KfMediaMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Service;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;

/**
 * 入站媒体归档（issue #9200 / 母单 #9194 子项 4）。
 *
 * <p>顺序 = **先下载 → 再落文件 → 最后落行**：行里记 `storage_key`，所以只有文件真写成功才记账；
 * 任何一步失败都抛 {@link KfMediaException}，由调用方（sync worker）**吞掉但不影响消息落库**。</p>
 *
 * <p>三条硬约束：</p>
 * <ol>
 *   <li><b>media_id 是不可信输入</b>（来自回调 JSON）⇒ 白名单净化，绝不拼出 `../` 逃出归档根；</li>
 *   <li><b>幂等</b>：已有归档行 ⇒ 直接返回旧路径，不再下载；行插入用 `ON CONFLICT DO NOTHING`；</li>
 *   <li><b>语音保留原格式</b>：本单不引入 ffmpeg（AMR→wav 属真机阶段，见 #9194 子项 3），
 *       原样归档并在 `mime` 里如实记录。</li>
 * </ol>
 */
@Slf4j
@Service
@ConditionalOnProperty(prefix = "wechat.kf", name = "enabled", havingValue = "true")
public class KfMediaService {

    /** 未知 mime 的后缀（微信偶尔不给 Content-Type）。 */
    private static final String FALLBACK_EXT = ".bin";
    /** media_id 里允许出现的字符（微信侧实际是 [A-Za-z0-9_-]，其余一律替换）。 */
    private static final String SAFE_ID_PATTERN = "[^A-Za-z0-9_-]";

    private final WechatKfClient client;
    private final KfMediaMapper mediaMapper;
    private final String mediaDir;

    public KfMediaService(WechatKfClient client,
                          KfMediaMapper mediaMapper,
                          @Value("${wechat.kf.media-dir:uploads/kf-media}") String mediaDir) {
        this.client = client;
        this.mediaMapper = mediaMapper;
        this.mediaDir = mediaDir;
    }

    /**
     * 归档一条入站媒体。
     *
     * @return 归档路径（已存在时返回既有路径）
     * @throws KfMediaException 下载 / 落盘失败（调用方容忍，不影响消息入库）
     */
    public String archiveInbound(Long tenantId, String openKfid, String mediaId, String accessToken) {
        if (mediaId == null || mediaId.isBlank()) {
            throw new KfMediaException("media_id 为空");
        }
        String existing = mediaMapper.selectInboundStorageKey(mediaId);
        if (existing != null && !existing.isBlank()) {
            return existing;
        }

        WechatKfClient.MediaFile file;
        try {
            file = client.getMedia(accessToken, mediaId);
        } catch (RuntimeException e) {
            throw new KfMediaException("媒体下载失败: mediaId=" + mediaId + ", err=" + e.getMessage(), e);
        }

        Path target = resolveTarget(tenantId, mediaId, file.mime());
        try {
            Files.createDirectories(target.getParent());
            Files.write(target, file.bytes(),
                    StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING,
                    StandardOpenOption.WRITE);
        } catch (Exception e) {
            throw new KfMediaException("媒体落盘失败: path=" + target + ", err=" + e.getMessage(), e);
        }

        mediaMapper.insertInbound(tenantId, openKfid, mediaId, file.mime(),
                (long) file.bytes().length, target.toString());
        log.info("[kf-media] 归档成功 tenant={} mediaId={} size={} path={}",
                tenantId, mediaId, file.bytes().length, target);
        return target.toString();
    }

    /** 归档路径 = `<mediaDir>/<tenantId>/<净化后的 mediaId><ext>`（ext 由 mime 推）。 */
    private Path resolveTarget(Long tenantId, String mediaId, String mime) {
        String safeId = mediaId.replaceAll(SAFE_ID_PATTERN, "_");
        String ext = extensionFor(mime);
        Path root = Paths.get(mediaDir).toAbsolutePath().normalize();
        Path target = root.resolve(String.valueOf(tenantId)).resolve(safeId + ext).normalize();
        if (!target.startsWith(root)) {
            // 理论上不可达（已净化）；留着是为了「净化规则被改坏」时当场失败而不是写出去
            throw new KfMediaException("媒体路径越界: " + target);
        }
        return target;
    }

    private static String extensionFor(String mime) {
        if (mime == null) {
            return FALLBACK_EXT;
        }
        return switch (mime.toLowerCase()) {
            case "image/jpeg" -> ".jpg";
            case "image/png" -> ".png";
            case "image/gif" -> ".gif";
            case "audio/amr" -> ".amr";
            case "audio/mpeg" -> ".mp3";
            case "audio/silk" -> ".silk";
            case "video/mp4" -> ".mp4";
            case "application/pdf" -> ".pdf";
            case "application/octet-stream" -> FALLBACK_EXT;
            default -> {
                int slash = mime.indexOf('/');
                String sub = slash >= 0 ? mime.substring(slash + 1) : mime;
                yield sub.matches("[A-Za-z0-9]{1,8}") ? "." + sub.toLowerCase() : FALLBACK_EXT;
            }
        };
    }
}
