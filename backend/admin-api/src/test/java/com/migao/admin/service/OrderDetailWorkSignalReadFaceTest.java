// case_ids: UI-115
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 「发货前要不要作业」这个判据**真的从读面交到了前端**的结构判据（issue #7079 第 5 包）。
 *
 * <h2>为什么要它（行为判据盖不到的那一半）</h2>
 * <p>判据本体（{@code OrderShipGuard.requiredOrderKind}）已由 {@link OrderShipGuardTest} 逐值判住；
 * 而本单的病根**不在判据**，在**接线**：读面只有「含加工项」这单侧信号 ⇒ 前端拿不到
 * 「卖布单也要作业」这件事 ⇒ 订单详情没有生成出口、发货页守卫完全不拦。
 * ⇒ 「判据对不对」与「它有没有被读面交出去」是**两个**判据，缺一个都会让同一类缺陷复活
 * （§28.2：结构判据绿 ≠ 接线在，行为判据绿 ≠ 读面在用它）。</p>
 *
 * <h2>三条会红的形态（每条都实测注入过，见 PR body 的红证表）</h2>
 * <ol>
 *   <li>{@code convertToDetailResponse} 里**不调** {@code OrderShipGuard.requiredOrderKind}
 *       （或调了但结果不落到响应上）⇒ 判据 1 红；</li>
 *   <li>响应漏设 {@code needs_work} / {@code work_order_kind} 任一键 ⇒ 判据 1 红；</li>
 *   <li>DTO 上的 {@code @JsonProperty} 被摘掉（键名静默退回 camelCase `needsWork`）⇒ 判据 2 红
 *       （消费方按冻结键取值会静默退化 —— 与 #6890 的类级元守卫同族，本判据是它在**本键**上的实例面）。</li>
 * </ol>
 *
 * <p>⚠️ 本判据读**源码文本**（剥注释），不做 AST —— 本仓既有形态（{@code OrderPaidAndReceivedAtWriteGuardTest}
 * 同款）。代价：它只证明「这几行在方法体里」；<b>真值面</b>（这一型的判定值）由
 * {@link OrderShipGuardTest} 的 {@code requiredOrderKind*} 逐值承担，两面临界互补。</p>
 */
@DisplayName("#7079 读面接线：订单详情必须把 needs_work / work_order_kind 从 OrderShipGuard 交出去")
class OrderDetailWorkSignalReadFaceTest {

    private static final Path MAIN = Path.of("src", "main", "java", "com", "migao", "admin");
    /** 读面本体在 issue #8191（P2-1a）随 {@code convertToDetailResponse} 搬到 OrderQueryService：
     * 扫描对象跟着方法搬家（断言、判别力自证一字未改）—— 搬回去/改名 ⇒ 依然判红（methodBody 取不到即红）。 */
    private static final Path ORDER_SERVICE = MAIN.resolve("service/OrderQueryService.java");
    private static final Path ORDER_DETAIL_RESPONSE = MAIN.resolve("dto/OrderDetailResponse.java");

    private static String source(Path path) throws IOException {
        assertThat(path).as("判据的扫描面必须真实存在（路径漂移 ⇒ 判红，不是空跑通过）").exists();
        return Files.readString(path, StandardCharsets.UTF_8);
    }

    /**
     * 剥掉块注释与行注释：注释里提一句字段名不算证据（本仓「判据被自己的文案喂绿」同族）。
     * 字符串字面量**不剥** —— 本判据要看的就是 {@code @JsonProperty("needs_work")} 里的字面量。
     */
    static String stripComments(String src) {
        StringBuilder out = new StringBuilder(src.length());
        boolean inBlock = false;
        boolean inLine = false;
        for (int i = 0; i < src.length(); i++) {
            char c = src.charAt(i);
            char n = i + 1 < src.length() ? src.charAt(i + 1) : '\0';
            if (inLine) {
                if (c == '\n') {
                    inLine = false;
                    out.append(c);
                }
                continue;
            }
            if (inBlock) {
                if (c == '*' && n == '/') {
                    inBlock = false;
                    i++;
                }
                continue;
            }
            if (c == '/' && n == '*') {
                inBlock = true;
                i++;
                continue;
            }
            if (c == '/' && n == '/') {
                inLine = true;
                i++;
                continue;
            }
            out.append(c);
        }
        return out.toString();
    }

