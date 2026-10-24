package com.migao.admin.service;

import org.springframework.web.multipart.MultipartFile;

import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;

/**
 * 内存字节 → {@link MultipartFile}（issue #7335）。
 *
 * <p>用途：admin-api 把 AI 生成的图下载到内存后转存 OSS。走 {@code MultipartFile} 而不是
 * 新增一条上传缝，是为了让**用户上传**与**服务端转存**共用同一条准入护栏
 * （{@link FileStorageService#upload} 的 {@link UploadGuard}）—— 不新增第二条绕过校验的路径。</p>
 */
final class InMemoryMultipartFile implements MultipartFile {

    private final String filename;
    private final byte[] bytes;

    InMemoryMultipartFile(String filename, byte[] bytes) {
        this.filename = filename;
        this.bytes = bytes == null ? new byte[0] : bytes;
    }

    @Override
    public String getName() {
        return "file";
    }

    @Override
    public String getOriginalFilename() {
        return filename;
    }

    @Override
    public String getContentType() {
        // 不声明具体类型：护栏只看**字节魔数**（UploadGuard 的口径），声明值不可信。
        return "application/octet-stream";
    }

    @Override
    public boolean isEmpty() {
        return bytes.length == 0;
    }

    @Override
    public long getSize() {
        return bytes.length;
    }

    @Override
    public byte[] getBytes() {
        return bytes;
    }

    @Override
    public InputStream getInputStream() {
        return new ByteArrayInputStream(bytes);
    }

    @Override
    public void transferTo(File dest) throws IOException {
        Files.write(dest.toPath(), bytes);
    }
}
