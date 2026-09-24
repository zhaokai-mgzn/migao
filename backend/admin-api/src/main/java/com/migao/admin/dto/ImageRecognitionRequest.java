package com.migao.admin.dto;

import lombok.Data;

import java.util.List;

/**
 * 图片识别请求（issue #5321 包 1 · 页面快通道）。
 *
 * <p>建品页 / 建单页的「拍照 / 上传识别」按钮用它发起识别 —— 这是**页面**能力，
 * 与 {@code /api/admin/agent/**}（ai-agent-service 的 Tool 调用的那批端点）不是一回事。</p>
 *
 * <p>{@code targetType} 区分**两个不同的识别 target**：{@code product}（色卡 / 布料实拍 /
 * 供应商图 → 名称/颜色/材质/工艺/门幅/售价）与 {@code order}（手写单 / 微信聊天截图 /
 * 旧系统单据 → 客户名/电话/商品明细/数量/规格）。字段 schema 与消歧规则不同，
 * <b>不是</b>「一套字段两个页面填」。</p>
 */
@Data
public class ImageRecognitionRequest {

    /** 识别 target：{@code product} / {@code order}（未知值一律 400，不猜）。 */
    private String targetType;

    /** 已上传的图片 URL 列表（1~3 张；必须是 {@code https://} 或 {@code /api/files} 开头）。 */
    private List<String> images;
}