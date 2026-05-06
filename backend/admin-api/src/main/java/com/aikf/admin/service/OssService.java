package com.aikf.admin.service;

import com.aikf.admin.config.OssConfig;
import com.aikf.admin.dto.UploadedFileInfo;
import com.aikf.admin.exception.BusinessException;
import com.aliyun.oss.OSS;
import com.aliyun.oss.model.ObjectMetadata;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnBean;
import org.springframework.context.annotation.Primary;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.io.InputStream;
import java.net.URL;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.Date;
import java.util.UUID;

/**
 * 阿里云 OSS 文件存储服务实现
 * 当 OSS 配置存在且有效时使用此实现
 */
@Slf4j
@Service
@Primary
@RequiredArgsConstructor
@ConditionalOnBean(OSS.class)
public class OssService implements FileStorageService {

    private final OSS ossClient;
    private final OssConfig ossConfig;

    /**
     * 允许上传的图片类型
     */
    private static final String[] ALLOWED_IMAGE_TYPES = {
            "image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp"
    };

    /**
     * 允许上传的文档类型
     */
    private static final String[] ALLOWED_DOC_TYPES = {
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    };

    /**
     * 允许的文件扩展名
     */
    private static final String[] ALLOWED_EXTENSIONS = {
            ".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf", ".xlsx", ".docx"
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
        String objectKey = generateObjectKey(directory, file.getOriginalFilename());

        try (InputStream inputStream = file.getInputStream()) {
            ObjectMetadata metadata = new ObjectMetadata();
            metadata.setContentType(file.getContentType());
            metadata.setContentLength(file.getSize());

            ossClient.putObject(ossConfig.getBucketName(), objectKey, inputStream, metadata);

            String url = buildAccessUrl(objectKey);
            log.info("上传文件成功: objectKey={}, url={}", objectKey, url);

            return UploadedFileInfo.builder()
                    .id(fileId)
                    .url(url)
                    .name(file.getOriginalFilename())
                    .size(file.getSize())
                    .type(file.getContentType())
                    .createdAt(LocalDateTime.now())
                    .build();

        } catch (IOException e) {
            log.error("上传文件失败: {}", e.getMessage(), e);
            throw new BusinessException("UPLOAD_ERROR", "文件上传失败", 500);
        }
    }

    /**
     * 上传图片到 OSS（兼容旧接口）
     */
    public String uploadImage(MultipartFile file, String directory) {
        UploadedFileInfo info = upload(file, directory);
        return info.getUrl();
    }

    @Override
    public void delete(String fileUrl) {
        deleteImage(fileUrl);
    }

    /**
     * 从 OSS 删除图片
     */
    public void deleteImage(String imageUrl) {
        if (!StringUtils.hasText(imageUrl)) {
            return;
        }

        String objectKey = extractObjectKey(imageUrl);
        if (objectKey == null) {
            log.warn("无法从 URL 中提取 objectKey: {}", imageUrl);
            return;
        }

        try {
            ossClient.deleteObject(ossConfig.getBucketName(), objectKey);
            log.info("删除文件成功: objectKey={}", objectKey);
        } catch (Exception e) {
            log.error("删除文件失败: objectKey={}, error={}", objectKey, e.getMessage(), e);
        }
    }

    /**
     * 生成签名 URL
     */
    public String generatePresignedUrl(String objectKey, int expirationMinutes) {
        Date expiration = new Date(System.currentTimeMillis() + (long) expirationMinutes * 60 * 1000);
        URL url = ossClient.generatePresignedUrl(ossConfig.getBucketName(), objectKey, expiration);
        return url.toString();
    }

    @Override
    public String getStorageType() {
        return "oss";
    }

    /**
     * 校验上传文件
     */
    private void validateFile(MultipartFile file) {
        if (file == null || file.isEmpty()) {
            throw BusinessException.validationError("请选择要上传的文件");
        }

        String contentType = file.getContentType();
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
        boolean isImage = isImageType(contentType);
        long maxSize = isImage ? MAX_IMAGE_SIZE : MAX_DOC_SIZE;
        String sizeLabel = isImage ? "5MB" : "20MB";

        if (file.getSize() > maxSize) {
            throw BusinessException.validationError("文件大小不能超过 " + sizeLabel);
        }
    }

    private boolean isImageType(String contentType) {
        if (contentType == null) return false;
        for (String type : ALLOWED_IMAGE_TYPES) {
            if (type.equals(contentType)) return true;
        }
        return false;
    }

    /**
     * 生成 OSS 对象 Key
     */
    private String generateObjectKey(String directory, String originalFilename) {
        String datePath = LocalDate.now().format(DateTimeFormatter.ofPattern("yyyy/MM/dd"));
        String extension = getFileExtension(originalFilename);
        String uuid = UUID.randomUUID().toString().replace("-", "");
        return String.format("%s/%s/%s%s", directory, datePath, uuid, extension);
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

    private String buildAccessUrl(String objectKey) {
        String urlPrefix = ossConfig.getUrlPrefix();
        if (StringUtils.hasText(urlPrefix)) {
            if (urlPrefix.endsWith("/")) {
                return urlPrefix + objectKey;
            }
            return urlPrefix + "/" + objectKey;
        }
        return String.format("https://%s.%s/%s", ossConfig.getBucketName(), ossConfig.getEndpoint(), objectKey);
    }

    private String extractObjectKey(String imageUrl) {
        String urlPrefix = ossConfig.getUrlPrefix();
        if (StringUtils.hasText(urlPrefix) && imageUrl.startsWith(urlPrefix)) {
            String key = imageUrl.substring(urlPrefix.length());
            if (key.startsWith("/")) {
                key = key.substring(1);
            }
            return key;
        }

        String ossHost = String.format("%s.%s/", ossConfig.getBucketName(), ossConfig.getEndpoint());
        int hostIndex = imageUrl.indexOf(ossHost);
        if (hostIndex >= 0) {
            return imageUrl.substring(hostIndex + ossHost.length());
        }

        return null;
    }
}
