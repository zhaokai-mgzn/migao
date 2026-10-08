package com.migao.admin.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;
import java.util.Map;

/**
 * 同页填充计划（issue #6367 包 P2）—— 三端**冻结契约**的出口形状。
 *
 * <p>与 ai-agent 的 {@code app/vision/deep_channel.py::build_page_fill()} <b>同一份形状</b>
 * （不许在 Java 侧重算、不许改键名）：</p>
 *
 * <pre>{@code
 * {"component":"page_fill","target_type":"product",
 *  "fields":[{"key","label","value","source","reason","candidates","note","note_source"}]}
 * }</pre>
 *
 * <p>🔴 <b>键名是 snake_case</b>（{@code target_type} / {@code note_source}）—— 全局 ObjectMapper
 * **没有** SNAKE_CASE 策略（见 {@code ProcessingOrderResponse} 的注释），故这里显式
 * {@code @JsonProperty}；写成 camelCase 会让前端与 ai-agent 两侧对不上。</p>
 *
 * <p>🔴 {@code fields} 的**键恒在**（{@code @JsonInclude(ALWAYS)}）：空数组 = 「一格都没认出来」
 * （合法结果，前端渲染「请手工填写」），缺键 = 「端点没说」（故障）—— 两者必须可区分，
 * 与 {@link com.migao.admin.service.ImageRecognitionClient} 的 fail-closed 判定同一条理由。</p>
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record PageFillPlan(
        /** 组件名，恒 {@code page_fill}（前端按它分流到同页填充分支）。 */
        String component,

        /** 识别 target（{@code product} / {@code order}），与请求回显一致。 */
        @JsonProperty("target_type") String targetType,

        /**
         * 逐格计划，**原样搬运** ai-agent 的字段表：
         * {@code {key, label, value, source, reason, candidates, note, note_source}}。
         *
         * <p>{@code value} 非空 ⇒ {@code source ∈ {"[图片识别]", "[米宝解读]"}}（来源可区分）；
         * {@code value == null} ⇒ 该格**故意留空**、{@code reason} 说明原因；歧义格带 {@code candidates}。</p>
         */
        @JsonInclude(JsonInclude.Include.ALWAYS) List<Map<String, Object>> fields) {
}
