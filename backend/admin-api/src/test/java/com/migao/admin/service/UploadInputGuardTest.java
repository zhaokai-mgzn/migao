// case_ids: DF-010, DF-011
package com.migao.admin.service;

import com.migao.admin.config.OssConfig;
import com.migao.admin.dto.UploadedFileInfo;
import com.migao.admin.exception.BusinessException;
import com.aliyun.oss.OSS;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.api.io.TempDir;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

import static com.migao.admin.service.UploadGuardFixtures.HOSTILE_INPUT_DOC;
import static com.migao.admin.service.UploadGuardFixtures.JPEG_MAGIC;
import static com.migao.admin.service.UploadGuardFixtures.PDF_MAGIC;
import static com.migao.admin.service.UploadGuardFixtures.PNG_MAGIC;
import static com.migao.admin.service.UploadGuardFixtures.TRAVERSAL_DIRECTORIES;
import static com.migao.admin.service.UploadGuardFixtures.bytes;
import static com.migao.admin.service.UploadGuardFixtures.hostileInputs;
import static com.migao.admin.service.UploadGuardFixtures.orNull;
import static com.migao.admin.service.UploadGuardFixtures.realFile;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;

/**
 * 上传端点族护栏的**端到端**判据（issue #6207 + #6208）——只经
 * {@code FileStorageService#upload} 这条**公开入口**取证，于是「接线是否真的串上」
 * 与「拒绝时有没有副作用」都在判据里。
 *
 * <ul>
 *   <li>#6207：类型按**魔数**判、大小按**服务端计数**，不信客户端 {@code Content-Type} / 扩展名；
 *       超限 / 伪装 ⇒ 4xx 且**不落 OSS、不落盘**；</li>
 *   <li>#6208：路径穿越 ⇒ 4xx；越界目录在**任何 SDK 被调用之前**就被拒。</li>
 * </ul>
 *
 * <p>三份判据的分工：本类 = 端到端副作用与故障机理；
 * {@code FileStorageServiceTest} = 模板契约 + 两个实现**同源**（含判别力自证控制组）；
 * {@code UploadGuardTest} = 护栏自身的判据（纯函数面，不碰存储）。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("上传端点族护栏端到端（#6207 字节流判类型 / #6208 越界零副作用）")
class UploadInputGuardTest {

    private static final String BUCKET = "ai-customer-service-admin-dev";
    private static final String URL_PREFIX = "https://admin.migaozn.com";

    @Mock
    private OSS ossClient;

    @Mock
    private OssConfig ossConfig;

    /** 本地实现的落盘根：每个用例一个空目录 ⇒ 「零副作用」可逐文件枚举取证。 */
    @TempDir
    Path uploadsRoot;

    private OssService oss;
    private LocalFileStorageService local;

    @BeforeEach
    void setUp() {
        lenient().when(ossConfig.getBucketName()).thenReturn(BUCKET);
        lenient().when(ossConfig.getEndpoint()).thenReturn("oss-cn-hangzhou.aliyuncs.com");
        lenient().when(ossConfig.getUrlPrefix()).thenReturn(URL_PREFIX);
        lenient().when(ossConfig.getPermanentBucketName()).thenReturn(BUCKET);
        lenient().when(ossConfig.getTemporaryBucketName()).thenReturn("ai-customer-service-chat-dev");

        oss = new OssService(ossClient, ossConfig);
        local = new LocalFileStorageService();
        // 落盘根指到临时目录：合法上传真的写、恶意上传一字节都不该写
        ReflectionTestUtils.setField(local, "uploadDir", uploadsRoot.toString());
        // 真 SDK 的 objectKey 契约（阿里云 OSS：key 不得以 '/' 开头、不得含 '../' 段）——
        // mock 默认「照单全收」会掩盖 issue #6208 的实测故障形态（越界目录 ⇒ 客户端 putObject
        // 抛 IllegalArgumentException ⇒ 全局兜底 500 INTERNAL_ERROR）。这里把它照实模拟。
        lenient().doAnswer(invocation -> {
            String objectKey = invocation.getArgument(1);
            if (objectKey.startsWith("/") || objectKey.contains("../")) {
                throw new IllegalArgumentException("InvalidObjectKey: " + objectKey);
            }
            return null;
        }).when(ossClient).putObject(anyString(), anyString(), any(InputStream.class), any());
    }

    // ==================================================== #6207

    @Test
    @DisplayName("#6207-1 声明 application/pdf 但字节流是 PDF、扩展名 .png、19.9MB ⇒ 4xx 且不落 OSS")
    void declaredPdfButPngExtensionOversizeRejected() {
        MultipartFile file = new MockMultipartFile("file", "big19.png", "application/pdf",
                bytes(PDF_MAGIC, 19_922_953));

        assertThatThrownBy(() -> oss.upload(file, "images"))
                .as("声明 PDF + .png 扩展名 + 19.9MB —— 旧实现按 pdf 类型放行 20MB 上限并被 OSS 收下")
                .isInstanceOf(BusinessException.class);

        verify(ossClient, never()).putObject(anyString(), anyString(), any(InputStream.class), any());
        assertThat(localFiles()).as("拒绝的请求不得产生任何本地文件").isEmpty();
    }

    @Test
    @DisplayName("#6207-1 内容 6MB 的图片（魔数合法）⇒ 4xx（服务端按字节计数，不看客户端声明）")
    void oversizeImageRejectedByActualBytes() {
        MultipartFile realPng6mb = new MockMultipartFile("file", "big6.png", "image/png",
                bytes(PNG_MAGIC, 6_291_525));

        assertThatThrownBy(() -> oss.upload(realPng6mb, "images"))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> assertThat(((BusinessException) ex).getHttpStatus()).isBetween(400, 499));

        verify(ossClient, never()).putObject(anyString(), anyString(), any(InputStream.class), any());
        assertThat(localFiles()).isEmpty();
    }

    @Test
    @DisplayName("#6207-3 声明图片但内容非图片（.png + 文本字节流）⇒ 4xx 且不落 OSS / 不落盘")
    void declaredImageButNotAnImageRejected() {
        MultipartFile textAsPng = new MockMultipartFile("file", "fake.png", "image/png",
                "not really a PNG".getBytes(StandardCharsets.UTF_8));

        assertThatThrownBy(() -> oss.upload(textAsPng, "images"))
                .isInstanceOf(BusinessException.class);
        assertThatThrownBy(() -> local.upload(textAsPng, "images"))
                .isInstanceOf(BusinessException.class);

        verify(ossClient, never()).putObject(anyString(), anyString(), any(InputStream.class), any());
        assertThat(localFiles()).isEmpty();
    }

    @Test
    @DisplayName("#6207-3 内容类型与扩展名不符（.png 扩展名 + 真 PDF 字节流）⇒ 4xx")
    void extensionContentMismatchRejected() {
        MultipartFile pdfNamedPng = new MockMultipartFile("file", "report.png", "image/png",
                bytes(PDF_MAGIC, 1024));

        assertThatThrownBy(() -> oss.upload(pdfNamedPng, "images"))
                .isInstanceOf(BusinessException.class);

        verify(ossClient, never()).putObject(anyString(), anyString(), any(InputStream.class), any());
    }

    @Test
    @DisplayName("#6207 边界：合法 png/jpg/pdf 仍 200（既有合法上传路径行为不变）")
    void legitimateUploadsStillSucceed() {
        UploadedFileInfo png = oss.upload(realFile("cover.png", "image/png", PNG_MAGIC), "products");
        UploadedFileInfo jpg = oss.upload(realFile("photo.jpg", "image/jpeg", JPEG_MAGIC), "products");
        UploadedFileInfo pdf = oss.upload(realFile("doc.pdf", "application/pdf", PDF_MAGIC), "docs");

        assertThat(png.getUrl()).startsWith(URL_PREFIX + "/").contains("products/");
        assertThat(jpg.getUrl()).contains("products/");
        assertThat(pdf.getUrl()).contains("docs/");

        assertThat(local.upload(realFile("cover.png", "image/png", PNG_MAGIC), "products").getUrl())
                .startsWith("/api/files/static/products/");
        assertThat(localFiles()).as("合法上传必须真的落了盘（否则「零副作用」是空判据）").isNotEmpty();
    }

    // ==================================================== #6208

    @Test
    @DisplayName("#6208-1 路径穿越（../、绝对路径、..%2f 编码形态）⇒ 4xx 且零副作用")
    void traversalDirectoriesRejectedWithoutSideEffects() {
        for (String evil : TRAVERSAL_DIRECTORIES) {
            assertThatThrownBy(() -> oss.upload(realFile("a.png", "image/png", PNG_MAGIC), evil))
                    .as("OSS 实现必须拒绝 directory=%s", evil)
                    .isInstanceOf(BusinessException.class);
            assertThatThrownBy(() -> local.upload(realFile("a.png", "image/png", PNG_MAGIC), evil))
                    .as("本地实现必须拒绝 directory=%s", evil)
                    .isInstanceOf(BusinessException.class);
        }

        verify(ossClient, never()).putObject(anyString(), anyString(), any(InputStream.class), any());
        assertThat(localFiles()).as("穿越请求不得在 uploads 根内外产生任何文件").isEmpty();
    }

    @Test
    @DisplayName("#6208 实测形态：directory=../../l2evil ⇒ 422（旧实现是 500 INTERNAL_ERROR）")
    void theObservedTraversalIsNowA422NotA500() {
        // 验收实测（2026-10-03 D3.2）：directory=../../l2evil + 合法 png ⇒ HTTP 500 INTERNAL_ERROR。
        // 真因是越界 objectKey 被 SDK 拒（本类 setUp 已照实模拟该契约）⇒ 全局兜底成 500。
        assertThatThrownBy(() -> oss.upload(realFile("ok.png", "image/png", PNG_MAGIC), "../../l2evil"))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException be = (BusinessException) ex;
                    assertThat(be.getHttpStatus())
                            .as("输入校验失败必须归口 4xx，不是服务端错误 500")
                            .isEqualTo(422);
                    assertThat(be.getCode()).isEqualTo("VALIDATION_ERROR");
                });
        verify(ossClient, never()).putObject(anyString(), anyString(), any(InputStream.class), any());
    }

    @Test
    @DisplayName("#6208 边界：拒绝信不外泄内部堆栈 / 外键名 / 落盘真路径，且一律 4xx")
    void rejectionDoesNotLeakInternals() {
        int rejected = 0;
        for (UploadGuardFixtures.HostileInput hostile : hostileInputs()) {
            for (BusinessException ex : List.of(
                    orNull(() -> oss.upload(hostile.file().get(), hostile.directory())),
                    orNull(() -> local.upload(hostile.file().get(), hostile.directory())))) {
                if (ex == null) {
                    continue;
                }
                rejected++;
                assertThat(ex.getCode() + "|" + ex.getMessage() + "|" + ex.getSuggestion())
                        .as("%s 的拒绝信不得外泄内部标识", hostile.label())
                        .doesNotContain("Exception")
                        .doesNotContain("java.")
                        .doesNotContain(".java")
                        .doesNotContain("uploads/")
                        .doesNotContain("at com.migao");
                assertThat(ex.getHttpStatus())
                        .as("%s 的拒绝必须是 4xx（输入校验失败不是服务端错误）", hostile.label())
                        .isBetween(400, 499);
            }
        }
        assertThat(rejected)
                .as("语料必须真的被拒（%s）—— 全数放行说明判据空转", HOSTILE_INPUT_DOC)
                .isPositive();
    }

    // ==================================================== 夹具

    /** 本地文件枚举（临时落盘根）。 */
    private List<Path> localFiles() {
        try (var stream = Files.walk(uploadsRoot)) {
            return stream.filter(Files::isRegularFile).toList();
        } catch (IOException e) {
            throw new AssertionError("枚举落盘文件失败", e);
        }
    }
}
