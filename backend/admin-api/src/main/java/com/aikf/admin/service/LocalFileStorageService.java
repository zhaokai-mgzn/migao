package com.aikf.admin.service;

import com.aikf.admin.dto.UploadedFileInfo;
import com.aikf.admin.exception.BusinessException;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.time.LocalDateTime;
import java.util.UUID;

/**
 * 本地文件存储服务实现
 * 当 OSS 未配置时作为 fallback 自动降级使用
 */
@Slf4j
@Service
public class LocalFileStorageService implements FileStorageService {

    /**
     * 本地存储根目录
     */
    private static final String UPLOAD_DIR = "uploads";

    /**
     * 静态资源访问路径前缀
     */
    private static final String ACCESS_PATH_PREFIX = "/api/files/static/";

    /**
     * 允许的文件扩展名
     */
    private static final String[] ALLOWED_EXTENSIONS = {
            ".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf", ".xlsx", ".docx"
    };

    /**
     * 图片类型扩展名
     */
    private static final String[] IMAGE_EXTENSIONS = {
            ".jpg", ".jpeg", ".png", ".gif", ".webp"
    };

    /**
     * 图片最大大小：5MB
     */
    private static final long MAX_IMAGE_SIZE = 5 * 1024 * 1024;

    /**
     * 文档最大大小：20MB
     */
    private static final long MAX_DOC_SIZE = 20 * 1024 * 1024;

    @Override
    public UploadedFileInfo upload(MultipartFile file, String directory) {
        validateFile(file);

        String fileId = UUID.randomUUID().toString().replace("-", "");
        String extension = getFileExtension(file.getOriginalFilename());
        String storedFilename = fileId + extension;

        // 构建存储路径：uploads/{directory}/{filename}
        Path uploadPath = Paths.get(UPLOAD_DIR, directory);

        try {
            Files.createDirectories(uploadPath);
            Path filePath = uploadPath.resolve(storedFilename);
            Files.copy(file.getInputStream(), filePath, StandardCopyOption.REPLACE_EXISTING);

            // 构建访问 URL（相对路径，由 Controller 层组装完整 URL）
            String url = ACCESS_PATH_PREFIX + directory + "/" + storedFilename;
            log.info("本地存储文件成功: path={}, url={}", filePath, url);

            return UploadedFileInfo.builder()
                    .id(fileId)
                    .url(url)
                    .name(file.getOriginalFilename())
                    .size(file.getSize())
                    .type(file.getContentType())
                    .createdAt(LocalDateTime.now())
                    .build();

        } catch (IOException e) {
            log.error("本地存储文件失败: {}", e.getMessage(), e);
            throw new BusinessException("UPLOAD_ERROR", "文件上传失败", 500);
        }
    }

    @Override
    public void delete(String fileUrl) {
        if (!StringUtils.hasText(fileUrl)) {
            return;
        }

        // 从 URL 中提取相对路径
        String relativePath = fileUrl;
        if (fileUrl.startsWith(ACCESS_PATH_PREFIX)) {
            relativePath = fileUrl.substring(ACCESS_PATH_PREFIX.length());
        }

        Path filePath = Paths.get(UPLOAD_DIR, relativePath);
        try {
            if (Files.exists(filePath)) {
                Files.delete(filePath);
                log.info("删除本地文件成功: {}", filePath);
            }
        } catch (IOException e) {
            log.error("删除本地文件失败: {}, error={}", filePath, e.getMessage(), e);
        }
    }

    @Override
    public String getStorageType() {
        return "local";
    }

    /**
     * 校验上传文件
     */
    private void validateFile(MultipartFile file) {
        if (file == null || file.isEmpty()) {
            throw BusinessException.validationError("请选择要上传的文件");
        }

        String extension = getFileExtension(file.getOriginalFilename()).toLowerCase();

        // 校验扩展名
        boolean validExtension = false;
        for (String ext : ALLOWED_EXTENSIONS) {
            if (ext.equals(extension)) {
                validExtension = true;
                break;
            }
        }
        if (!validExtension) {
            throw BusinessException.validationError(
                    "不支持的文件类型，仅支持 JPG、JPEG、PNG、GIF、WebP、PDF、XLSX、DOCX 格式");
        }

        // 根据类型校验大小
        boolean isImage = isImageExtension(extension);
        long maxSize = isImage ? MAX_IMAGE_SIZE : MAX_DOC_SIZE;
        String sizeLabel = isImage ? "5MB" : "20MB";

        if (file.getSize() > maxSize) {
            throw BusinessException.validationError("文件大小不能超过 " + sizeLabel);
        }
    }

    private boolean isImageExtension(String extension) {
        for (String ext : IMAGE_EXTENSIONS) {
            if (ext.equals(extension)) return true;
        }
        return false;
    }

    private String getFileExtension(String filename) {
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
