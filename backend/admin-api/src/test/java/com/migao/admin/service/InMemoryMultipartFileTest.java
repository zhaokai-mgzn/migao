package com.migao.admin.service;

// case_ids: UI-129

import com.migao.admin.dto.UploadedFileInfo;
import com.migao.admin.exception.BusinessException;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.web.multipart.MultipartFile;

import java.util.Base64;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * InMemoryMultipartFile 单测（issue #7335）。
 *
 * <p>判据：</p>
 * <ol>
 *   <li>字节 / 长度 / 文件名 / 空判定原样暴露（转存 OSS 时文件名与内容不能被改写）；</li>
 *   <li>经 {@link FileStorageService#uploadBytes} 走**同一条** UploadGuard：
 *       合法 PNG ⇒ 进入实现；伪装成 .png 的非图片字节 ⇒ 422 且实现**不被调用**。</li>
 * </ol>
 */
@DisplayName("InMemoryMultipartFile（issue #7335）")
class InMemoryMultipartFileTest {

    /** 1×1 PNG（合法魔数）。 */
    private static final byte[] PNG = Base64.getDecoder().decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==");

    /** 记录是否进入落库动作的假存储。 */
    private static final class CapturingStorage implements FileStorageService {
        final AtomicReference<MultipartFile> captured = new AtomicReference<>();

        @Override
        public UploadedFileInfo doUpload(MultipartFile file, String normalizedDirectory) {
            captured.set(file);
            return UploadedFileInfo.builder().url("https://oss/out.png").name(file.getOriginalFilename()).build();
        }

        @Override
        public void delete(String fileUrl) {
        }

        @Override
        public String getStorageType() {
            return "capturing";
        }
    }

    @Test
    @DisplayName("字节 / 长度 / 文件名原样暴露")
    void exposesBytesAndMetadata() throws Exception {
        InMemoryMultipartFile file = new InMemoryMultipartFile("ai-product-1.png", PNG);

        assertThat(file.getOriginalFilename()).isEqualTo("ai-product-1.png");
        assertThat(file.getSize()).isEqualTo(PNG.length);
        assertThat(file.getBytes()).isEqualTo(PNG);
        assertThat(file.isEmpty()).isFalse();
    }

    @Test
    @DisplayName("uploadBytes 走同一条 UploadGuard：合法 PNG 进入实现")
    void uploadBytes_passesGuardForRealImage() throws Exception {
        CapturingStorage storage = new CapturingStorage();

        UploadedFileInfo info = storage.uploadBytes(PNG, "ai-product-1.png", "products/ai-generated");

        assertThat(info.getUrl()).isEqualTo("https://oss/out.png");
        assertThat(storage.captured.get()).isNotNull();
        assertThat(storage.captured.get().getBytes()).isEqualTo(PNG);
    }

    @Test
    @DisplayName("伪装成 .png 的非图片字节 ⇒ 422，实现不被调用")
    void uploadBytes_rejectsFakeImageBeforeSideEffects() {
        CapturingStorage storage = new CapturingStorage();

        assertThatThrownBy(() -> storage.uploadBytes("hello".getBytes(), "ai-product-1.png", "products/ai-generated"))
                .isInstanceOf(BusinessException.class);
        assertThat(storage.captured.get()).isNull();
    }
}
