package com.migao.admin.service;

import com.migao.admin.config.OssConfig;
import com.migao.admin.dto.UploadedFileInfo;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.time.BusinessClock;
import com.aliyun.oss.OSS;
import com.aliyun.oss.model.CannedAccessControlList;
import com.aliyun.oss.model.ObjectMetadata;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.autoconfigure.condition.ConditionalOnExpression;
import lombok.extern.slf4j.Slf4j;
import org.springframework.context.annotation.Primary;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.io.InputStream;
import java.net.URL;
import java.time.format.DateTimeFormatter;
import java.util.Date;
import java.util.UUID;

/**
 * 阿里云 OSS 文件存储服务实现
 * 仅当 **OSS 客户端 bean 存在**（即 ossClient 凭据齐备、未被跳过）时启用，
 * 优先级高于 LocalFileStorageService。
 *
 * 条件注解的选择（issue #3270 实测踩坑，两个都不能用）：
 * - `@ConditionalOnProperty(name = "aliyun.oss.endpoint")`：对**空字符串**恒成立
 *   （application.yml 默认 `endpoint: ${OSS_ENDPOINT:}` 即空串），无凭据时仍注册本类
 *   → 构造器注入 OSS 失败 → **整个应用启动失败**。
 * - `@ConditionalOnBean(OSS.class)`：`@Service` 的 bean 定义在 `@Configuration` 之前注册，
 *   条件求值时 OSS bean 定义尚未出现 → 同样失败。
 *
 * 故用 `@ConditionalOnExpression` 直接判「三项凭据是否都非空白」——纯属性求值，
 * 与 bean 注册顺序无关，且对空串判断正确。
 */
@Slf4j
@Service
@Primary
@RequiredArgsConstructor
@ConditionalOnExpression(OssConfig.REQUIRE_OSS_CREDENTIALS)
public class OssService implements FileStorageService {

    /** 业务时钟（issue #3802）：业务「今天」的唯一来源。Spring 注入单例；**不扫描 @Component 的切片上下文**
     * （@WebMvcTest / ApplicationContextRunner）与直接 new 构造的既有单测没有该 bean ⇒ required=false +
     * 默认实例（同为 +08 口径，行为一致），不因引入时钟让任何既有上下文启动失败（实测 OssEmptyConfigContextTest）。 */
    @Autowired(required = false)
    private BusinessClock businessClock = new BusinessClock();

    private final OSS ossClient;
    private final OssConfig ossConfig;

    /**
     * 上传到 OSS。
     *
     * <p><b>准入校验不在这里</b>：类型（魔数）/ 大小（服务端计数）/ 目录合法性由
     * {@link FileStorageService#upload} 经 {@link UploadGuard} 统一把关（issue #6207 / #6208）——
     * 本类原先只按**扩展名**判类型、按**客户端声明的 Content-Type** 选大小档，
     * 于是「{@code .png} 名 + 声明 pdf + 19.9MB」被 200 落桶公共可读（实测 D2）。</p>
     */
    @Override
    public UploadedFileInfo doUpload(MultipartFile file, String normalizedDirectory) {
        String directory = normalizeDirectory(normalizedDirectory);

        String fileId = UUID.randomUUID().toString().replace("-", "");
        String objectKey = generateObjectKey(directory, file.getOriginalFilename());
        String bucketName = selectBucket(directory);

        try (InputStream inputStream = file.getInputStream()) {
            ObjectMetadata metadata = new ObjectMetadata();
            metadata.setContentType(file.getContentType());
            metadata.setContentLength(file.getSize());
            // 仅永久 Bucket 设置 object 级 PublicRead ACL（临时 Bucket 有 BlockPublicAccess 策略，
            // 拒绝 object 级 public ACL；其公开读权限通过 bucket 级 ACL 保障）
            if (bucketName.equals(ossConfig.getPermanentBucketName())) {
                metadata.setObjectAcl(CannedAccessControlList.PublicRead);
            }

            ossClient.putObject(bucketName, objectKey, inputStream, metadata);

            String url = buildAccessUrl(objectKey);
            log.info("上传文件成功: bucket={}, objectKey={}, url={}", bucketName, objectKey, url);

            return UploadedFileInfo.builder()
                    .id(fileId)
                    .url(url)
                    .name(file.getOriginalFilename())
                    .size(file.getSize())
                    .type(file.getContentType())
                    .createdAt(businessClock.now())
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

    /** 目录回落与 {@code UploadController} 的 {@code defaultValue = "images"} 同口径。 */
    private static String normalizeDirectory(String directory) {
        return StringUtils.hasText(directory) ? directory : "images";
    }

    /**
     * 生成 OSS 对象 Key
     */
    private String generateObjectKey(String directory, String originalFilename) {
        String datePath = businessClock.today().format(DateTimeFormatter.ofPattern("yyyy/MM/dd"));
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

    /**
     * 根据目录选择 Bucket
     * - chat/ 目录使用临时 Bucket（如已配置）
     * - 其他目录使用永久 Bucket
     *
     * 注：临时 Bucket 需先通过控制台或 API 关闭 BlockPublicAccess，
     * 否则回退到永久 Bucket。
     */
    public String selectBucket(String directory) {
        if (directory != null && directory.startsWith("chat/")) {
            String tempBucket = ossConfig.getTemporaryBucketName();
            if (StringUtils.hasText(tempBucket)) {
                return tempBucket;
            }
            // 临时 Bucket 未配置时回退到永久 Bucket
            log.debug("临时 Bucket 未配置，使用永久 Bucket 存储聊天图片");
        }
        return ossConfig.getPermanentBucketName();
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
