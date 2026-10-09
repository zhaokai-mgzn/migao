package com.migao.admin.service;

import com.migao.admin.exception.BusinessException;
import org.springframework.util.StringUtils;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.io.InputStream;
import java.util.Arrays;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/**
 * 上传 / 存储端点族的**输入护栏**（issue #6207 + #6208）——
 * {@link OssService} 与 {@link LocalFileStorageService} 的**同一份**准入判据。
 *
 * <h3>为什么必须是「同一份」（#6208 的根因）</h3>
 * <p>2026-10-03 验收实测：同一语义的护栏在两个实现里**分叉**——本地实现有
 * {@code safeResolve}（{@code ../} ⇒ 422），而运行的 OSS 实现 {@code generateObjectKey}
 * **零校验**（⇒ 500 {@code INTERNAL_ERROR}）。「改一处」永远追不上「实现 ×2」，
 * 故判据收在一处，两个实现**只消费**它。</p>
 *
 * <h3>为什么按字节流判（#6207 的根因）</h3>
 * <p>实测：{@code big19.png} + {@code Content-Type: application/pdf} + 19.9MB 真实内容 ⇒
 * <b>200</b> 且落 OSS <b>公共可读</b>。根因是大小上限按**客户端声明的** {@code Content-Type}
 * 选（声明 pdf 就走 20MB 档）而类型只按**文件扩展名**判。⇒ 两者都改成
 * <b>只看字节流</b>：类型看魔数、大小看服务端计数。</p>
 *
 * <h3>口径</h3>
 * <ul>
 *   <li>扩展名与内容**都要**在允许清单内，且必须**同一类**（{@code .png} ⇒ PNG 魔数）；
 *       不符即拒 —— 否则「{@code .png} 名 + PDF 内容」会被当成文档放行 20MB，
 *       且伪装的 {@code Content-Type} 会被写进对象元数据、由静态托管原样回给浏览器；</li>
 *   <li>解码失败 / 空文件 / 超限 / 越界目录 ⇒ 一律 {@code VALIDATION_ERROR}（<b>422</b>），
 *       <b>不外泄</b>内部堆栈与外键名；</li>
 *   <li>拒绝发生在**任何副作用之前**（不建目录、不 putObject）。</li>
 * </ul>
 */
final class UploadGuard {

    /** 允许的扩展名（与两个实现既有清单逐字一致，含前端提示文案里列出的那 8 种）。 */
    private static final List<String> ALLOWED_EXTENSIONS =
            List.of(".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf", ".xlsx", ".docx");

    /** 图片最大大小：5MB（与 {@code WorkerInboundUploadController.MAX_IMAGE_BYTES} 同口径）。 */
    private static final long MAX_IMAGE_SIZE = 5 * 1024 * 1024;

    /** 文档最大大小：20MB。 */
    private static final long MAX_DOC_SIZE = 20 * 1024 * 1024;

    /** 目录段长度上限（畸形长串直接拒，防资源放大）。 */
    private static final int MAX_DIRECTORY_LENGTH = 255;

    private static final String ILLEGAL_PATH = "非法文件路径";

    /** 读魔数时最多咀嚼多少字节 —— 够覆盖 PDF 尾注 / zip 的首个中央目录项，且不随文件大小放大。 */
    private static final int MAGIC_SCAN_LIMIT = 8 * 1024;

    private UploadGuard() {
    }

    /**
     * 准入校验：类型（魔数）× 大小（服务端计数）× 目录合法性。
     *
     * @param file      上传文件
     * @param directory 存储目录（用户可控）
     * @return 已规范化的目录（{@code a//b} ⇒ {@code a/b}），供生成 objectKey / URL 使用
     */
    static String validate(MultipartFile file, String directory) {
        if (file == null || file.isEmpty()) {
            throw BusinessException.validationError("请选择要上传的文件");
        }

        String extension = getFileExtension(file.getOriginalFilename()).toLowerCase(Locale.ROOT);
        if (!ALLOWED_EXTENSIONS.contains(extension)) {
            throw BusinessException.validationError(
                    "不支持的文件类型，仅支持 JPG、JPEG、PNG、GIF、WebP、PDF、XLSX、DOCX 格式");
        }

        String detected = detectType(file);
        if (detected == null || !family(detected).equals(family(extension))) {
            throw BusinessException.validationError(
                    "文件内容与扩展名不符：按内容判，不按文件名 / Content-Type 判");
        }

        // 大小按**服务端计数**的字节流，且按**内容**判类型 —— 客户端声明一律不参与
        boolean isImage = "image".equals(family(detected));
        long maxSize = isImage ? MAX_IMAGE_SIZE : MAX_DOC_SIZE;
        if (file.getSize() > maxSize) {
            throw BusinessException.validationError("文件大小不能超过 " + (isImage ? "5MB" : "20MB"));
        }

        return resolveDirectory(directory);
    }

    /**
     * 解析并校验用户可控目录：规范化后必须**位于根内**。
     * 防路径穿越（{@code ../}、绝对路径、{@code ..%2f} 解码形态）导致的越界写 / 越界建前缀。
     *
     * @param directory 用户可控目录；null/空 ⇒ 空（调用方回落到默认目录）
     * @return 规范化后的相对目录
     */
    static String resolveDirectory(String directory) {
        if (!StringUtils.hasText(directory)) {
            return "";
        }
        // 首尾空白去掉：`" products "` 会造出带空格的对象前缀（OSS 与本地两侧都怪异）
        String relative = fullyDecode(directory).replace('\\', '/').strip();
        if (relative.length() > MAX_DIRECTORY_LENGTH) {
            throw BusinessException.validationError(ILLEGAL_PATH);
        }
        for (String segment : relative.split("/", -1)) {
            if ("..".equals(segment)) {
                throw BusinessException.validationError(ILLEGAL_PATH);
            }
        }
        String normalized = normalizeSegments(relative);
        if (normalized.chars().anyMatch(c -> c < 0x20 || c == 0x7F)) {
            throw BusinessException.validationError(ILLEGAL_PATH);
        }
        // 绝对路径（POSIX / 盘符）在 OSS 侧会变成越界 objectKey 前缀，在本地侧会跳出 uploads 根 ⇒ 一律拒
        if (relative.startsWith("/") || relative.matches("^[A-Za-z]:.*")) {
            throw BusinessException.validationError(ILLEGAL_PATH);
        }
        return normalized;
    }

