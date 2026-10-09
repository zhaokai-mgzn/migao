// case_ids: DF-010, DF-011
package com.migao.admin.service;

import com.migao.admin.exception.BusinessException;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.mock.web.MockMultipartFile;

import java.nio.charset.StandardCharsets;

import static com.migao.admin.service.UploadGuardFixtures.GIF_MAGIC;
import static com.migao.admin.service.UploadGuardFixtures.JPEG_MAGIC;
import static com.migao.admin.service.UploadGuardFixtures.PDF_MAGIC;
import static com.migao.admin.service.UploadGuardFixtures.PNG_MAGIC;
import static com.migao.admin.service.UploadGuardFixtures.bytes;
import static com.migao.admin.service.UploadGuardFixtures.realFile;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * {@code UploadGuard} 自身的判据（issue #6207 / #6208）——**不碰任何存储实现**，
 * 读数为「护栏给什么判据」，与「实现有没有接上」互不遮蔽。
 *
 * <p>接线面（两个实现是否共用这一份）由 {@code FileStorageServiceTest} 与
 * {@code UploadInputGuardTest} 承担。</p>
 */
@DisplayName("UploadGuard：按字节流判类型 / 大小 / 目录（#6207 #6208）")
class UploadGuardTest {

    // ==================================================== 类型：按魔数

    @ParameterizedTest
    @CsvSource({
            "image/png, image/png",
            "image/jpeg, image/jpeg",
            "image/gif, image/gif",
            "'application/pdf', application/pdf"
    })
    @DisplayName("detectType：按魔数认出 png / jpeg / gif / pdf（不看文件名与 Content-Type）")
    void detectsTypeByMagicBytes(String declaredContentTypeIgnored, String expected) {
        MockMultipartFile file = new MockMultipartFile("file", "whatever.bin", declaredContentTypeIgnored,
                magicFor(expected));

        assertThat(UploadGuard.detectType(file))
                .as("内容是真 %s ⇒ 必须认出来（声明的 Content-Type 不参与判定）", expected)
                .isEqualTo(expected);
    }

    @Test
    @DisplayName("detectType：文本改名 .png + 伪造 image/png ⇒ 认不出（null）")
    void textMasqueradingAsImageIsNotRecognised() {
        MockMultipartFile file = new MockMultipartFile("file", "fake.png", "image/png",
                "not really a PNG".getBytes(StandardCharsets.UTF_8));

        assertThat(UploadGuard.detectType(file))
                .as("类型只看字节流 —— 名字与声明都拦不住伪造")
                .isNull();
    }

    @Test
    @DisplayName("detectType：扩展名与内容不符（.png 名 + PDF 字节流）⇒ 内容是 PDF")
    void pdfNamedPngIsDetectedAsPdf() {
        MockMultipartFile file = new MockMultipartFile("file", "report.png", "image/png",
                bytes(PDF_MAGIC, 1024));

        assertThat(UploadGuard.detectType(file)).isEqualTo("application/pdf");
    }

    // ==================================================== 准入：类型 × 大小

    @Test
    @DisplayName("validate：合法 png/jpg/gif/pdf 通过，并回规范化后的目录")
    void legitimateFilesPass() {
        assertThat(UploadGuard.validate(realFile("a.png", "image/png", PNG_MAGIC), " products "))
                .as("目录去掉首尾空白（空白目录名会造出诡异 objectKey）")
                .isEqualTo("products");
        assertThat(UploadGuard.validate(realFile("a.jpg", "image/jpeg", JPEG_MAGIC), "images")).isEqualTo("images");
        assertThat(UploadGuard.validate(realFile("a.gif", "image/gif", GIF_MAGIC), "images")).isEqualTo("images");
        assertThat(UploadGuard.validate(realFile("a.pdf", "application/pdf", PDF_MAGIC), "docs")).isEqualTo("docs");
    }

    @Test
    @DisplayName("validate：内容与扩展名不同类（.png 装 PDF）⇒ 422（否则伪装类型会进对象元数据）")
    void mismatchedFamilyRejected() {
        assertRejected(realFile("report.png", "image/png", PDF_MAGIC), "images");
    }

    @Test
    @DisplayName("validate：5MB 图片上限按字节流算（魔数合法、内容 6MB ⇒ 422）")
    void oversizeImageRejected() {
        MockMultipartFile png6mb = new MockMultipartFile("file", "big6.png", "image/png",
                bytes(PNG_MAGIC, 6_291_525));

        assertRejected(png6mb, "images");
    }

    @Test
    @DisplayName("validate：19.9MB 的 PDF 声明成 .png ⇒ 422（#6207 的实测形态）")
    void declaredPdfAsPngRejected() {
        MockMultipartFile big19 = new MockMultipartFile("file", "big19.png", "application/pdf",
                bytes(PDF_MAGIC, 19_922_953));

        assertRejected(big19, "images");
    }

    @Test
    @DisplayName("validate：扩展名不在允许清单 ⇒ 422（.exe / .csv）")
    void disallowedExtensionsRejected() {
        assertRejected(new MockMultipartFile("file", "script.exe", "application/octet-stream",
                "MZ".getBytes(StandardCharsets.UTF_8)), "images");
        assertRejected(new MockMultipartFile("file", "表格.csv", "text/csv",
                "a,b".getBytes(StandardCharsets.UTF_8)), "images");
    }

