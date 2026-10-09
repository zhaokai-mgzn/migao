package com.migao.admin.service;
// case_ids: DF-010

import com.migao.admin.dto.UploadedFileInfo;
import com.migao.admin.exception.BusinessException;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.util.ReflectionTestUtils;

import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@DisplayName("LocalFileStorageService 本地文件存储测试")
class LocalFileStorageServiceTest {

    /** 真魔数（issue #6207 起类型按**字节流**判，不再认扩展名 / Content-Type 的声明）。 */
    private static final byte[] PNG_MAGIC = {(byte) 0x89, 'P', 'N', 'G', 0x0D, 0x0A, 0x1A, 0x0A};
    private static final byte[] JPEG_MAGIC = {(byte) 0xFF, (byte) 0xD8, (byte) 0xFF, (byte) 0xE0};
    private static final byte[] PDF_MAGIC = {'%', 'P', 'D', 'F', '-'};

    /** 落盘根指向临时目录（与生产行为同构，且不给仓库工作区留垃圾文件）。 */
    @TempDir
    Path uploadsRoot;

    private final LocalFileStorageService service = new LocalFileStorageService();

    @org.junit.jupiter.api.BeforeEach
    void pointUploadDirAtTempDir() {
        ReflectionTestUtils.setField(service, "uploadDir", uploadsRoot.toString());
    }

    @Nested
    @DisplayName("upload")
    class Upload {

        @Test
        @DisplayName("目录参数路径穿越（../）→ 拒绝（审计 07 P1-7）")
        void traversalDirectoryRejected() {
            MockMultipartFile file = new MockMultipartFile(
                    "file", "test.jpg", "image/jpeg", JPEG_MAGIC);

            assertThatThrownBy(() -> service.upload(file, "../evil"))
                    .isInstanceOf(BusinessException.class);
        }

        @Test
        @DisplayName("目录参数嵌套穿越（a/../../evil）→ 拒绝")
        void nestedTraversalDirectoryRejected() {
            MockMultipartFile file = new MockMultipartFile(
                    "file", "test.jpg", "image/jpeg", JPEG_MAGIC);

            assertThatThrownBy(() -> service.upload(file, "a/../../evil"))
                    .isInstanceOf(BusinessException.class);
        }

        @Test
        @DisplayName("上传图片成功 → 返回 UploadedFileInfo")
        void imageSuccess() {
            MockMultipartFile file = new MockMultipartFile(
                    "file", "test.jpg", "image/jpeg", JPEG_MAGIC);

            UploadedFileInfo info = service.upload(file, "test-dir");

            assertThat(info.getName()).isEqualTo("test.jpg");
            assertThat(info.getSize()).isEqualTo(4L);
            assertThat(info.getUrl()).startsWith("/api/files/static/test-dir/");
        }

        @Test
        @DisplayName("上传 PDF 成功")
        void pdfSuccess() {
            MockMultipartFile file = new MockMultipartFile(
                    "file", "doc.pdf", "application/pdf", PDF_MAGIC);

            UploadedFileInfo info = service.upload(file, "docs");

            assertThat(info.getName()).isEqualTo("doc.pdf");
            assertThat(info.getType()).isEqualTo("application/pdf");
        }

        @Test
        @DisplayName("文件为空 → VALIDATION_ERROR")
        void emptyFile() {
            MockMultipartFile file = new MockMultipartFile(
                    "file", "empty.jpg", "image/jpeg", new byte[0]);

            assertThatThrownBy(() -> service.upload(file, "dir"))
                    .isInstanceOf(BusinessException.class)
                    .satisfies(ex -> assertThat(((BusinessException) ex).getCode()).isEqualTo("VALIDATION_ERROR"));
        }

        @Test
        @DisplayName("不支持的文件类型 → VALIDATION_ERROR")
        void invalidExtension() {
            MockMultipartFile file = new MockMultipartFile(
                    "file", "script.exe", "application/octet-stream", "bad".getBytes());

            assertThatThrownBy(() -> service.upload(file, "dir"))
                    .isInstanceOf(BusinessException.class);
        }
    }

    @Nested
    @DisplayName("delete")
    class Delete {

        @Test
        @DisplayName("路径穿越删除（../../application.yml）→ 拒绝（审计 07 P1-7）")
        void traversalDeleteRejected() {
            assertThatThrownBy(() -> service.delete("../../application.yml"))
                    .isInstanceOf(BusinessException.class);
        }

        @Test
        @DisplayName("删除不存在的文件不报错")
        void nonExistent() {
            service.delete("nonexistent-file-url");
        }

        @Test
        @DisplayName("URL 为空直接返回")
        void emptyUrl() {
            service.delete("");
            service.delete(null);
        }
    }

    @Nested
    @DisplayName("getStorageType")
    class GetStorageType {

        @Test
        @DisplayName("返回 local")
        void returnsLocal() {
            assertThat(service.getStorageType()).isEqualTo("local");
        }
    }
}
