package com.migao.admin.service;

// case_ids: UI-129

import com.migao.admin.dto.UploadedFileInfo;
import com.migao.admin.exception.BusinessException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.web.client.RestTemplate;

import java.net.URI;
import java.util.Base64;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * ProductImageGenerationService 单测（issue #7335）。
 *
 * <p>判据：</p>
 * <ol>
 *   <li>生成成功 ⇒ 临时图**下载后**走 {@code uploadBytes}（目录 {@code products/ai-generated}），
 *       返回 OSS 永久 URL + 模型名 —— <b>不返回百炼临时地址</b>；</li>
 *   <li>用途白名单 / 样图 http / 临时图非百炼域名 ⇒ 422 且**不发远端生成请求**（SSRF 面收口）；</li>
 *   <li>依赖面恰好 {@link ProductImageClient} + {@link FileStorageService} + 下载器 ——
 *       不塞任何 Mapper（本能力不落库）。</li>
 * </ol>
 */
@DisplayName("ProductImageGenerationService（issue #7335）")
class ProductImageGenerationServiceTest {

    /** 1×1 PNG（只看魔数判类型，不需要真实尺寸）。 */
    private static final byte[] PNG = Base64.getDecoder().decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==");

    private ProductImageClient client;
    private FileStorageService storage;
    private RestTemplate downloader;
    private ProductImageGenerationService service;

    @BeforeEach
    void setUp() {
        client = mock(ProductImageClient.class);
        storage = mock(FileStorageService.class);
        downloader = mock(RestTemplate.class);
        service = new ProductImageGenerationService(client, storage, downloader);
    }

    @Test
    @DisplayName("成功：下载临时图 → uploadBytes → 返回 OSS 永久 URL（不返回临时地址）")
    void generate_downloadsAndStoresPermanently() {
        when(client.generate("https://oss.example.com/sample.png", "回归布帘", "main"))
                .thenReturn(new ProductImageClient.GeneratedImage(
                        "https://dashscope-0484.oss-accelerate.aliyuncs.com/tmp/out.png", "qwen-image-3.0"));
        when(downloader.getForObject(any(URI.class), eq(byte[].class))).thenReturn(PNG);
        when(storage.uploadBytes(any(byte[].class), anyString(), eq("products/ai-generated")))
                .thenReturn(UploadedFileInfo.builder().url("https://oss/permanent.png").build());

        Map<String, String> result = service.generate("https://oss.example.com/sample.png", "回归布帘", "main");

        assertThat(result).containsEntry("url", "https://oss/permanent.png")
                .containsEntry("model", "qwen-image-3.0");
        ArgumentCaptor<String> filename = ArgumentCaptor.forClass(String.class);
        verify(storage).uploadBytes(any(byte[].class), filename.capture(), eq("products/ai-generated"));
        assertThat(filename.getValue()).startsWith("ai-product-").endsWith(".png");
    }

    @Test
    @DisplayName("用途非白名单 ⇒ 422，且不发起生成请求")
    void unknownKind_rejected() {
        assertThatThrownBy(() -> service.generate("https://oss.example.com/s.png", "某商品", "banner"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("用途");
        verifyNoInteractions(client);
    }

    @Test
    @DisplayName("样图必须是 https ⇒ 否则 422，且不发起生成请求")
    void httpSample_rejected() {
        assertThatThrownBy(() -> service.generate("http://oss.example.com/s.png", "某商品", "main"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("https");
        verifyNoInteractions(client);
    }

    @Test
    @DisplayName("临时图域名不是百炼 OSS ⇒ 422，不下载（SSRF 面）")
    void untrustedDownloadHost_rejected() {
        when(client.generate(anyString(), anyString(), anyString()))
                .thenReturn(new ProductImageClient.GeneratedImage("https://evil.example.com/x.png", "m"));

        assertThatThrownBy(() -> service.generate("https://oss.example.com/s.png", "某商品", "main"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("不可信");
        verify(downloader, never()).getForObject(any(URI.class), eq(byte[].class));
        verifyNoInteractions(storage);
    }

    @Test
    @DisplayName("依赖面：只有 client + storage + 下载器（无 Mapper = 不落库）")
    void dependencySurfaceHasNoWriters() {
        var instanceFields = java.util.Arrays.stream(ProductImageGenerationService.class.getDeclaredFields())
                .filter(f -> !java.lang.reflect.Modifier.isStatic(f.getModifiers()))
                .map(java.lang.reflect.Field::getType)
                .toList();
        assertThat(instanceFields)
                .containsExactlyInAnyOrder(ProductImageClient.class, FileStorageService.class, RestTemplate.class);
    }

    @Test
    @DisplayName("客户端 422 原样上抛（不吞成「生成失败」）")
    void clientFailure_propagates() {
        when(client.generate(anyString(), anyString(), anyString()))
                .thenThrow(new BusinessException(ProductImageClient.ERR_AI_IMAGE_UNAVAILABLE, "服务不可用", 422));

        assertThatThrownBy(() -> service.generate("https://oss.example.com/s.png", "某商品", "main"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("服务不可用");
        verifyNoInteractions(storage);
    }
}
