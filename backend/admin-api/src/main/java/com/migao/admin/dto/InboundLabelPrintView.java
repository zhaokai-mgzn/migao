package com.migao.admin.dto;

/**
 * 打印回执（issue #5052 P2；设计 §5.2 / §7.3）—— 设备侧打印**前**必调
 * {@code POST /api/worker/inbound/labels/{短码}/print} 的返回。
 *
 * <p>为什么要把 {@code printCount} 回给设备：它是「第几次」的**服务端读数** ——
 * 设备侧拿它才能在纸面/日志上标注重打（而不是各自本地数一份，两份数必然漂移）。</p>
 *
 * <p>⚠️ 本回执**不是**打印授权令牌：设计 §7.3 的「设备侧打印前必须先调本端点」是**纪律型**约束
 * （壳 / 前端不得本地直打绕过），服务端的可观测判据是「每次打印都有 {@code print_count} +1
 * 与一行 {@code audit_logs}」；设备侧那一半的判据在 P4（打印适配层）的包里。</p>
 */
public record InboundLabelPrintView(String shortCode, Integer printCount) {
}
