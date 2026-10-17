// case_ids: OR-067
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 「收款时刻 / 完成时刻」两列的**写面结构判据**（issue #7078）—— 把三种「改坏了不会红」的退化形态钉住。
 *
 * <h2>为什么需要它</h2>
 * <ol>
 *   <li><b>{@code paid_at} 被写到回退边上</b>：把 {@code pending → confirmed} 的限定拆掉（或干脆写进
 *       {@code shipped} 分支）⇒ {@code producing → confirmed}（作废加工单退回待发货）会把「支付时间」
 *       **顶成当天**，而屏幕上看不出任何异常 —— 一行之差、静默失真。</li>
 *   <li><b>{@code received_at} 漏了自动完成那条腿</b>：那条腿走
 *       {@code OrderMapper.autoCompleteShippedOrders} 自己的条件 UPDATE，**不经**
 *       {@code transitionStatusAtomic} ⇒ 漏写后「发货后 N 天自动完成」的单**永远**是空值，
 *       而**不会有别的东西变红**（形态同 V148 的「两条发货路」）。</li>
 *   <li><b>详情响应又读不回真值</b>：{@code OrderDetailResponse} 漏掉 {@code paidAt} / {@code receivedAt}
 *       / {@code shippedAt} 任一键 ⇒ 屏幕退回「恒 `-`」（#6882 同类；用户 2026-10-17 裁定 A 的初衷）。</li>
 * </ol>
 *
 * <p>⚠️ 本判据读**源码文本**（不做 AST）—— 本仓既有形态（{@code OrderAutoCompleteSqlGuardTest} 同款）。
 * 代价：它只能证明「这几个字在方法体里」；<b>行为面（真库写入 / SQL 谓词）由既有
 * {@code AutoCompleteShippedRealDbTest} 与 {@code OrderService} 单测承担</b>（§28.2：
 * 结构判据绿 ≠ 接线在，两面缺一不可）。判据本体抽成**纯谓词**并做**判别力自证**：
 * 四种坏形态必须在内存里各自判红（否则判据本身可能已退化成恒真）。</p>
 */
@DisplayName("#7078 结构判据：paid_at 只在 pending→confirmed 写、received_at 两条完成路都写、详情响应透出三键")
class OrderPaidAndReceivedAtWriteGuardTest {

    private static final Path MAIN = Path.of("src", "main", "java", "com", "migao", "admin");
    private static final Path ORDER_SERVICE = MAIN.resolve("service/OrderService.java");
    private static final Path ORDER_MAPPER = MAIN.resolve("mapper/OrderMapper.java");
    private static final Path ORDER_DETAIL_RESPONSE = MAIN.resolve("dto/OrderDetailResponse.java");

    private static String source(Path path) throws IOException {
        assertThat(path).as("判据的扫描面必须真实存在（路径漂移 ⇒ 判红，不是空跑通过）").exists();
        return Files.readString(path, StandardCharsets.UTF_8);
    }

    // ── 解析件 ────────────────────────────────────────────────────────────────

    /**
     * 剥掉块注释与行注释（否则**注释里提一句字段名**就能把判据喂绿/喂红 ——
     * 本仓 {@code migao-dev-flow} §17.3「判据被自己的文案喂红」同族）。
     * 本判据扫的是 {@code src/main} 的**代码**，注释里的说明不构成证据。
     */
    static String stripComments(String src) {
        StringBuilder out = new StringBuilder(src.length());
        boolean inBlock = false;
        boolean inLine = false;
        for (int i = 0; i < src.length(); i++) {
            char c = src.charAt(i);
            char next = i + 1 < src.length() ? src.charAt(i + 1) : '\0';
            if (inBlock) {
                if (c == '*' && next == '/') {
                    inBlock = false;
                    i++;
                }
                continue;
            }
            if (inLine) {
                if (c == '\n') {
                    inLine = false;
                    out.append(c);
                }
                continue;
            }
            if (c == '/' && next == '*') {
                inBlock = true;
                i++;
                continue;
            }
            if (c == '/' && next == '/') {
                inLine = true;
                i++;
                continue;
            }
            out.append(c);
        }
        return out.toString();
    }

