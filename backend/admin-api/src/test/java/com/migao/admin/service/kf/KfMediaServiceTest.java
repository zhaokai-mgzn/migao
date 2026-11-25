// case_ids: KF-028
package com.migao.admin.service.kf;

import com.migao.admin.mapper.KfMediaMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 入站媒体归档（issue #9200 / 母单 #9194 子项 4）。
 *
 * <p>口径：**先落文件再落行**，行里记 size/storage_key；`media_id` 是不可信输入
 * （来自回调 JSON）⇒ 必须净化，绝不能拼出 `../` 逃出归档根。</p>
 */
class KfMediaServiceTest {

    @TempDir
    Path tempDir;

    private final WechatKfClient client = mock(WechatKfClient.class);
    private final KfMediaMapper mediaMapper = mock(KfMediaMapper.class);
    private KfMediaService service;

    @BeforeEach
    void setUp() {
        service = new KfMediaService(client, mediaMapper, tempDir.toString());
    }

    @Test
    @DisplayName("下载成功 ⇒ 落文件 + 落行（size/mime/storage_key 一致）")
    void archivesFileAndRow() throws Exception {
        byte[] bytes = new byte[]{1, 2, 3, 4, 5};
        when(client.getMedia("tok", "mid-1"))
                .thenReturn(new WechatKfClient.MediaFile(bytes, "image/png"));
        when(mediaMapper.insertInbound(anyLong(), anyString(), anyString(), anyString(), anyLong(), anyString()))
                .thenReturn(1);

        service.archiveInbound(7L, "wk-1", "mid-1", "tok");

        Path expected = tempDir.resolve("7").resolve("mid-1.png");
        assertThat(Files.exists(expected)).isTrue();
        assertThat(Files.readAllBytes(expected)).isEqualTo(bytes);
        verify(mediaMapper).insertInbound(eq(7L), eq("wk-1"), eq("mid-1"), eq("image/png"),
                eq(5L), eq(expected.toString()));
    }

    @Test
    @DisplayName("下载失败 ⇒ 抛 KfMediaException（由调用方容忍，不阻塞消息落库）")
    void downloadFailureThrowsMediaException() {
        when(client.getMedia(anyString(), anyString()))
                .thenThrow(new KfApiException(40007, "invalid media_id"));

        assertThatThrownBy(() -> service.archiveInbound(7L, "wk-1", "mid-1", "tok"))
                .isInstanceOf(KfMediaException.class)
                .hasMessageContaining("40007");
    }

    @Test
    @DisplayName("media_id 含路径跳转 ⇒ 被净化，文件不逃出归档根")
    void mediaIdIsSanitised() throws Exception {
        byte[] bytes = new byte[]{9};
        when(client.getMedia("tok", "../../etc/passwd"))
                .thenReturn(new WechatKfClient.MediaFile(bytes, "application/octet-stream"));
        when(mediaMapper.insertInbound(anyLong(), anyString(), anyString(), anyString(), anyLong(), anyString()))
                .thenReturn(1);

        service.archiveInbound(7L, "wk-1", "../../etc/passwd", "tok");

        Path tenantDir = tempDir.resolve("7");
        assertThat(Files.list(tenantDir).count()).isEqualTo(1);
        Path written = Files.list(tenantDir).findFirst().orElseThrow();
        assertThat(written.toString()).startsWith(tenantDir.toString());
        assertThat(written.getFileName().toString()).doesNotContain("..").doesNotContain("/");
    }

    @Test
    @DisplayName("归档根不可写 ⇒ 抛 KfMediaException（可归因），不吞掉")
    void unwritableRootThrows() {
        when(client.getMedia(anyString(), anyString()))
                .thenReturn(new WechatKfClient.MediaFile(new byte[]{1}, "image/png"));
        KfMediaService broken = new KfMediaService(client, mediaMapper,
                tempDir.resolve("not-a-dir").toString());
        // 把 "not-a-dir" 建成普通文件 ⇒ 其下的 <tenantId> 目录无法创建
        try {
            Files.writeString(tempDir.resolve("not-a-dir"), "x");
        } catch (Exception e) {
            throw new AssertionError(e);
        }

        assertThatThrownBy(() -> broken.archiveInbound(7L, "wk-1", "mid-1", "tok"))
                .isInstanceOf(KfMediaException.class);
    }
}
