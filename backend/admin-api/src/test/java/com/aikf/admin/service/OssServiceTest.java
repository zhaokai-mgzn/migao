package com.aikf.admin.service;

import com.aikf.admin.config.OssConfig;
import com.aikf.admin.dto.UploadedFileInfo;
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

    @BeforeEach
    void setUp() {
        lenient().when(ossConfig.getBucketName()).thenReturn(BUCKET_NAME);
        lenient().when(ossConfig.getEndpoint()).thenReturn(ENDPOINT);
        lenient().when(ossConfig.getUrlPrefix()).thenReturn(URL_PREFIX);
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
}
