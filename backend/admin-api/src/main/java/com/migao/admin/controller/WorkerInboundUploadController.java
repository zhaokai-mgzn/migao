package com.migao.admin.controller;

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.UploadedFileInfo;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.service.FileStorageService;
import com.migao.admin.service.WorkerInboundService;
import com.migao.admin.worker.WorkerSessionService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import javax.imageio.ImageIO;
import javax.imageio.ImageReader;
import javax.imageio.stream.ImageInputStream;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;

/**
 * 工人可达的**照片上传**端点（issue #5052 <b>P2</b>）：{@code POST /api/worker/inbound/upload}。
 *
 * <h3>🔴 它补的是 P1 留下的真缺口（不是可选优化）</h3>
 * <p>P1 的 {@code /api/worker/inbound/recognize} 收的是**已上传好的 URL 列表**，
 * 而现有一切上传端点都挂在 {@code /api/admin/**}
 * （{@code UploadController} 的 {@code /api/admin/files/upload} 等，且带 {@code @RequirePermission}）
 * ⇒ 工人**根本够不着**：路径被 {@code ADMIN_API_REJECTED_ROLES}（含 {@code worker}）拒，
 * 即便放行也因零商家权限码被 {@code requirePermission} 拒。
 * ⇒ 「拍照入库」这条链在 P1 之后仍然**拍不成**（本端点就是那一步）。</p>
 *
 * <h3>零商家权限码（设计 §9.3 红线）</h3>
 * <p>没有 {@code @RequirePermission}、不注入 {@code PermissionInterceptor} ——
 * 准入判据只有「有效工人 session」（无 ⇒ <b>401</b>）。
 * <b>不是「有码就放行」，而是这条路径根本不查商家码</b>（#4727 的落法）。</p>
 *
 * <h3>拒绝口径（设计 §5.2，逐条可红）</h3>
 * <ul>
 *   <li>非图片（MIME 不是 {@code image/*}，或**读不出图像头** —— 只信 MIME 会被改名文本骗过）⇒ <b>400</b>；</li>
 *   <li>张数不是 1~{@value WorkerInboundService#MAX_IMAGES} 张 ⇒ <b>400</b>（上限与 {@code recognize} **同一常量**，不各写一份）；</li>
 *   <li>超尺寸（单张 &gt; 5MB，或任一边长 &gt; 8000px）⇒ <b>400</b>；</li>
 *   <li>存储失败 ⇒ 由存储层抛既有异常（不吞、不改状态码）。</li>
 * </ul>
 *
 * <h3>为什么是独立控制器</h3>
 * <p>① P1 的结构守卫逐字钉住「{@code WorkerInboundController} 只有那三个 POST」；
 * ② 上传是**存储面**（复用 {@link FileStorageService}，不新造存储），与入库单据面判据不同，
 * 分开才能各自被独立守卫。</p>
 *
 * <h3>复用而非新造</h3>
 * <p>落 OSS 还是本地盘由既有的 {@link FileStorageService} 决定（{@code OssService} /
 * {@code LocalFileStorageService}），本控制器**不碰**任何存储 SDK、不新建桶 / 目录约定，
 * 只把「这是工人拍的上游标签照」这个语义固定到 {@link #DIRECTORY}。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/worker/inbound")
@RequiredArgsConstructor
public class WorkerInboundUploadController {

    /** 存储目录（语义化：入库照片单独归置，便于设计 §9.4 的「图片保留期」按目录治理）。 */
    public static final String DIRECTORY = "inbound";

    /** 单张图片上限：5MB（与既有 {@code OssService.MAX_IMAGE_SIZE} 同口径 —— 不新造第二把尺子）。 */
    public static final long MAX_IMAGE_BYTES = 5 * 1024 * 1024;

    /** 单边像素上限（工人手机 1 亿像素也不该把 OSS / 识别链路拖垮）。 */
    public static final int MAX_IMAGE_EDGE_PX = 8000;

    private final FileStorageService fileStorageService;
    private final WorkerSessionService workerSessionService;

    /**
     * 上传 1~3 张照片 ⇒ 回 URL 列表（喂给 {@code POST /api/worker/inbound/recognize} 的 {@code images}）。
     */
    @PostMapping(value = "/upload", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ApiResponse<List<UploadedFileInfo>> upload(
            @RequestParam(value = "files", required = false) List<MultipartFile> files,
            @RequestHeader(value = WorkerSessionService.SESSION_HEADER, required = false) String sessionId) {
        requireWorker(sessionId);
        if (files == null || files.isEmpty()) {
            throw badRequest("INBOUND_UPLOAD_NO_FILE", "请选择要上传的照片",
                    "一次上传 1~" + WorkerInboundService.MAX_IMAGES + " 张上游标签 / 布卷包装照。");
        }
        if (files.size() > WorkerInboundService.MAX_IMAGES) {
            throw badRequest("INBOUND_UPLOAD_TOO_MANY_FILES",
                    "一次最多上传 " + WorkerInboundService.MAX_IMAGES + " 张照片（收到 " + files.size() + " 张）",
                    "请只保留最能看清标签的那几张再上传（上限与识别端点一致）。");
        }
        List<UploadedFileInfo> uploaded = new ArrayList<>();
        for (MultipartFile file : files) {
            validateImage(file);
            uploaded.add(fileStorageService.upload(file, DIRECTORY));
        }
        log.info("[工人入库] 照片已上传: count={}, directory={}, storage={}",
                uploaded.size(), DIRECTORY, fileStorageService.getStorageType());
        return ApiResponse.success(uploaded);
    }

    // ============================================================ 内部

    /** 有效工人 session 或 401（与 P1 同一处判据：工人路径上「谁」没有第二条来源）。 */
    private void requireWorker(String sessionId) {
        if (workerSessionService.resolveIdentity(sessionId) == null) {
            throw BusinessException.authFailed("尚未登录工人身份，请先用工号 + PIN 登录");
        }
    }

    /**
     * 只收**真图片**：MIME 是 {@code image/*} **且**能读出图像头。
     *
     * <p>为什么两道都要：MIME 是客户端给的（改名 / 伪造 Content-Type 零成本），
     * 而「读不出图像头」这件事由 JDK 的 {@code ImageIO} 判 —— 那才是**内容**层面的判据。
     * 少了第二道，一个 {@code photo.txt} 改名 + 伪造 MIME 就能进 OSS。</p>
     */
    private static void validateImage(MultipartFile file) {
        if (file == null || file.isEmpty()) {
            throw badRequest("INBOUND_UPLOAD_EMPTY_FILE", "上传的照片是空的", "请重新拍照后上传。");
        }
        String contentType = file.getContentType();
        if (contentType == null || !contentType.toLowerCase(java.util.Locale.ROOT).startsWith("image/")) {
            throw badRequest("INBOUND_UPLOAD_NOT_IMAGE",
                    "只支持上传图片（收到 " + (contentType == null ? "未知类型" : contentType) + "）",
                    "入库识别只吃照片：请拍上游标签 / 布卷包装，不要上传 PDF、表格等文件。");
        }
        if (file.getSize() > MAX_IMAGE_BYTES) {
            throw badRequest("INBOUND_UPLOAD_TOO_LARGE",
                    "单张照片不能超过 " + (MAX_IMAGE_BYTES / 1024 / 1024) + "MB（收到 "
                            + (file.getSize() / 1024 / 1024) + "MB）",
                    "请用手机相机直接拍（不要传原图 / 长图），或在相册里先压缩。");
        }
        int[] size = readImageSize(file);
        if (size == null) {
            throw badRequest("INBOUND_UPLOAD_NOT_DECODABLE",
                    "这个文件读不出图像内容（不是有效的图片）",
                    "请重新拍照；改扩展名 / 伪造类型都过不了这一步（按内容判，不按文件名判）。");
        }
        if (size[0] > MAX_IMAGE_EDGE_PX || size[1] > MAX_IMAGE_EDGE_PX) {
            throw badRequest("INBOUND_UPLOAD_TOO_LARGE_PIXELS",
                    "照片尺寸过大（" + size[0] + "×" + size[1] + "，单边上限 " + MAX_IMAGE_EDGE_PX + "px）",
                    "请在相机里改用较小的分辨率（识别只看标签上的字，不需要全画幅）。");
        }
    }

    /** 读图像头取尺寸（**不整图解码**：工人手机 1200 万像素整解一次要几十 MB 内存）。 */
    private static int[] readImageSize(MultipartFile file) {
        try (ImageInputStream stream = ImageIO.createImageInputStream(file.getInputStream())) {
            if (stream == null) {
                return null;
            }
            Iterator<ImageReader> readers = ImageIO.getImageReaders(stream);
            if (!readers.hasNext()) {
                return null;
            }
            ImageReader reader = readers.next();
            try {
                reader.setInput(stream);
                return new int[] {reader.getWidth(0), reader.getHeight(0)};
            } finally {
                reader.dispose();
            }
        } catch (IOException | RuntimeException e) {
            log.warn("[工人入库] 照片读取失败，按「不是有效图片」处理: {}", e.getMessage());
            return null;
        }
    }

    /** 400 + 可行动建议（设计 §5.2 逐字：非图片 / 超限一律 400，不是 422）。 */
    private static BusinessException badRequest(String code, String message, String suggestion) {
        return new BusinessException(code, message, 400, suggestion);
    }
}
