package com.migao.admin.service;

import com.migao.admin.dto.UploadedFileInfo;
import com.migao.admin.exception.BusinessException;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;
import org.springframework.web.client.RestTemplate;

import javax.imageio.IIOImage;
import javax.imageio.ImageIO;
import javax.imageio.ImageWriteParam;
import javax.imageio.ImageWriter;
import javax.imageio.stream.ImageOutputStream;
import java.awt.Color;
import java.awt.Graphics2D;
import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.net.URI;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/**
 * 商品图生成服务（issue #7335）：样图 → 百炼生成 → **转存 OSS** → 返回永久 URL。
 *
 * <h3>它做什么</h3>
 * <ol>
 *   <li>校验用途白名单与样图地址；</li>
 *   <li>调 {@link ProductImageClient}（ai-agent 内部端点）拿**临时 URL**；</li>
 *   <li>下载临时图（**只认百炼 OSS 域名 + https**，防 SSRF），必要时压到 5MB 内；</li>
 *   <li>走 {@link FileStorageService#uploadBytes}（与用户上传**同一条** UploadGuard）落 OSS；</li>
 *   <li>返回永久 URL —— <b>不写任何业务表</b>，「用不用」由商家在页面上点按钮。</li>
 * </ol>
 *
 * <h3>为什么必须转存</h3>
 * <p>百炼返回的是 24h 过期的临时地址；直接写进商品会在第二天全部裂图。转存后 URL 归本仓
 * OSS，与手工上传的图同域、同生命周期。</p>
 */
@Slf4j
@Service
public class ProductImageGenerationService {

    /** 与前端「用这张」的四个入口一一对应（前端另有一份文案，取值只有这一份真值）。 */
    public static final Set<String> KINDS = Set.of("main", "texture", "craft", "scene");

    /** 与 {@code UploadGuard} 的图片上限同口径（5MB）；超过则先压成 JPEG。 */
    static final long MAX_IMAGE_BYTES = 5L * 1024 * 1024;
    /** 超过该阈值就转 JPEG（PNG 照片在 1440×1440 下常见 2.5~4.8MB，留一点余量）。 */
    static final long REENCODE_THRESHOLD = 4L * 1024 * 1024;

    private static final List<String> ALLOWED_DOWNLOAD_SUFFIXES =
            List.of(".aliyuncs.com", ".aliyuncs.com.cn");

    private final ProductImageClient client;
    private final FileStorageService fileStorageService;
    private final RestTemplate downloader;

    @Autowired
    public ProductImageGenerationService(ProductImageClient client, FileStorageService fileStorageService) {
        this(client, fileStorageService, new RestTemplate(downloadFactory()));
    }

    /** 供测试注入 mock 下载器。 */
    ProductImageGenerationService(ProductImageClient client, FileStorageService fileStorageService,
                                  RestTemplate downloader) {
        this.client = client;
        this.fileStorageService = fileStorageService;
        this.downloader = downloader;
    }

    private static SimpleClientHttpRequestFactory downloadFactory() {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(3_000);
        factory.setReadTimeout(60_000);
        return factory;
    }

    /**
     * 生成一张并转存 OSS。
     *
     * @return {@code {"url": OSS 永久地址, "model": 实际模型名}}
     * @throws BusinessException 422：用途非法 / 样图地址非法 / 临时图域名不可信 / 图片过大 / 上传失败
     */
    public Map<String, String> generate(String imageUrl, String productName, String kind) {
        if (!StringUtils.hasText(kind) || !KINDS.contains(kind)) {
            throw BusinessException.validationError("用途只能是 main / texture / craft / scene");
        }
        if (!StringUtils.hasText(imageUrl) || !imageUrl.startsWith("https://")) {
            throw BusinessException.validationError("样图地址必须是 https 图片地址");
        }

        ProductImageClient.GeneratedImage generated = client.generate(imageUrl, productName, kind);
        byte[] bytes = download(generated.imageUrl());
        String extension = detectExtension(bytes);
        if (bytes.length > REENCODE_THRESHOLD) {
            bytes = toJpeg(bytes);
            extension = ".jpg";
        }
        if (bytes.length > MAX_IMAGE_BYTES) {
            throw BusinessException.validationError("生成图过大（超过 5MB），请重试一次或手工上传");
        }

        String filename = "ai-product-" + UUID.randomUUID().toString().replace("-", "") + extension;
        UploadedFileInfo info = fileStorageService.uploadBytes(bytes, filename, "products/ai-generated");
        log.info("商品图生成成功: kind={}, model={}, bytes={}, url={}",
                kind, generated.model(), bytes.length, info.getUrl());
        return Map.of("url", info.getUrl(), "model", generated.model());
    }

