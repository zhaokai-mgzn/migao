package com.migao.admin.service;

import com.migao.admin.config.OssConfig;
import com.migao.admin.dto.UploadedFileInfo;
import com.aliyun.oss.OSS;
import com.aliyun.oss.model.CannedAccessControlList;
import com.aliyun.oss.model.ObjectMetadata;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.mock.web.MockMultipartFile;

import java.io.InputStream;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

/**
 * OssService 单元测试
 */
@ExtendWith(MockitoExtension.class)
class OssServiceTest {

    @InjectMocks
    private OssService ossService;

    @Mock
    private OSS ossClient;

    @Mock
    private OssConfig ossConfig;

    private static final String BUCKET_NAME = "ai-customer-service-admin-dev";
    private static final String ENDPOINT = "oss-cn-hangzhou-internal.aliyuncs.com";
    private static final String URL_PREFIX = "https://admin.migaozn.com";

    private static final String PERMANENT_BUCKET = "ai-customer-service-admin-dev";
    private static final String TEMPORARY_BUCKET = "ai-customer-service-chat-dev";

    @BeforeEach
    void setUp() {
        lenient().when(ossConfig.getBucketName()).thenReturn(BUCKET_NAME);
        lenient().when(ossConfig.getEndpoint()).thenReturn(ENDPOINT);
        lenient().when(ossConfig.getUrlPrefix()).thenReturn(URL_PREFIX);
        // 双 Bucket 配置
        lenient().when(ossConfig.getPermanentBucketName()).thenReturn(PERMANENT_BUCKET);
        lenient().when(ossConfig.getTemporaryBucketName()).thenReturn(TEMPORARY_BUCKET);
    }

    @Test
    @DisplayName("上传文件时应设置 object ACL 为 PublicRead，防止链接过期")
    void upload_shouldSetObjectAclToPublicRead() {
        // Given
        MockMultipartFile file = new MockMultipartFile(
                "file",
                "test-image.jpg",
                "image/jpeg",
                "fake image content".getBytes()
        );

        // When
        UploadedFileInfo result = ossService.upload(file, "products");

        // Then
        @SuppressWarnings("unchecked")
        ArgumentCaptor<ObjectMetadata> metadataCaptor = ArgumentCaptor.forClass(ObjectMetadata.class);
        verify(ossClient).putObject(eq(BUCKET_NAME), any(String.class), any(InputStream.class), metadataCaptor.capture());

        ObjectMetadata capturedMetadata = metadataCaptor.getValue();
        Object aclValue = capturedMetadata.getRawMetadata().get("x-oss-object-acl");
        assertThat(aclValue)
                .as("上传的 ObjectMetadata 应设置 ACL 为 PublicRead")
                .isEqualTo(CannedAccessControlList.PublicRead.toString());
    }

    @Test
    @DisplayName("上传文件后应返回包含 URL_PREFIX 的访问 URL")
    void upload_shouldReturnUrlWithPrefix() {
        // Given
        MockMultipartFile file = new MockMultipartFile(
                "file",
                "cover.png",
                "image/png",
                "fake png content".getBytes()
        );

        // When
        UploadedFileInfo result = ossService.upload(file, "products");

        // Then
        assertThat(result.getUrl()).startsWith(URL_PREFIX + "/");
        assertThat(result.getName()).isEqualTo("cover.png");
        assertThat(result.getType()).isEqualTo("image/png");
    }

    @Test
    @DisplayName("上传文件时应正确设置 Content-Type 和 Content-Length")
    void upload_shouldSetContentTypeAndLength() {
        // Given
        byte[] content = "fake image data".getBytes();
        MockMultipartFile file = new MockMultipartFile(
                "file",
                "photo.jpg",
                "image/jpeg",
                content
        );

        // When
        ossService.upload(file, "products");

        // Then
        @SuppressWarnings("unchecked")
        ArgumentCaptor<ObjectMetadata> metadataCaptor = ArgumentCaptor.forClass(ObjectMetadata.class);
        verify(ossClient).putObject(eq(BUCKET_NAME), any(String.class), any(InputStream.class), metadataCaptor.capture());

        ObjectMetadata capturedMetadata = metadataCaptor.getValue();
        assertThat(capturedMetadata.getContentType()).isEqualTo("image/jpeg");
        assertThat(capturedMetadata.getContentLength()).isEqualTo(content.length);
    }

    // ==================== 双 Bucket 路由测试 ====================

    @Test
    @DisplayName("上传到 chat/ 目录时应使用临时 Bucket")
    void upload_toChatDirectory_shouldUseTemporaryBucket() {
        // Given
        MockMultipartFile file = new MockMultipartFile(
                "file",
                "chat-image.jpg",
                "image/jpeg",
                "fake image content".getBytes()
        );

        // When
        ossService.upload(file, "chat/tenant-123");

        // Then
        verify(ossClient).putObject(eq(TEMPORARY_BUCKET), any(String.class), any(InputStream.class), any(ObjectMetadata.class));
    }

    @Test
    @DisplayName("上传到 products/ 目录时应使用永久 Bucket")
    void upload_toProductsDirectory_shouldUsePermanentBucket() {
        // Given
        MockMultipartFile file = new MockMultipartFile(
                "file",
                "product-image.jpg",
                "image/jpeg",
                "fake image content".getBytes()
        );

        // When
        ossService.upload(file, "products/123");

        // Then
        verify(ossClient).putObject(eq(PERMANENT_BUCKET), any(String.class), any(InputStream.class), any(ObjectMetadata.class));
    }

    @Test
    @DisplayName("上传到 avatars/ 目录时应使用永久 Bucket")
    void upload_toAvatarsDirectory_shouldUsePermanentBucket() {
        // Given
        MockMultipartFile file = new MockMultipartFile(
                "file",
                "avatar.png",
                "image/png",
                "fake image content".getBytes()
        );

        // When
        ossService.upload(file, "avatars/user-456");

        // Then
        verify(ossClient).putObject(eq(PERMANENT_BUCKET), any(String.class), any(InputStream.class), any(ObjectMetadata.class));
    }

    @Test
    @DisplayName("selectBucket 方法应正确路由 chat/ 目录到临时 Bucket")
    void selectBucket_chatDirectory_shouldReturnTemporaryBucket() {
        // When
        String bucket = ossService.selectBucket("chat/tenant-123/session-456");

        // Then
        assertThat(bucket).isEqualTo(TEMPORARY_BUCKET);
    }

    @Test
    @DisplayName("selectBucket 方法应正确路由非 chat/ 目录到永久 Bucket")
    void selectBucket_otherDirectories_shouldReturnPermanentBucket() {
        // When & Then
        assertThat(ossService.selectBucket("products/123")).isEqualTo(PERMANENT_BUCKET);
        assertThat(ossService.selectBucket("avatars/456")).isEqualTo(PERMANENT_BUCKET);
        assertThat(ossService.selectBucket("documents/789")).isEqualTo(PERMANENT_BUCKET);
        assertThat(ossService.selectBucket("other")).isEqualTo(PERMANENT_BUCKET);
    }
}
