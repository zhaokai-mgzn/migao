package com.migao.admin.dto;

import lombok.Data;

import java.util.List;
import java.util.Map;

/**
 * 工人入库识别响应（issue #5052 P1，设计 §5.2 / §6）—— <b>只回候选，不落库、不动库存</b>。
 *
 * <p>三条形态约束（都能红，见 {@code WorkerInboundServiceTest}）：</p>
 * <ol>
 *   <li><b>零命中不建品</b>（§6.3）：{@link #skuMatches} 的每一条都是 {@code product_skus} 的实读行，
 *       服务端**不构造** SKU；零命中 ⇒ 空数组 + {@link #requiresManualEntry} = true；</li>
 *   <li><b>不确定 ⇒ 不预填</b>（§6.4 / §11.1 第 8 条）：vision 降级（{@code degraded}）时
 *       {@link #productName} / {@link #colorName} / {@link #quantityMeters} **一律为 null**，
 *       只留 {@link #degraded} = true 与提示语，由工人手输兜底 —— **不编造**；</li>
 *   <li><b>解码优先</b>（§6.1）：{@link #path} = {@code barcode_decode} 时本次请求
 *       **零次 LLM 调用**（成本守卫）。</li>
 * </ol>
 *
 * <p>{@link #fields} 是 ai-agent 识别内核的字段表**原样透传**（{@code {key,label,value,source,reason}}）——
 * Java 侧不重建字段表、不二次消歧（第二份口径必然漂移，见 {@code ImageRecognitionClient} 的既有纪律）。</p>
 */
@Data
public class WorkerInboundRecognizeResponse {

    /** 本次走的识别路径：{@code barcode_decode}（前端解码命中，0 次 LLM）/ {@code vision}（兜底） */
    private String path;

    /** vision 降级（vision 失败 / 一格都没认出来）——**合法结果**，不是错误（同入口既有口径） */
    private boolean degraded;

    /** true ⇒ 候选不可用，请工人**人工录入**（降级 或 零命中既有 SKU）；不是错误，是「不预填」 */
    private boolean requiresManualEntry;

    /** 条码原文（前端解码值 或 vision 抄回的原文；都没有 ⇒ null）。**不解析、不猜含义** */
    private String barcode;

    /** 品名候选（null = 没认出来 / 不在图上；**绝不编造**） */
    private String productName;

    /** 色号候选（null = 同上） */
    private String colorName;

    /** 米数候选（字符串原样搬运，避免精度歧义；null = 同上）。入库数量仍由工人确认后提交 */
    private String quantityMeters;

    /** 命中**既有** {@code product_skus} 的行（零命中 ⇒ 空数组；**不自动建品**） */
    private List<WorkerInboundSkuMatch> skuMatches;

    /** ai-agent 识别内核的字段表原样透传（{@code {key,label,value,source,reason}}） */
    private List<Map<String, Object>> fields;

    /** 给工人看的一句话说明（该手输 / 该选哪一个） */
    private String message;
}
