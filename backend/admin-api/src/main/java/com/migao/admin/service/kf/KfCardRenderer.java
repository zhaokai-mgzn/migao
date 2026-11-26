package com.migao.admin.service.kf;

import org.springframework.stereotype.Component;

import java.util.Map;

/**
 * 卡片降级（issue #9187）：微信客服不支持米宝的交互卡片 ⇒ 统一转成文本 + 链接。
 *
 * <p>规则：商品/报价/订单/物流/生产进度/知识 → 标题 + 关键字段 + URL；支付 → 扫码提示；
 * 确认/选择/快捷按钮 → 文本选项；表单 → 请直接回复。</p>
 */
@Component
public class KfCardRenderer {

    public String render(String cardType, Map<String, Object> data) {
        if (data == null) {
            data = Map.of();
        }
        String type = cardType == null ? "" : cardType;
        return switch (type) {
            case "product", "quotation", "order", "logistics", "production", "knowledge" ->
                    withLink(text(data.get("title")), text(data.get("summary")), text(data.get("url")));
            case "payment" -> "请扫码支付：" + text(data.get("url"));
            case "confirm", "choice", "quick_actions" -> options(data.get("options"));
            case "form" -> "请直接回复文字，我来帮你处理。";
            default -> withLink(text(data.get("title")), text(data.get("summary")), text(data.get("url")));
        };
    }

    private static String options(Object raw) {
        if (raw instanceof Iterable<?> it) {
            StringBuilder sb = new StringBuilder("请回复数字：\n");
            int i = 1;
            for (Object o : it) {
                sb.append(i++).append(". ").append(text(o)).append('\n');
            }
            return sb.toString().trim();
        }
        return "请直接回复文字。";
    }

    private static String withLink(String title, String summary, String url) {
        StringBuilder sb = new StringBuilder();
        if (!title.isBlank()) {
            sb.append(title);
        }
        if (!summary.isBlank()) {
            if (!sb.isEmpty()) {
                sb.append('\n');
            }
            sb.append(summary);
        }
        if (!url.isBlank()) {
            if (!sb.isEmpty()) {
                sb.append('\n');
            }
            sb.append(url);
        }
        return sb.toString();
    }

    private static String text(Object v) {
        return v == null ? "" : String.valueOf(v);
    }
}