    /**
     * 把**残留的**百分号编码解到底：Spring 只解一层路径变量，{@code ..%2f..%2fevil} 会**原样**
     * 送到服务层（实测 issue #6208：旧实现直接把它拼进 objectKey，本层零校验 ⇒ 该形态放行）。
     *
     * <p>迭代解到不动点（带次数上限，畸形串不会变慢），于是「编码穿越」与「明文穿越」
     * 归到**同一条**判据上 —— 不必为每种编码另写一份正则。</p>
     */
    private static String fullyDecode(String value) {
        String current = value;
        for (int round = 0; round < 3; round++) {
            String decoded = current.replace("%2e", ".").replace("%2E", ".")
                    .replace("%2f", "/").replace("%2F", "/")
                    .replace("%5c", "\\").replace("%5C", "\\");
            if (decoded.equals(current)) {
                return current;
            }
            current = decoded;
        }
        return current;
    }

    /** 去掉空段与「当前目录」段：{@code a//b} / {@code ./a} ⇒ {@code a}。 */
    private static String normalizeSegments(String relative) {
        return Arrays.stream(relative.split("/", -1))
                .filter(segment -> !segment.isEmpty() && !".".equals(segment))
                .reduce((a, b) -> a + "/" + b)
                .orElse("");
    }

    /**
     * 按**魔数**判内容类型（不看扩展名、不看 {@code Content-Type}）。
     *
     * @return 规范化的 MIME 字符串；识别不出 ⇒ {@code null}
     */
    static String detectType(MultipartFile file) {
        byte[] head;
        try (InputStream in = file.getInputStream()) {
            head = in.readNBytes(MAGIC_SCAN_LIMIT);
        } catch (IOException e) {
            return null;
        }
        if (startsWith(head, new int[] {0x89, 'P', 'N', 'G', 0x0D, 0x0A, 0x1A, 0x0A})) {
            return "image/png";
        }
        if (startsWith(head, new int[] {0xFF, 0xD8, 0xFF})) {
            return "image/jpeg";
        }
        if (startsWith(head, new int[] {'G', 'I', 'F', '8'})) {
            return "image/gif";
        }
        if (startsWith(head, new int[] {'B', 'M'})) {
            return "image/bmp";
        }
        if (head.length >= 12 && startsWith(head, new int[] {'R', 'I', 'F', 'F'})
                && head[8] == 'W' && head[9] == 'E' && head[10] == 'B' && head[11] == 'P') {
            return "image/webp";
        }
        if (startsWith(head, new int[] {'%', 'P', 'D', 'F', '-'})) {
            return "application/pdf";
        }
        if (startsWith(head, new int[] {'P', 'K', 0x03, 0x04})) {
            return detectOoxml(head);
        }
        return null;
    }

    /**
     * OOXML（xlsx / docx）都是 zip 容器 —— 看包内首个 OOXML 部件定具体类型，
     * 避免把「zip 改了名」也当表格放行。
     */
    private static String detectOoxml(byte[] head) {
        try (ZipInputStream zip = new ZipInputStream(new java.io.ByteArrayInputStream(head))) {
            for (ZipEntry entry = zip.getNextEntry(); entry != null; entry = zip.getNextEntry()) {
                String name = entry.getName();
                if (name.startsWith("xl/")) {
                    return SHEET_MIME;
                }
                if (name.startsWith("word/")) {
                    return DOC_MIME;
                }
            }
        } catch (IOException ignored) {
            return null;
        }
        return null;
    }

    private static final String SHEET_MIME =
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
    private static final String DOC_MIME =
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

    private static final Map<String, String> FAMILY_BY_EXTENSION = Map.ofEntries(
            Map.entry(".png", "image"), Map.entry(".jpg", "image"), Map.entry(".jpeg", "image"),
            Map.entry(".gif", "image"), Map.entry(".webp", "image"), Map.entry(".bmp", "image"),
            Map.entry(".pdf", "document"), Map.entry(".xlsx", "document"), Map.entry(".docx", "document"));

    /** 扩展名 / 内容类型 → 「图片」或「文档」这一**类**（大小上限按类走）。 */
    private static String family(String type) {
        if (type == null) {
            return "unknown";
        }
        if (type.startsWith("image/")) {
            return "image";
        }
        return FAMILY_BY_EXTENSION.getOrDefault(type.toLowerCase(Locale.ROOT), "document");
    }

    private static boolean startsWith(byte[] data, int[] prefix) {
        if (data.length < prefix.length) {
            return false;
        }
        for (int i = 0; i < prefix.length; i++) {
            if ((data[i] & 0xFF) != prefix[i]) {
                return false;
            }
        }
        return true;
    }

    private static String getFileExtension(String filename) {
        if (!StringUtils.hasText(filename)) {
            return ".jpg";
        }
        int dotIndex = filename.lastIndexOf('.');
        if (dotIndex >= 0) {
            return filename.substring(dotIndex);
        }
        return ".jpg";
    }
}