    /** 只允许从百炼 OSS 下载（临时 URL 由 ai-agent 原样转回，仍按不可信输入处理）。 */
    private byte[] download(String url) {
        URI uri;
        try {
            uri = URI.create(url);
        } catch (IllegalArgumentException e) {
            throw BusinessException.validationError("生成图地址非法");
        }
        String host = uri.getHost();
        boolean trustedHost = host != null && ALLOWED_DOWNLOAD_SUFFIXES.stream().anyMatch(host::endsWith);
        if (!"https".equalsIgnoreCase(uri.getScheme()) || !trustedHost) {
            log.warn("拒绝下载非百炼 OSS 域名的生成图: {}", url);
            throw BusinessException.validationError("生成图地址不可信，已中止转存");
        }
        try {
            byte[] bytes = downloader.getForObject(uri, byte[].class);
            if (bytes == null || bytes.length == 0) {
                throw BusinessException.validationError("生成图为空，请重试一次");
            }
            return bytes;
        } catch (BusinessException e) {
            throw e;
        } catch (Exception e) {
            log.error("下载生成图失败: url={}, err={}", url, e.getMessage());
            throw BusinessException.validationError("下载生成图失败，请重试一次");
        }
    }

    private String detectExtension(byte[] bytes) {
        if (bytes.length >= 4 && (bytes[0] & 0xFF) == 0x89 && bytes[1] == 'P' && bytes[2] == 'N' && bytes[3] == 'G') {
            return ".png";
        }
        if (bytes.length >= 3 && (bytes[0] & 0xFF) == 0xFF && (bytes[1] & 0xFF) == 0xD8) {
            return ".jpg";
        }
        throw BusinessException.validationError("生成图格式不支持（只接受 PNG/JPEG），请重试一次");
    }

    /** PNG 照片压成 JPEG（仅在超阈值时走；白底填充避免透明通道变黑）。 */
    private byte[] toJpeg(byte[] source) {
        try {
            BufferedImage image = ImageIO.read(new ByteArrayInputStream(source));
            if (image == null) {
                return source;
            }
            BufferedImage rgb = new BufferedImage(image.getWidth(), image.getHeight(), BufferedImage.TYPE_INT_RGB);
            Graphics2D graphics = rgb.createGraphics();
            try {
                graphics.drawImage(image, 0, 0, Color.WHITE, null);
            } finally {
                graphics.dispose();
            }
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            ImageWriter writer = ImageIO.getImageWritersByFormatName("jpeg").next();
            ImageWriteParam param = writer.getDefaultWriteParam();
            param.setCompressionMode(ImageWriteParam.MODE_EXPLICIT);
            param.setCompressionQuality(0.9f);
            try (ImageOutputStream stream = ImageIO.createImageOutputStream(out)) {
                writer.setOutput(stream);
                writer.write(null, new IIOImage(rgb, null, null), param);
            } finally {
                writer.dispose();
            }
            return out.toByteArray();
        } catch (Exception e) {
            log.warn("生成图压缩失败，按原图继续: {}", e.getMessage());
            return source;
        }
    }

    /** 前端展示用的用途文案（与 KINDS 同源；未知取值回落主图）。 */
    public static String kindLabel(String kind) {
        return switch (kind == null ? "" : kind.toLowerCase(Locale.ROOT)) {
            case "texture" -> "材质细节";
            case "craft" -> "工艺细节";
            case "scene" -> "场景图";
            default -> "主图";
        };
    }
}
