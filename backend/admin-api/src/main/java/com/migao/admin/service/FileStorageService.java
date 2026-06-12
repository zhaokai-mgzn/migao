package com.migao.admin.service;

import com.migao.admin.dto.UploadedFileInfo;
import org.springframework.web.multipart.MultipartFile;

/**
 * 文件存储服务接口
 * 提供统一的文件上传、删除抽象
 */
public interface FileStorageService {

    /**
     * 上传文件
     *
     * @param file      上传的文件
     * @param directory 存储目录（如 products, categories）
     * @return 上传结果
     */
    UploadedFileInfo upload(MultipartFile file, String directory);

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
