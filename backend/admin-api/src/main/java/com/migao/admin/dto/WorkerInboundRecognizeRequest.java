package com.migao.admin.dto;

import lombok.Data;

import java.util.List;

/**
 * 工人入库识别请求（issue #5052 P1，设计真值源 {@code docs/design/inbound-photo-and-label.md} §5.2 / §6）。
 *
 * <p>🔴 <b>字段面就是全部能力面</b>（设计 §5.3 硬约束 1「只表达入库语义」）：本类**只有两个字段** ——
 * {@code images} 与 {@code barcode}。结构上**不存在** {@code adjustment} / {@code delta} /
 * {@code setStock} / {@code reason} / {@code operator} / {@code targetType} 之类的键
 * ⇒ 「传任意调整」「把库存改成 N」不是被校验拒绝，而是**根本无从表达**
 * （判据 = DTO 声明字段集，见 {@code WorkerInboundSurfaceGuardTest}）。</p>
 *
 * <p><b>为什么没有 {@code targetType}</b>（设计 §5.1 / §11.2 N4）：识别 target 由**服务端**固定为
 * {@code inbound}（{@code app/vision/targets.py} 的 {@code TARGET_FIELDS}），
 * 客户端**不参与选择** —— 复用 {@code ImageRecognitionController} 的 {@code TARGET_PERMISSIONS}
 * 机制会让「权限码按 target 取」的商家写码语义渗进工人路径，那正是 #4727 要防的形态。</p>
 */
@Data
public class WorkerInboundRecognizeRequest {

    /**
     * 照片 URL（1~3 张）。上传通道由页面侧承担（本包不新增上传端点），
     * 服务端只做「张数下限/上限」这一条准入（设计 §6.1 / §11.1 第 7 条）。
     */
    private List<String> images;

    /**
     * **前端解码**得到的条码/二维码原文（可空）—— 设计 §6.1 的「第一优先：前端解码，0 次 LLM 调用」。
     *
     * <p>🔴 只要它非空，服务端就**不再触发 vision**（成本守卫，§11.1 第 7 条「照片含可解条码时
     * 不调用 LLM」）。顺序由**服务端**掌握（§6.2）：设备只负责报告「解码成没成功」，
     * 不许自己决定要不要走模型。解不出的设备侧形态是**不传这个键**（而不是传空串或假串）。</p>
     */
    private String barcode;
}