    @Test
    @DisplayName("validate：空文件 ⇒ 422")
    void emptyFileRejected() {
        assertRejected(new MockMultipartFile("file", "empty.png", "image/png", new byte[0]), "images");
    }

    @Test
    @DisplayName("validate：合法 PDF 可到 20MB 档（文档上限不被图片 5MB 误伤）")
    void pdfUpToDocumentLimitPasses() {
        MockMultipartFile pdf10mb = new MockMultipartFile("file", "doc.pdf", "application/pdf",
                bytes(PDF_MAGIC, 10 * 1024 * 1024));

        assertThat(UploadGuard.validate(pdf10mb, "docs")).isEqualTo("docs");
    }

    // ==================================================== 目录：穿越

    @ParameterizedTest
    @ValueSource(strings = {
            "../evil",
            "../../l2evil",
            "a/../../evil",
            "/etc/evil",
            "..\\..\\evil",
            "..%2f..%2fevil",
            "images/../../evil",
            "images//../../evil"})
    @DisplayName("resolveDirectory：一切越界形态 ⇒ 422 非法文件路径")
    void traversalRejected(String directory) {
        assertThatThrownBy(() -> UploadGuard.resolveDirectory(directory))
                .as("directory=%s 必须被拒（穿越 / 绝对路径 / 编码形态）", directory)
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException be = (BusinessException) ex;
                    assertThat(be.getCode()).isEqualTo("VALIDATION_ERROR");
                    assertThat(be.getHttpStatus()).isEqualTo(422);
                });
    }

    @Test
    @DisplayName("resolveDirectory：任何 `..` 段一律拒（含回折不出根的 a/../b）—— 与本地实现既有口径一致")
    void anyDotDotSegmentIsRejected() {
        assertThatThrownBy(() -> UploadGuard.resolveDirectory("a/../b"))
                .as("本地实现既有判据就是「含 .. 即拒」（审计 07 P1-7 的 nestedTraversalDirectoryRejected），"
                        + "OSS 侧与它同源 ⇒ 不在这里放宽")
                .isInstanceOf(BusinessException.class);
    }

    @Test
    @DisplayName("resolveDirectory：正常目录原样通过；多斜杠 / ./ 归一化（既有合法形态不误伤）")
    void ordinaryDirectoriesPass() {
        assertThat(UploadGuard.resolveDirectory("images")).isEqualTo("images");
        assertThat(UploadGuard.resolveDirectory("products/123")).isEqualTo("products/123");
        assertThat(UploadGuard.resolveDirectory("a//b")).isEqualTo("a/b");
        assertThat(UploadGuard.resolveDirectory("./a")).isEqualTo("a");
    }

    @Test
    @DisplayName("resolveDirectory：空白目录 ⇒ 空串（由调用方回落默认目录）；控制字符 ⇒ 422")
    void blankAndControlCharacters() {
        assertThat(UploadGuard.resolveDirectory(null)).isEmpty();
        assertThat(UploadGuard.resolveDirectory("")).isEmpty();
        assertThat(UploadGuard.resolveDirectory("  ")).isEmpty();

        assertThatThrownBy(() -> UploadGuard.resolveDirectory("images\u0000evil"))
                .as("NUL / 控制字符不得进 objectKey")
                .isInstanceOf(BusinessException.class);
    }

    @Test
    @DisplayName("resolveDirectory：超长目录段 ⇒ 422（畸形长串不进 objectKey）")
    void overlongDirectoryRejected() {
        assertThatThrownBy(() -> UploadGuard.resolveDirectory("a".repeat(300)))
                .isInstanceOf(BusinessException.class);
    }

    // ==================================================== 拒绝信：不外泄内部标识

    @Test
    @DisplayName("拒绝信只给结论，不带堆栈 / 内部类名 / 落盘真路径")
    void rejectionMessagesLeakNothing() {
        for (String directory : UploadGuardFixtures.TRAVERSAL_DIRECTORIES) {
            BusinessException ex = UploadGuardFixtures.orNull(() -> {
                UploadGuard.resolveDirectory(directory);
                return null;
            });
            assertThat(ex).as("directory=%s 必须被拒", directory).isNotNull();
            assertThat(ex.getCode() + "|" + ex.getMessage() + "|" + ex.getSuggestion())
                    .doesNotContain("Exception")
                    .doesNotContain(".java")
                    .doesNotContain("at com.migao")
                    .doesNotContain("uploads/");
        }
    }

    private static void assertRejected(org.springframework.web.multipart.MultipartFile file, String directory) {
        assertThatThrownBy(() -> UploadGuard.validate(file, directory))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> assertThat(((BusinessException) ex).getCode()).isEqualTo("VALIDATION_ERROR"));
    }

    private static byte[] magicFor(String contentType) {
        return switch (contentType) {
            case "image/png" -> PNG_MAGIC;
            case "image/jpeg" -> JPEG_MAGIC;
            case "image/gif" -> GIF_MAGIC;
            default -> PDF_MAGIC;
        };
    }
}
