package com.migao.admin.service;

import com.migao.admin.dto.UploadedFileInfo;
import com.migao.admin.exception.BusinessException;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.mock.web.MockMultipartFile;

import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@DisplayName("LocalFileStorageService 本地文件存储测试")
class LocalFileStorageServiceTest {

    private final LocalFileStorageService service = new LocalFileStorageService();

    @Nested
    @DisplayName("upload")
    class Upload {

        @Test
        @DisplayName("上传图片成功 → 返回 UploadedFileInfo")
        void imageSuccess() {
            MockMultipartFile file = new MockMultipartFile(
                    "file", "test.jpg", "image/jpeg", "hello".getBytes());

            UploadedFileInfo info = service.upload(file, "test-dir");

            assertThat(info.getName()).isEqualTo("test.jpg");
            assertThat(info.getSize()).isEqualTo(5L);
            assertThat(info.getUrl()).startsWith("/api/files/static/test-dir/");
        }

        @Test
        @DisplayName("上传 PDF 成功")
        void pdfSuccess() {
            MockMultipartFile file = new MockMultipartFile(
                    "file", "doc.pdf", "application/pdf", new byte[100]);

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
