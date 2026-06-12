package com.migao.admin.controller;

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.UploadedFileInfo;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.service.FileStorageService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 文件上传控制器
 * 提供文件上传、删除接口
 * 自动使用 OSS 或本地存储（通过 FileStorageService 接口注入）
 */
@Slf4j
@RestController
@RequiredArgsConstructor
public class UploadController {

    private final FileStorageService fileStorageService;

    /**
     * 单文件上传
     *
     * POST /api/admin/files/upload
     */
    @PostMapping("/api/admin/files/upload")
    public ApiResponse<UploadedFileInfo> uploadFile(
            @RequestParam("file") MultipartFile file,
            @RequestParam(value = "directory", defaultValue = "images") String directory) {
        log.info("上传文件: name={}, size={}, directory={}, storage={}",
                file.getOriginalFilename(), file.getSize(), directory, fileStorageService.getStorageType());
        UploadedFileInfo info = fileStorageService.upload(file, directory);
        return ApiResponse.success(info);
    }

    /**
     * 批量文件上传（最多10个）
     *
     * POST /api/admin/files/upload-batch
     */
    @PostMapping("/api/admin/files/upload-batch")
    public ApiResponse<List<UploadedFileInfo>> uploadFiles(
            @RequestParam("files") List<MultipartFile> files,
            @RequestParam(value = "directory", defaultValue = "images") String directory) {
        if (files.size() > 10) {
            throw BusinessException.validationError("批量上传最多支持 10 个文件");
        }
        log.info("批量上传文件: count={}, directory={}, storage={}",
                files.size(), directory, fileStorageService.getStorageType());

        List<UploadedFileInfo> results = new ArrayList<>();
        for (MultipartFile file : files) {
            UploadedFileInfo info = fileStorageService.upload(file, directory);
            results.add(info);
        }
        return ApiResponse.success(results);
    }

    /**
     * 删除文件
     *
     * DELETE /api/admin/files/{fileId}
     */
    @DeleteMapping("/api/admin/files/{fileId}")
    public ApiResponse<Void> deleteFile(
            @PathVariable String fileId,
            @RequestBody(required = false) Map<String, String> body) {
        String url = body != null ? body.get("url") : null;
        log.info("删除文件: fileId={}, url={}", fileId, url);
        if (url != null) {
            fileStorageService.delete(url);
        }
        return ApiResponse.success();
    }

    // ========== 兼容旧接口 ==========

    /**
     * 上传单张图片（兼容旧接口）
     *
     * POST /api/admin/upload/image
     */
    @PostMapping("/api/admin/upload/image")
    public ApiResponse<Map<String, String>> uploadImage(
            @RequestParam("file") MultipartFile file,
            @RequestParam(value = "directory", defaultValue = "images") String directory) {
        log.info("上传图片(兼容): name={}, size={}, directory={}",
                file.getOriginalFilename(), file.getSize(), directory);
        UploadedFileInfo info = fileStorageService.upload(file, directory);
        return ApiResponse.success(Map.of("url", info.getUrl()));
    }

    /**
     * 批量上传图片（兼容旧接口）
     *
     * POST /api/admin/upload/images
     */
    @PostMapping("/api/admin/upload/images")
    public ApiResponse<Map<String, List<String>>> uploadImages(
            @RequestParam("files") List<MultipartFile> files,
            @RequestParam(value = "directory", defaultValue = "images") String directory) {
        log.info("批量上传图片(兼容): count={}, directory={}", files.size(), directory);
        List<String> urls = new ArrayList<>();
        for (MultipartFile file : files) {
            UploadedFileInfo info = fileStorageService.upload(file, directory);
            urls.add(info.getUrl());
        }
        return ApiResponse.success(Map.of("urls", urls));
    }

    /**
     * 删除图片（兼容旧接口）
     *
     * DELETE /api/admin/upload/image
     */
    @DeleteMapping("/api/admin/upload/image")
    public ApiResponse<Void> deleteImage(@RequestBody Map<String, String> body) {
        String url = body.get("url");
        log.info("删除图片(兼容): url={}", url);
        fileStorageService.delete(url);
        return ApiResponse.success();
    }
}