    /** {@code convertToDetailResponse} 的方法体（大括号配平取到闭合那一行；取不到 ⇒ 返回空串 ⇒ 判红）。 */
    static String methodBody(String src, String signature) {
        int at = src.indexOf(signature);
        if (at < 0) {
            return "";
        }
        int open = src.indexOf('{', at);
        if (open < 0) {
            return "";
        }
        int depth = 0;
        for (int i = open; i < src.length(); i++) {
            char c = src.charAt(i);
            if (c == '{') {
                depth++;
            } else if (c == '}') {
                depth--;
                if (depth == 0) {
                    return src.substring(open, i + 1);
                }
            }
        }
        return "";
    }

    /**
     * 判据本体（纯谓词，入参即事实 ⇒ 可在内存里做注入式红证）。
     *
     * @return 违规清单（空 = 通过）
     */
    static List<String> readFaceWiringViolations(String orderServiceSrc, String dtoSrc) {
        List<String> out = new ArrayList<>();
        String service = stripComments(orderServiceSrc);
        String dto = stripComments(dtoSrc);

        String body = methodBody(service, "OrderDetailResponse convertToDetailResponse(");
        if (body.isEmpty()) {
            out.add("OrderService.convertToDetailResponse 的方法体取不到（改名 / 删掉 ⇒ 读面接线失去依据）");
            return out;
        }
        if (!body.contains("OrderShipGuard.requiredOrderKind(")) {
            out.add("convertToDetailResponse 没有调用 OrderShipGuard.requiredOrderKind —— "
                    + "读面只剩「含加工项」单侧信号 ⇒ 卖布单在订单详情没有生成出口、发货页守卫不拦（本单病根）");
        }
        if (!body.contains("setNeedsWork(")) {
            out.add("convertToDetailResponse 没有 setNeedsWork( ⇒ needs_work 恒不下发");
        }
        if (!body.contains("setWorkOrderKind(")) {
            out.add("convertToDetailResponse 没有 setWorkOrderKind( ⇒ work_order_kind 恒不下发"
                    + "（前端拿不到「该生成哪一型」）");
        }

        for (String key : new String[]{"needs_work", "work_order_kind"}) {
            if (!dto.contains("@JsonProperty(\"" + key + "\")")) {
                out.add("OrderDetailResponse 上没有显式 @JsonProperty(\"" + key + "\") ⇒ "
                        + "全局无 SNAKE_CASE 策略，键名静默退回 camelCase，消费方按冻结键取值会静默退化");
            }
        }
        return out;
    }

    @Test
    @DisplayName("🔴 真实源码：读面把 needs_work / work_order_kind 都交出去了（会话前先过这一关）")
    void realSourcesWired() throws IOException {
        assertThat(readFaceWiringViolations(source(ORDER_SERVICE), source(ORDER_DETAIL_RESPONSE))).isEmpty();
    }

    @Test
    @DisplayName("🔴 判别力自证：三种坏形态各自判红（否则上面那条可能是恒真的空判据）")
    void predicateHasDiscriminatingPower() throws IOException {
        String service = source(ORDER_SERVICE);
        String dto = source(ORDER_DETAIL_RESPONSE);

        // ① 判据本体不接线（回到本单修前的形态：读面自己按 processingItems 数）
        assertThat(readFaceWiringViolations(
                service.replace("OrderShipGuard.requiredOrderKind(", "OrderShipGuard.hasProcessingItems("), dto))
                .isNotEmpty();

        // ② 结果不落到响应上
        assertThat(readFaceWiringViolations(service.replace("response.setNeedsWork(", "// response.setNeedsWork("), dto))
                .isNotEmpty();
        assertThat(readFaceWiringViolations(
                service.replace("response.setWorkOrderKind(", "// response.setWorkOrderKind("), dto))
                .isNotEmpty();

        // ③ 键名静默退回 camelCase（摘掉 @JsonProperty）
        assertThat(readFaceWiringViolations(service, dto.replace("@JsonProperty(\"needs_work\")", "")))
                .isNotEmpty();
        assertThat(readFaceWiringViolations(service, dto.replace("@JsonProperty(\"work_order_kind\")", "")))
                .isNotEmpty();

        // ④ 方法被改名 / 消失 ⇒ fail-closed（不许读成「没有违规」）
        assertThat(readFaceWiringViolations(service.replace("private OrderDetailResponse convertToDetailResponse",
                "private OrderDetailResponse convertToDetailResponseRenamed"), dto)).isNotEmpty();

        // 对照：只往注释里加字面量 ⇒ 一条都不红（防止判据被文案喂绿）
        assertThat(readFaceWiringViolations(
                service.replace("public OrderDetailResponse getOrderById(String id) {",
                        "// OrderShipGuard.requiredOrderKind( response.setNeedsWork( response.setWorkOrderKind(\n"
                                + "    public OrderDetailResponse getOrderById(String id) {"),
                dto)).isEmpty();
    }
}