    /**
     * 取名为 {@code name} 的**方法声明**体（含签名），按大括号配平截断。找不到 ⇒ 返回空串（判据随后判红）。
     *
     * <p>🔴 必须区分**声明点**与**调用点**：本仓 {@code transitionStatusAtomic} 在
     * {@code OrderService} 里有 3 处调用，且**都在声明之前** ⇒ 朴素的「第一次出现」会截到一段
     * 无关代码（实测：本判据第一版就这么红过）。判据 = 「名字之前那一段语句里带访问修饰符」。</p>
     */
    static String methodBody(String src, String name) {
        int from = 0;
        while (true) {
            int sig = src.indexOf(name + "(", from);
            if (sig < 0) {
                return "";
            }
            from = sig + 1;
            int segStart = Math.max(
                    Math.max(src.lastIndexOf(';', sig), src.lastIndexOf('{', sig)),
                    src.lastIndexOf('}', sig)) + 1;
            String segment = src.substring(segStart, sig);
            if (!segment.contains("private ") && !segment.contains("public ") && !segment.contains("protected ")) {
                continue; // 调用点，不是声明
            }
            int open = src.indexOf('{', sig);
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
                        return src.substring(sig, i + 1);
                    }
                }
            }
            return "";
        }
    }

    static int count(String src, String needle) {
        int n = 0;
        int i = src.indexOf(needle);
        while (i >= 0) {
            n++;
            i = src.indexOf(needle, i + needle.length());
        }
        return n;
    }

    // ── 判据本体（纯谓词；坏形态由下面的判别力自证逐条注入）────────────────────

    /** {@code paid_at}：全类**只有一个**写面，且落在 {@code transitionStatusAtomic} 的 pending→confirmed 边上。 */
    static boolean paidAtIsWrittenOnlyOnTheConfirmEdge(String orderServiceSrc) {
        String src = stripComments(orderServiceSrc);
        if (count(src, "set(Order::getPaidAt") != 1) {
            return false;
        }
        String body = methodBody(src, "transitionStatusAtomic");
        if (!body.contains("set(Order::getPaidAt")) {
            return false;
        }
        // 两个限定缺一不可：新态 confirmed + **期望前驱** pending（回退边限定）
        return body.contains("\"confirmed\".equals(newStatus)")
                && body.contains("\"pending\".equals(expectedStatus)");
    }

    /** {@code received_at}：商家确认收货（{@code transitionStatusAtomic}）与自动完成（mapper SQL）两条路都写。 */
    static boolean receivedAtIsWrittenOnBothCompletedPaths(String orderServiceSrc, String orderMapperSrc) {
        String service = stripComments(orderServiceSrc);
        if (count(service, "set(Order::getReceivedAt") != 1) {
            return false;
        }
        String body = methodBody(service, "transitionStatusAtomic");
        if (!body.contains("set(Order::getReceivedAt") || !body.contains("\"completed\".equals(newStatus)")) {
            return false;
        }
        // 自动完成那条腿**不经** transitionStatusAtomic ⇒ 必须在它自己的 SQL 里同写
        return stripComments(orderMapperSrc).contains("received_at = NOW()");
    }

    /** 详情响应必须**透出**三个时刻（否则屏幕退回「恒 `-`」）。 */
    static boolean detailResponseExposesTheThreeTimestamps(String dtoSrc) {
        String src = stripComments(dtoSrc);
        return src.contains("private OffsetDateTime paidAt;")
                && src.contains("private OffsetDateTime receivedAt;")
                && src.contains("private OffsetDateTime shippedAt;");
    }

    // ── 真语料判据 ────────────────────────────────────────────────────────────

    @Test
    @DisplayName("paid_at 只在 pending→confirmed 这条边上写（回退边不得写）")
    void paidAtIsWrittenOnlyOnTheConfirmEdge() throws IOException {
        assertThat(paidAtIsWrittenOnlyOnTheConfirmEdge(source(ORDER_SERVICE)))
                .as("paid_at 的写面漂了（被写到回退边 / 挪出 transitionStatusAtomic / 多出第二个写面）")
                .isTrue();
    }

    @Test
    @DisplayName("received_at 由商家确认收货与自动完成**两条路**各写一次")
    void receivedAtIsWrittenOnBothCompletedPaths() throws IOException {
        assertThat(receivedAtIsWrittenOnBothCompletedPaths(source(ORDER_SERVICE), source(ORDER_MAPPER)))
                .as("received_at 的写面漂了（自动完成那条腿漏写 ⇒ 那批单永远空值且不会有别的东西变红）")
                .isTrue();
    }

    @Test
    @DisplayName("OrderDetailResponse 透出 paidAt / receivedAt / shippedAt 三键")
    void detailResponseExposesTheThreeTimestamps() throws IOException {
        assertThat(detailResponseExposesTheThreeTimestamps(source(ORDER_DETAIL_RESPONSE)))
                .as("详情响应又读不回真值 ⇒ 屏幕退回「恒 -」（#6882 同类）")
                .isTrue();
    }

    // ── 判别力自证（四种坏形态必须在内存里各自判红；否则判据可能已退化成恒真）────

    @Test
    @DisplayName("判别力自证：注入四种坏形态 ⇒ 判据各自判红（未注入 ⇒ 不报）")
    void guardHasDiscriminatingPower() throws IOException {
        String service = source(ORDER_SERVICE);
        String mapper = source(ORDER_MAPPER);
        String dto = source(ORDER_DETAIL_RESPONSE);

        // 对照读数：真语料绿
        assertThat(paidAtIsWrittenOnlyOnTheConfirmEdge(service)).isTrue();
        assertThat(receivedAtIsWrittenOnBothCompletedPaths(service, mapper)).isTrue();

        // 坏 ①：摘掉「期望前驱 pending」限定 ⇒ 回退边也会写 paid_at
        assertThat(paidAtIsWrittenOnlyOnTheConfirmEdge(
                service.replace("\"pending\".equals(expectedStatus)", "\"anything\".equals(expectedStatus)")))
                .as("摘掉回退边限定后判据仍绿 ⇒ 判据没有判别力")
                .isFalse();

        // 坏 ②：多出一个 paid_at 写面（第二个类内写点）
        assertThat(paidAtIsWrittenOnlyOnTheConfirmEdge(
                service + "\nclass SecondWriter { void w(LambdaUpdateWrapper<Order> u) { u.set(Order::getPaidAt, null); } }\n"))
                .as("多出第二个 paid_at 写面后判据仍绿 ⇒ 判据没有判别力")
                .isFalse();

        // 坏 ③：自动完成那条腿漏写 received_at
        assertThat(receivedAtIsWrittenOnBothCompletedPaths(service, mapper.replace("received_at = NOW()", "updated_at = NOW()")))
                .as("自动完成腿漏写 received_at 后判据仍绿 ⇒ 判据没有判别力")
                .isFalse();

        // 坏 ④：商家确认收货那条腿漏写 received_at
        assertThat(receivedAtIsWrittenOnBothCompletedPaths(
                service.replace("set(Order::getReceivedAt", "set(Order::getUpdatedAt"), mapper))
                .as("确认收货腿漏写 received_at 后判据仍绿 ⇒ 判据没有判别力")
                .isFalse();

        // 坏 ⑤：详情响应漏一个键
        assertThat(detailResponseExposesTheThreeTimestamps(
                dto.replace("private OffsetDateTime receivedAt;", "")))
                .as("详情响应漏 receivedAt 后判据仍绿 ⇒ 判据没有判别力")
                .isFalse();
    }
}
