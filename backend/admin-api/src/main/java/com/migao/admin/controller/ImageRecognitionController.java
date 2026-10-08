package com.migao.admin.controller;

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.ImageRecognitionInterpretRequest;
import com.migao.admin.dto.ImageRecognitionRequest;
import com.migao.admin.dto.PageFillPlan;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.security.PermissionInterceptor;
import com.migao.admin.service.ImageRecognitionClient;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * 图片识别控制器（issue #5321 包 1 · 页面快通道；issue #6367 包 P2 追加推理端点）。
 *
 * <p>接口：</p>
 * <ul>
 *   <li>{@code POST /api/admin/image-recognition} —— 图 → 结构化字段（<b>不落库</b>）；</li>
 *   <li>{@code POST /api/admin/image-recognition/interpret} —— 图 + 可选 {@code hint} →
 *       黄金策推理的 {@code page_fill} 计划（<b>同族</b>：同权限、同 service token、同 service，
 *       不新立第二套约定）。</li>
 * </ul>
 *
 * <h3>为什么落在这里（调用路径与理由，与 PR body 同一份）</h3>
 * <ol>
 *   <li><b>对外</b>：{@code 建品页 / 建单页} → {@code POST /api/admin/image-recognition}
 *       （JWT + 端点权限码 + 租户上下文）。形态与 {@link CraftCalcController}
 *       （{@code POST /api/admin/orders/craft-calc}）同类：<b>页面用的 AI 辅助读接口</b>，
 *       不属于任何实体的 CRUD 生命周期。</li>
 *   <li><b>为什么不放 {@code /api/admin/agent/**}</b>：那个命名空间在本仓是
 *       <b>ai-agent-service 的 Tool 调用的那批端点</b>（实证：{@code customer_order_query.py} /
 *       {@code order_create.py} / {@code production_progress_query.py} 等都打
 *       {@code /api/admin/agent/*}）。把页面入口挂进去 = 把纯技术能力标成「必须有 Agent 才能用」，
 *       而设计裁定恰恰是<b>「不要让 Agent 成为这个能力的唯一入口」</b>
 *       （{@code docs/agent-feature-design.md} §四，PR #5320 入库）。{@code /interpret} 同理：
 *       用户裁定「操作入口和呈现方式和黄金策 agent 不一样」⇒ 它<b>不经过</b>对话窗口。</li>
 *   <li><b>对内</b>：本控制器 → {@link ImageRecognitionClient} →
 *       {@code POST /api/internal/vision/recognize} / {@code POST /api/internal/vision/interpret}
 *       （Service Token）。与 {@link CraftCalcController} / 简报 / 知识提炼<b>同一套</b>内部调用约定，
 *       不另立第二套。</li>
 * </ol>
 *
 * <h3>权限：按 target 取写码（不是端点级静态码）</h3>
 * <p>一个入口覆盖两个模块 ⇒ 静态 {@code @RequirePermission} 表达不了「商品用商品写码、
 * 订单用订单写码」。改用 {@link PermissionInterceptor#requirePermission(String)}
 * <b>命令式断言</b>（issue #4148 的既有机制，与 AOP 拦截同一份判定）：
 * 建品页拿 {@code product:create}、建单页拿 {@code order:create} ——
 * 只见得到商品列表的角色不会因为点了建单页的按钮而绕过订单写权限。
 * <b>未知 target 一律 400</b>（fail-closed：没有权限码可用就不放行）。两个端点共用同一个私有判定
 * （{@link #requireTargetPermission(String)}），故新端点<b>不可能</b>悄悄放宽权限。</p>
 *
 * <p>🔴 <b>不落库 / 不提交</b>：本控制器只回「填哪几格」，<b>提交永远是人的动作</b>。
 * 机械判据见 {@code ImageRecognitionControllerTest}（依赖面反射 + 返回体恰好三个键）。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/image-recognition")
@RequiredArgsConstructor
public class ImageRecognitionController {

    private static final String ERR_INVALID_TARGET = "IMAGE_RECOGNITION_INVALID_TARGET";
    private static final String ERR_INVALID_IMAGES = "IMAGE_RECOGNITION_INVALID_IMAGES";
    private static final String ERR_INVALID_HINT = "IMAGE_RECOGNITION_INVALID_HINT";

    /** {@code hint} 上限（字）：一句补充够用；再长就不是「提示」而是「下单指令」，且只会白烧 token。 */
    private static final int HINT_MAX_CHARS = 200;

    /**
     * target → 所需权限码。
     *
     * <p>取值即目录里的**写码**（{@code ProductController} / {@code OrderController} 建对象用的那两个）——
     * 识别是为了**建**，不是**看**；用读码会让「只看列表」的角色顺带拿到建对象的入口
     * （与 issue #5246「读写拆码」同一条判据）。</p>
     */
    private static final Map<String, String> TARGET_PERMISSIONS = Map.of(
            "product", "product:create",
            "order", "order:create");

    private final ImageRecognitionClient imageRecognitionClient;
    private final PermissionInterceptor permissionInterceptor;

    /**
     * 识别图片 → 结构化字段（**不落库**）。
     *
     * <p>入参 {@code {targetType, images}}：{@code targetType} 必须是
     * {@code product} / {@code order} 之一，未知值 <b>400 且不发起远端调用</b>
     * （fail-closed，不猜 target —— 猜错就是「拿商品字段表去填订单」）。</p>
     */
    @PostMapping
    public ApiResponse<ImageRecognitionClient.ImageRecognitionResult> recognize(
            @RequestBody(required = false) ImageRecognitionRequest request) {
        String targetType = request == null ? null : request.getTargetType();
        // 权限按 target 决定（命令式断言，复用 PermissionInterceptor 的同一份判定）
        requireTargetPermission(targetType);

        List<String> images = request.getImages();
        requireNonEmptyImages(images);
        Long tenantId = com.migao.admin.config.TenantContext.getTenantId();
        log.info("[图片识别] target={}, images={}, tenantId={}", targetType, images.size(), tenantId);

        return ApiResponse.success(imageRecognitionClient.recognize(targetType, images));
    }

    /**
     * 识别 + 黄金策推理 → 同页填充计划（**不落库**；issue #6367 包 P2）。
     *
     * <p>与 {@link #recognize} <b>同族</b>：同一类级前缀、同一个 {@code @PostMapping} 形态、
     * 同一份「按 target 取写码」权限判定、同一套 client / service token；只多一个**可选** {@code hint}
     * （商家已经知道的那点信息，如「客厅雪尼尔，韩褶，遮光」）。</p>
     *
     * <p>校验顺序与 {@code recognize} 逐字同序（target → images），{@code hint} 放最后：
     * 前两条的报错读数与既有端点<b>一字不差</b>（前端两个入口共用一份错误处理）。</p>
     */
    @PostMapping("/interpret")
    public ApiResponse<PageFillPlan> interpret(
            @RequestBody(required = false) ImageRecognitionInterpretRequest request) {
        String targetType = request == null ? null : request.getTargetType();
        requireTargetPermission(targetType);

        List<String> images = request.getImages();
        requireNonEmptyImages(images);

        String hint = request.getHint();
        if (hint != null && hint.length() > HINT_MAX_CHARS) {
            throw new BusinessException(ERR_INVALID_HINT,
                    "补充提示太长：" + hint.length() + " 字，上限 " + HINT_MAX_CHARS + " 字",
                    400,
                    "请把 hint 压到 " + HINT_MAX_CHARS + " 字以内（例如「客厅雪尼尔，韩褶，遮光」）—— "
                            + "它是给推理的一句话上下文，不是订单内容；写长了不会更准，只会白烧一次调用。");
        }

        Long tenantId = com.migao.admin.config.TenantContext.getTenantId();
        log.info("[图片识别·推理] target={}, images={}, hint={}字, tenantId={}",
                targetType, images.size(), hint == null ? 0 : hint.length(), tenantId);

        ImageRecognitionClient.PageFillResult result =
                imageRecognitionClient.interpret(targetType, images, hint);
        return ApiResponse.success(new PageFillPlan(result.component(), result.targetType(), result.fields()));
    }

    /**
     * target → 权限码的**唯一一处**判定（两个端点共用）。
     *
     * <p>抽出来不是为了省几行，而是让「新端点会不会悄悄放宽权限」在结构上不可能：
     * 只要有人给 {@code /interpret} 单开一条判定，{@code ImageRecognitionInterpretControllerTest}
     * 的注解一致性判据与权限判据会当场变红。</p>
     */
    private void requireTargetPermission(String targetType) {
        String permission = targetType == null ? null : TARGET_PERMISSIONS.get(targetType);
        if (permission == null) {
            throw new BusinessException(ERR_INVALID_TARGET,
                    "不支持的识别 target：" + targetType + "（只认 product / order）",
                    400,
                    "请把 targetType 传成 \"product\"（建品页：色卡/布料实拍/供应商图）"
                            + "或 \"order\"（建单页：手写单/微信聊天截图/旧系统单据）；"
                            + "两个 target 的字段 schema 与消歧规则不同，系统不替你猜。");
        }
        permissionInterceptor.requirePermission(permission);
    }

    /** 空图片列表 = 白烧一次 vision（推理端点还要多烧一次 LLM）⇒ 远端调用前拦住。 */
    private void requireNonEmptyImages(List<String> images) {
        if (images == null || images.isEmpty()) {
            throw new BusinessException(ERR_INVALID_IMAGES,
                    "缺少图片：images 为空", 400,
                    "请先上传图片（POST /api/admin/upload/image 拿 url），再把 url 列表传给 images。"
                            + "系统不会拿空列表去问模型（那只会浪费一次 vision 调用）。");
        }
    }
}
