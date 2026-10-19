package com.migao.admin.controller;

import com.migao.admin.dto.AiProductImageRequest;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.ProductImageGenerationService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 商品图生成控制器（issue #7335 · 建品页 AI 生成入口）。
 *
 * <p>接口：{@code POST /api/admin/products/ai-images} —— 样图 + 用途 → **一张** OSS 永久 URL。
 * 与 {@link ImageRecognitionController} 同族（页面用的 AI 辅助入口、JWT + 端点权限码 +
 * 租户上下文；对内用 Service Token 反调 ai-agent），差别只有：产物是**一张新图**而不是字段表。</p>
 *
 * <p>🔴 <b>不落库</b>：本端点不碰 ProductService / Mapper，「用不用」由商家在页面上点按钮，
 * 提交仍走既有建品/编辑保存链路。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/products/ai-images")
@RequiredArgsConstructor
public class ProductImageController {

    private final ProductImageGenerationService productImageGenerationService;

    /**
     * 生成一张商品图（主图 / 材质 / 工艺 / 场景）。
     *
     * <p>权限码取 {@code product:create}（与建品同一枚写码）：能看见商品列表但无权建品的角色
     * 不该拿到「为货架生成图片」的入口。</p>
     */
    @PostMapping
    @RequirePermission("product:create")
    public ApiResponse<Map<String, String>> generate(@Valid @RequestBody AiProductImageRequest request) {
        log.info("AI 生成商品图: kind={}, product={}", request.getKind(), request.getProductName());
        return ApiResponse.success(productImageGenerationService.generate(
                request.getImageUrl(), request.getProductName(), request.getKind()));
    }
}
