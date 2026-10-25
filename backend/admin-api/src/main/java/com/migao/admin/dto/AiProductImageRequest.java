package com.migao.admin.dto;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.Data;

/**
 * 商品图生成请求（issue #7335 · 建品页「AI 生成商品图」）。
 *
 * <p>只描述「用哪张样图、生成什么用途」；**不需要商品 ID** —— 建品页此时商品可能尚未保存，
 * 生成结果只回预览 URL，不落库。</p>
 */
@Data
public class AiProductImageRequest {

    /** 样图 URL（商家刚上传到 OSS 的那张；必须是 https）。 */
    @NotBlank(message = "请先上传一张样图")
    @Size(max = 512, message = "样图地址过长")
    private String imageUrl;

    /** 商品名（提示词里用；可空 ⇒ 使用通用措辞）。 */
    @Size(max = 60, message = "商品名不能超过 60 字")
    private String productName;

    /** 用途：main 主图 / white 白底图 / texture 材质 / craft 工艺 / scene 场景。 */
    @NotBlank(message = "请选择生成用途")
    private String kind;

    /**
     * 主图构图变体（issue #7782）：0 正面棚拍 / 1 半垂坠 / 2 悬挂近景。
     *
     * <p>同一用途连点「再生成一张」时由前端递增，避免两次出同一张图（用户 2026-10-25
     * 「主图图片生成的都一样」）。其它用途忽略此值；缺省 = 0（老客户端不受影响）。</p>
     */
    @Min(value = 0, message = "主图变体序号不合法")
    @Max(value = 2, message = "主图变体序号不合法")
    private Integer variant;
}
