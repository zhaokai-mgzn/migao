package com.migao.admin.service;

import com.migao.admin.dto.UploadedFileInfo;
import org.springframework.web.multipart.MultipartFile;

/**
 * 文件存储服务接口
 * 提供统一的文件上传、删除抽象
 */
public interface FileStorageService {

    /**
     * 上传文件入口（**模板方法**：准入校验在接口这一层做，实现只负责「怎么存」）。
     *
     * <p>护栏**就在接口的默认实现里**（issue #6208 的类级固化）：本地存储与 OSS 存储
     * 自动共用 {@link UploadGuard} 这一份判据，**新增实现不可能忘记接**——
     * 「实现 ×2 各写一份校验」正是本单的根因（本地有 {@code safeResolve}、OSS 零校验）。</p>
     *
     * <p>校验一律发生在**任何副作用之前**（超限 / 非图片 / 越界目录 ⇒ 4xx 且不落盘、不落 OSS）。</p>
     *
     * @param file      上传的文件（按**字节流**判类型与大小，不信客户端 Content-Type / 扩展名）
     * @param directory 存储目录（如 products, categories）；用户可控，越界即 422
     * @return 上传结果
     */
    default UploadedFileInfo upload(MultipartFile file, String directory) {
        return doUpload(file, UploadGuard.validate(file, directory));
    }

    /**
     * 落库动作（只对**已通过 {@link #upload} 准入校验**的输入负责）。
     *
     * @param file                已校验的文件
     * @param normalizedDirectory 已规范化的目录（{@code a//b} ⇒ {@code a/b}，绝不含 {@code ..}）
     * @return 上传结果
     */
    UploadedFileInfo doUpload(MultipartFile file, String normalizedDirectory);

    /**
     * 删除文件
     *
     * @param fileUrl 文件 URL
     */
    void delete(String fileUrl);

    /**
     * 获取存储类型标识
     *
     * @return 存储类型名称（如 "oss" 或 "local"）
     */
    String getStorageType();
}
