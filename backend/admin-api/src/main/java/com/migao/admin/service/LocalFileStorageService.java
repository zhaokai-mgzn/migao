package com.migao.admin.service;

import com.migao.admin.dto.UploadedFileInfo;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.time.BusinessClock;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
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
    /** 业务时钟（issue #3802）：业务「今天」的唯一来源。Spring 注入单例；**不扫描 @Component 的切片上下文**
     * （@WebMvcTest / ApplicationContextRunner）与直接 new 构造的既有单测没有该 bean ⇒ required=false +
     * 默认实例（同为 +08 口径，行为一致），不因引入时钟让任何既有上下文启动失败（实测 OssEmptyConfigContextTest）。 */
    @Autowired(required = false)
    private BusinessClock businessClock = new BusinessClock();

    private static final String UPLOAD_DIR = "uploads";

    /**
     * 本地存储根目录覆盖点（默认 {@value #UPLOAD_DIR}）。
     * 与 {@code WebConfig} 的静态托管前缀同源；单测指到临时目录，让「零副作用」可逐文件枚举取证。
     */
    @Value("${migao.upload.local-dir:" + UPLOAD_DIR + "}")
    private String uploadDir = UPLOAD_DIR;

    /**
     * 静态资源访问路径前缀
     */
    private static final String ACCESS_PATH_PREFIX = "/api/files/static/";

    @Override
    public UploadedFileInfo doUpload(MultipartFile file, String normalizedDirectory) {
        String fileId = UUID.randomUUID().toString().replace("-", "");
        String extension = getFileExtension(file.getOriginalFilename());
        String storedFilename = fileId + extension;

        // 构建存储路径：uploads/{directory}/{filename}
        // 路径穿越护栏已由 FileStorageService#upload 经 UploadGuard 统一把过（issue #6208：
        // 与 OSS 实现**同一份**判据）；本方法只对已校验的输入负责（defense-in-depth 的
        // 越界检查仍在 safeResolve 里，delete 路径同样走它）。
        String directory = StringUtils.hasText(normalizedDirectory) ? normalizedDirectory : "";
        Path uploadPath = safeResolve(directory);

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
                    .createdAt(businessClock.now())
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

        // 安全校验：禁止路径穿越删除 uploads 之外的文件（审计 07 P1-7）
        Path filePath = safeResolve(relativePath);
        try {
            if (Files.exists(filePath)) {
                Files.delete(filePath);
                log.info("删除本地文件成功: {}", filePath);
            }
        } catch (IOException e) {
            log.error("删除本地文件失败: {}, error={}", filePath, e.getMessage(), e);
        }
    }

    /**
     * 解析并校验用户可控的相对路径：规范化后必须位于 uploads 根内。
     * 防路径穿越（../、绝对路径逃逸）导致的任意目录写/删（审计 07 P1-7）。
     *
     * @param relative 用户可控相对路径；null/空 → uploads 根
     * @return 规范化后的绝对路径
     */
    private Path safeResolve(String relative) {
        Path base = Paths.get(uploadDir).toAbsolutePath().normalize();
        Path target = StringUtils.hasText(relative)
                ? base.resolve(relative).normalize()
                : base;
        if (!target.startsWith(base)) {
            throw BusinessException.validationError("非法文件路径");
        }
        return target;
    }

    @Override
    public String getStorageType() {
        return "local";
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
