package com.migao.admin.dto;

import lombok.Data;

import java.util.List;

/**
 * 工人端**拍照识别批次号**请求（issue #8210；用户 2026-10-31 逐字「通过拍照来识别批次号」）。
 *
 * <p>形态 = 工人在库存修正页拍 1~3 张带批次号的标签 / 布卷照，服务端把图转给 ai-agent 的
 * vision（target {@code batch}），回来的字段表**原样**下发。识别只产出「定位是哪一批」的
 * 批次号；<b>实盘米数与提交永远是人的动作</b>（与识别内核的「不落库 / 不提交」同一条纪律）。</p>
 *
 * <h3>为什么字段只有 {@code images}</h3>
 * <ul>
 *   <li><b>字段集 = 能力集</b>：没有 {@code batchId} / {@code actualMeters} / {@code reason} /
 *       {@code workerId} / {@code tenantId} —— 识别不是一次修正，结构上不存在「借识别顺手改账」的入口；</li>
 *   <li>图必须**先上传**（{@code POST /api/worker/inbound/upload}，与拍照入库 / 拍照发货同一条上传腿）⇒
 *       这里收的是 URL 列表，不收二进制（不另立第二条上传约定）；</li>
 *   <li>键形 = <b>camelCase</b>？不 —— 本字段名 {@code images} 在两条口径下同形，故不涉及；
 *       工人端<b>写面</b>的其余请求体仍是 camelCase（{@code WorkerBatchCorrectionRequest}）。</li>
 * </ul>
 */
@Data
public class WorkerBatchRecognizeRequest {

    /**
     * 已上传的照片 URL（1~{@code WorkerInboundService.MAX_IMAGES} 张）。
     *
     * <p>空 / 超上限 ⇒ <b>400</b>，且<b>不发起远端调用</b>（不拿空列表去烧一次 vision）。</p>
     */
    private List<String> images;
}
