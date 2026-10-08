package com.migao.admin.dto;

import lombok.Data;

import java.util.List;

/**
 * 图片识别 + 黄金策推理请求（issue #6367 包 P2 · 表单内入口）。
 *
 * <p>与 {@link ImageRecognitionRequest} 同族：{@code targetType} / {@code images} 的取值与校验口径
 * <b>逐字一致</b>（未知 target ⇒ 400；空图 ⇒ 400 且不发起远端调用）；本 DTO 只**多一个可选**
 * {@code hint}（商家已经知道的那点信息，喂给黄金策推理当输入），<b>不改既有 DTO</b>。</p>
 */
@Data
public class ImageRecognitionInterpretRequest {

    /** 识别 target：{@code product} / {@code order}（未知值一律 400，不猜）。 */
    private String targetType;

    /** 已上传的图片 URL 列表（口径同 {@link ImageRecognitionRequest#getImages()}）。 */
    private List<String> images;

    /**
     * 商家的补充提示（**可选**，≤200 字，如「客厅雪尼尔，韩褶，遮光」）。
     *
     * <p>它是**推理的输入**，不是给模型的新指令面：超长 ⇒ 400（见控制器），
     * 空/缺省 ⇒ 请求体里**不出现该键**（不编造空串，口径由
     * {@code ImageRecognitionInterpretTest} 钉住）。</p>
     */
    private String hint;
}
