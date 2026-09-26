// case_ids: PR-116
package com.migao.admin.controller;

import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.dto.UploadedFileInfo;
import com.migao.admin.service.FileStorageService;
import com.migao.admin.service.WorkerInboundService;
import com.migao.admin.worker.WorkerIdentity;
import com.migao.admin.worker.WorkerSessionService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import javax.imageio.ImageIO;
import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 工人可达的**照片上传**端点（issue #5052 P2；设计 §5.2 / §9.3）。
 *
 * <p>这是 P1 留下的**真缺口**的补口：P1 的 {@code recognize} 收的是「已上传好的 URL」，
 * 而现有一切上传端点都在 {@code /api/admin/**} 且带商家权限码 ⇒ 工人根本够不着
 * ⇒ 「拍照入库」在 P1 之后仍然拍不成。</p>
 *
 * <h3>红证（改坏 ⇒ 必红）</h3>
 * <ul>
 *   <li>给本端点加 {@code @RequirePermission}（或把路径挪到 {@code /api/admin/**}）⇒
 *       {@code workerUploadsWithoutAnyMerchantPermissionCode} 与
 *       {@code InboundLabelSurfaceGuardTest#workerPhotoSurfaceCarriesNoMerchantPermissionCode} 红；</li>
 *   <li>只信 {@code Content-Type} 不验内容（去掉 {@code ImageIO} 那一道）⇒
 *       {@code aTextFileWithAForgedImageMimeTypeIs400} 红（伪造 MIME 的文本会 200 进 OSS）；</li>
 *   <li>把张数上限从 {@code WorkerInboundService.MAX_IMAGES} 改成自己写的数字 ⇒
 *       {@code moreThanThreePhotosIs400} 与 {@code zeroPhotosIs400} 一起红。</li>
 * </ul>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("WorkerInboundUploadController（#5052 P2）：工人可达的图片上传")
class WorkerInboundUploadControllerTest {

    @Mock private FileStorageService fileStorageService;
    @Mock private WorkerSessionService workerSessionService;

    private MockMvc mockMvc;

    private static final String SESSION = "sess-zhang-1";
    private static final String URL = "https://cdn.example.com/inbound/2026/09/26/a.png";

    @BeforeEach
    void setUp() {
        when(workerSessionService.resolveIdentity(SESSION)).thenReturn(
                new WorkerIdentity("w-1", "张三", WorkerIdentity.SOURCE_SERVER_SESSION, SESSION));
        when(fileStorageService.upload(any(), anyString())).thenReturn(
                UploadedFileInfo.builder().id("f-1").url(URL).name("a.png").size(10L).type("image/png").build());

        WorkerInboundUploadController controller =
                new WorkerInboundUploadController(fileStorageService, workerSessionService);
        mockMvc = MockMvcBuilders.standaloneSetup(controller)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    @Test
    @DisplayName("🔴 无工人 session ⇒ 401，且一张都不落存储")
    void withoutWorkerSessionIs401() throws Exception {
        mockMvc.perform(multipart("/api/worker/inbound/upload")
                        .file(new MockMultipartFile("files", "a.png", "image/png", png(10, 10))))
                .andExpect(status().isUnauthorized());

        verify(fileStorageService, never()).upload(any(), anyString());
    }

    @Test
    @DisplayName("🔴 工人零商家权限码也能上传（本路径不查商家码，只认工人 session）")
    void workerUploadsWithoutAnyMerchantPermissionCode() throws Exception {
        mockMvc.perform(multipart("/api/worker/inbound/upload")
                        .file(new MockMultipartFile("files", "a.png", "image/png", png(20, 10)))
                        .header(WorkerSessionService.SESSION_HEADER, SESSION))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data[0].url").value(URL));

        // 复用既有存储（目录语义化 = inbound），不新造存储
        verify(fileStorageService).upload(any(), eq(WorkerInboundUploadController.DIRECTORY));
    }

    @Test
    @DisplayName("非图片（PDF / 文本 / 无类型）⇒ 400，且不落存储")
    void nonImagesAre400() throws Exception {
        mockMvc.perform(multipart("/api/worker/inbound/upload")
                        .file(new MockMultipartFile("files", "a.pdf", "application/pdf", "%PDF-1.4".getBytes(StandardCharsets.UTF_8)))
                        .header(WorkerSessionService.SESSION_HEADER, SESSION))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error.code").value("INBOUND_UPLOAD_NOT_IMAGE"));

        mockMvc.perform(multipart("/api/worker/inbound/upload")
                        .file(new MockMultipartFile("files", "a.txt", "text/plain", "hello".getBytes(StandardCharsets.UTF_8)))
                        .header(WorkerSessionService.SESSION_HEADER, SESSION))
                .andExpect(status().isBadRequest());

        verify(fileStorageService, never()).upload(any(), anyString());
    }

    @Test
    @DisplayName("🔴 伪造 MIME 的文本 ⇒ 400（按**内容**判，不按扩展名 / Content-Type 判）")
    void aTextFileWithAForgedImageMimeTypeIs400() throws Exception {
        mockMvc.perform(multipart("/api/worker/inbound/upload")
                        .file(new MockMultipartFile("files", "a.png", "image/png",
                                "this is definitely not a png".getBytes(StandardCharsets.UTF_8)))
                        .header(WorkerSessionService.SESSION_HEADER, SESSION))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error.code").value("INBOUND_UPLOAD_NOT_DECODABLE"));

        verify(fileStorageService, never()).upload(any(), anyString());
    }

    @Test
    @DisplayName("🔴 张数越界（0 张 / 4 张）⇒ 400，上限与识别端点**同一常量**")
    void moreThanThreePhotosIs400() throws Exception {
        mockMvc.perform(multipart("/api/worker/inbound/upload")
                        .header(WorkerSessionService.SESSION_HEADER, SESSION))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error.code").value("INBOUND_UPLOAD_NO_FILE"));

        mockMvc.perform(multipart("/api/worker/inbound/upload")
                        .file(png("1.png"))
                        .file(png("2.png"))
                        .file(png("3.png"))
                        .file(png("4.png"))
                        .header(WorkerSessionService.SESSION_HEADER, SESSION))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error.code").value("INBOUND_UPLOAD_TOO_MANY_FILES"));

        verify(fileStorageService, never()).upload(any(), anyString());
        org.assertj.core.api.Assertions.assertThat(WorkerInboundService.MAX_IMAGES).isEqualTo(3);
    }

    @Test
    @DisplayName("空文件 / 超大小（>5MB）/ 超像素（单边 >8000）⇒ 400")
    void oversizeAndUndecodableInputsAre400() throws Exception {
        mockMvc.perform(multipart("/api/worker/inbound/upload")
                        .file(new MockMultipartFile("files", "empty.png", "image/png", new byte[0]))
                        .header(WorkerSessionService.SESSION_HEADER, SESSION))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error.code").value("INBOUND_UPLOAD_EMPTY_FILE"));

        mockMvc.perform(multipart("/api/worker/inbound/upload")
                        .file(new MockMultipartFile("files", "big.png", "image/png",
                                new byte[(int) WorkerInboundUploadController.MAX_IMAGE_BYTES + 1]))
                        .header(WorkerSessionService.SESSION_HEADER, SESSION))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error.code").value("INBOUND_UPLOAD_TOO_LARGE"));

        mockMvc.perform(multipart("/api/worker/inbound/upload")
                        .file(new MockMultipartFile("files", "wide.png", "image/png",
                                png(WorkerInboundUploadController.MAX_IMAGE_EDGE_PX + 1, 1)))
                        .header(WorkerSessionService.SESSION_HEADER, SESSION))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error.code").value("INBOUND_UPLOAD_TOO_LARGE_PIXELS"));

        verify(fileStorageService, never()).upload(any(), anyString());
    }

    @Test
    @DisplayName("三张合法照片 ⇒ 200 + 三个 URL（张数上限内全部上传）")
    void threeValidPhotosAreUploaded() throws Exception {
        mockMvc.perform(multipart("/api/worker/inbound/upload")
                        .file(png("1.png")).file(png("2.png")).file(png("3.png"))
                        .header(WorkerSessionService.SESSION_HEADER, SESSION))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.length()").value(3))
                .andExpect(jsonPath("$.data[2].url").value(URL));
    }

    // ============================================================ 夹具

    private static MockMultipartFile png(String name) throws IOException {
        return new MockMultipartFile("files", name, "image/png", png(10, 10));
    }

    /** 真 PNG 字节（判据走 {@code ImageIO} 读图像头 ⇒ 夹具必须是**真图**，不能用假字节）。 */
    private static byte[] png(int width, int height) throws IOException {
        BufferedImage image = new BufferedImage(width, height, BufferedImage.TYPE_INT_RGB);
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        ImageIO.write(image, "png", out);
        return out.toByteArray();
    }
}
