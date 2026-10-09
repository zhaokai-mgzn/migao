package com.migao.admin.dto;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.databind.DeserializationContext;
import com.fasterxml.jackson.databind.JsonDeserializer;
import org.springframework.boot.jackson.JsonComponent;
import org.springframework.util.StringUtils;

import java.io.IOException;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeFormatterBuilder;

/**
 * 宽松的 {@link OffsetDateTime} 反序列化器（issue #6209）。
 *
 * <h2>为什么需要它</h2>
 * 商品响应一族（{@code ProductResponse} / {@code ProductSkuResponse} / {@code ProductColorResponse}）
 * 用 {@code @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")} 输出**无时区**的展示串，而
 * {@link OffsetDateTime} 的默认反序列化要求 ISO-8601 + 偏移量 ⇒ 「按同一个 DTO 序列化出来的快照
 * 读不回去」。这在幂等回放路径上是**功能性缺陷**：同键重试会被 fail-closed 判成
 * 「结果快照无法解析」（node 现场：同键并发 4 个请求里 3 个拿到 500，业务对象虽然只有 1 条，
 * 但调用方看不到那条 —— 重试的语义是「看到同一条」，不是「被拒」）。
 *
 * <h2>口径（两条都收，显示格式不变）</h2>
 * <ol>
 *   <li><b>展示格式</b>（本仓既有线上形态）：{@code 2026-10-03 13:55:27} —— 缺偏移量 ⇒ 按
 *       {@code ZoneId.systemDefault()}（本机约定 Asia/Shanghai）解释；这也正是 Jackson 用同一
 *       pattern **写出**的形态（写出时偏移量被丢掉了，信息在写侧就已经不在）。</li>
 *   <li><b>ISO-8601 带偏移量</b>：{@code 2026-10-03T13:55:27+08:00} —— 原样解析（将来某处改用
 *       标准序列化时不必再改一遍）。</li>
 * </ol>
 * 空串 / 空白 ⇒ {@code null}（与「该字段没有值」同义，不造 {@code 1970} 假值）。
 *
 * <p>注册方式 = {@link JsonComponent}（Spring Boot 3 的 Jackson 自动装配），不需要改 Spring 配置；
 * 本类只被显式标注的字段消费（{@code @JsonDeserialize(using = …)}），不在全局改任何其他 DTO 的行为。</p>
 */
@JsonComponent
public class LenientOffsetDateTimeDeserializer extends JsonDeserializer<OffsetDateTime> {

    /** 展示格式（本仓商品一族既有的线上形态；缺偏移量 ⇒ 视为系统时区）。 */
    private static final DateTimeFormatter DISPLAY = new DateTimeFormatterBuilder()
            .appendPattern("yyyy-MM-dd HH:mm:ss")
            .optionalStart().appendPattern(".SSS").optionalEnd()
            .toFormatter();

    @Override
    public OffsetDateTime deserialize(JsonParser parser, DeserializationContext context) throws IOException {
        String text = parser.getText();
        if (!StringUtils.hasText(text)) {
            return null;
        }
        String value = text.trim();
        try {
            return OffsetDateTime.parse(value);
        } catch (Exception ignored) {
            // 缺偏移量的展示格式（写出时偏移量已被 pattern 丢掉）
            return LocalDateTime.parse(value, DISPLAY).atZone(ZoneId.systemDefault()).toOffsetDateTime();
        }
    }
}
