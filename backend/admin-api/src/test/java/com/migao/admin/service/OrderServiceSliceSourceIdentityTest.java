// case_ids: MC-199
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * {@link OrderService} 切片（issue #8191，P2-1c）的<b>搬运逐字节一致</b>判据。
 *
 * <p>拆出去的是<b>搬运</b>，不是重写：库存族（18 个方法）与财务流水族（4 个方法）的**方法体**
 * 必须与拆分前逐字节相同。证据是随本判据一起入库的**拆分前源码**
 * {@code src/test/resources/order-slice/OrderService.baseline.txt}（取自 {@code origin/main}
 * 的 {@code OrderService.java}，2685 行，sha256 钉在本类里 ⇒ 基线被改会当场红）。</p>
 *
 * <p><b>三条断言</b>：① 基线里每个方法体都**原样**出现在新载体文件里；② 门面 {@link OrderService}
 * 里**不再有**这些方法体（唯一实现点，不留第二份口径）；③ 写面锚点只在新载体出现
 * （{@code StockChange.from(productSkuMapper.deductStock(} / {@code FinanceTransaction.builder()}）。</p>
 *
 * <p><b>判别力自证</b>：把新载体文本在内存里改一个字符 ⇒ 第 ① 条必须变红（见最后一个用例）。
 * 没有这段，本判据可能只是「两边都读了同一个文件」的空断言。</p>
 */
class OrderServiceSliceSourceIdentityTest {

    /** 拆分前 {@code OrderService.java}（origin/main）的 sha256 —— 基线被改动即判红。 */
    private static final String BASELINE_SHA256 =
            "2fe075fd5cb33a45a8f1fa90ea167f535aa258037a214ba3e401abde23bd5a60";

    private static final String SERVICE_DIR = "src/main/java/com/migao/admin/service/";

    /** (方法名, 同名重载中的第几个从 0 起) —— 库存族 18 个。 */
    private static final List<String[]> STOCK_METHODS = List.of(
            new String[]{"validateStockSufficient", "0"},
            new String[]{"validateStockSufficientForRequest", "0"},
            new String[]{"validateStockSufficientForItems", "0"},
            new String[]{"deductStockAndIncreaseSales", "0"},
            new String[]{"restoreStockAndDecreaseSales", "0"},
            new String[]{"restoreStockForReturn", "0"},
            new String[]{"adjustStockAndSales", "0"},
            new String[]{"deductSkuStock", "0"},
            new String[]{"restoreSkuStock", "0"},
            new String[]{"restoreStockForLedger", "0"},
            new String[]{"recordAtomicStockChange", "0"},
            new String[]{"matchSkuId", "0"},
            new String[]{"findSkuByKeyFamily", "0"},
            new String[]{"belongsToProduct", "0"},
            new String[]{"toSkuText", "0"},
            new String[]{"toSkuKey", "0"},
            new String[]{"describeDeclaredSpec", "0"},
            new String[]{"findSkuByCombination", "0"});

    /** 财务流水族 4 个（{@code recordFinanceTransaction} 两个重载）。 */
    private static final List<String[]> FEE_METHODS = List.of(
            new String[]{"effectiveActualAmount", "0"},
            new String[]{"recordFinanceTransaction", "0"},
            new String[]{"recordFinanceTransaction", "1"},
            new String[]{"generateFinanceTransactionNo", "0"});

    @Test
    @DisplayName("基线自证：资源文件就是拆分前 origin/main 的 OrderService.java（sha256 钉死）")
    void baselineIsThePreSplitSource() throws Exception {
        String baseline = baseline();

        assertThat(sha256(baseline)).as("基线必须是拆分前的 OrderService.java（origin/main），否则本判据无意义")
                .isEqualTo(BASELINE_SHA256);
        assertThat(baseline.lines().count()).as("基线行数（拆分前 2,685）").isEqualTo(2685L);
        assertThat(bodyOf(baseline, "recordAtomicStockChange", 0))
                .as("基线里必须真有本单搬走的方法（扫描器失明 ⇒ 判据空跑）")
                .contains("stockLedgerService.record(");
    }

    @Test
    @DisplayName("搬运逐字节一致：库存族 18 个方法体原样出现在 OrderStockService，且门面里不再有它们")
    void stockFamilyBodiesAreVerbatim() throws Exception {
        String baseline = baseline();
        String stock = read(Path.of(SERVICE_DIR + "OrderStockService.java"));

        List<String> missing = new ArrayList<>();
        List<String> leftover = new ArrayList<>();
        for (String[] entry : STOCK_METHODS) {
            String body = bodyOf(baseline, entry[0], Integer.parseInt(entry[1]));
            assertThat(body).as("基线里必须找得到 " + entry[0] + " 的方法体").isNotEmpty();
            if (!stock.contains(body)) {
                missing.add(entry[0]);
            }
            if (facadeSource().contains(body)) {
                leftover.add(entry[0]);
            }
        }

        assertThat(missing).as("这些方法体在 OrderStockService 里不再逐字节一致（拆分被重写/被改动）").isEmpty();
        assertThat(leftover).as("这些方法体仍留在门面里（= 第二份口径，搬走就该删掉）").isEmpty();
    }

    @Test
    @DisplayName("搬运逐字节一致：财务流水族 4 个方法体原样出现在 OrderFeeSupport，且门面里不再有它们")
    void feeFamilyBodiesAreVerbatim() throws Exception {
        String baseline = baseline();
        String fee = read(Path.of(SERVICE_DIR + "OrderFeeSupport.java"));

        List<String> missing = new ArrayList<>();
        List<String> leftover = new ArrayList<>();
        for (String[] entry : FEE_METHODS) {
            String body = bodyOf(baseline, entry[0], Integer.parseInt(entry[1]));
            assertThat(body).as("基线里必须找得到 " + entry[0] + " 的方法体").isNotEmpty();
            if (!fee.contains(body)) {
                missing.add(entry[0]);
            }
            if (facadeSource().contains(body)) {
                leftover.add(entry[0]);
            }
        }

        assertThat(missing).as("这些方法体在 OrderFeeSupport 里不再逐字节一致").isEmpty();
        assertThat(leftover).as("这些方法体仍留在门面里（= 第二份口径）").isEmpty();
    }

    @Test
    @DisplayName("写面唯一：扣减与记账的写面锚点只在新载体出现，门面里一处都没有")
    void writeAnchorsLiveOnlyInTheNewCarriers() throws Exception {
        String facade = facadeSource();
        String stock = read(Path.of(SERVICE_DIR + "OrderStockService.java"));
        String fee = read(Path.of(SERVICE_DIR + "OrderFeeSupport.java"));

        assertThat(stock).as("库存扣减的原子读数锚点必须在新载体")
                .contains("StockChange.from(productSkuMapper.deductStock(");
        assertThat(fee).as("流水登记写面必须在新载体").contains("FinanceTransaction.builder()");
        assertThat(facade).as("门面不得再自己扣库存（那会绕过新载体）")
                .doesNotContain("StockChange.from(productSkuMapper.deductStock(");
        assertThat(facade).as("门面不得再自己写流水（那会绕过新载体）")
                .doesNotContain("FinanceTransaction.builder()");
        assertThat(facade).as("门面不得再读库存快照落台账")
                .doesNotContain("recordAtomicStockChange");
    }

    @Test
    @DisplayName("判别力自证：把新载体改一个字符 ⇒ 「逐字节一致」必须当场判红（否则是空断言）")
    void byteIdentityCheckHasDiscriminatingPower() throws Exception {
        String baseline = baseline();
        String stock = read(Path.of(SERVICE_DIR + "OrderStockService.java"));
        String body = bodyOf(baseline, "deductSkuStock", 0);

        assertThat(stock).as("对照：未注入时该载体确实包含基线方法体").contains(body);
        String mutated = stock.replace("库存已被并发订单占用", "库存已被占用");
        assertThat(mutated).as("注入必须真的改到了字面量（否则下面的「判红」是假的）")
                .isNotEqualTo(stock);
        assertThat(mutated).as("注入后必须被判红：一致性检查对单字符改动敏感").doesNotContain(body);
    }

    // ────────────────────────────────────────────── 读取与提取

    private static String facadeSource() throws Exception {
        return read(Path.of(SERVICE_DIR + "OrderService.java"));
    }

    private static String read(Path path) throws Exception {
        assertThat(Files.exists(path)).as("源码路径必须真实存在（漂移 ⇒ 判红，不是空跑通过）：" + path).isTrue();
        return Files.readString(path, StandardCharsets.UTF_8);
    }

    private static String baseline() throws Exception {
        try (InputStream in = OrderServiceSliceSourceIdentityTest.class
                .getResourceAsStream("/order-slice/OrderService.baseline.txt")) {
            assertThat(in).as("基线资源必须存在（/order-slice/OrderService.baseline.txt）").isNotNull();
            return new String(in.readAllBytes(), StandardCharsets.UTF_8);
        }
    }

    private static String sha256(String text) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        return HexFormat.of().formatHex(digest.digest(text.getBytes(StandardCharsets.UTF_8)));
    }

    /**
     * 取「方法体」原文（{@code { 到配对的 } }，含两端）。
     *
     * <p>只做括号配对，跳字符串 / 字符字面量与注释；不做语法分析 —— 判据只需要「同一段文本」。</p>
     */
    static String bodyOf(String source, String name, int occurrence) {
        Pattern decl = Pattern.compile(
                "(?m)^    (?:public |private |protected )?(?:static )?(?=[^ \\n=;{}])[^\\n=;{}]*\\b" + Pattern.quote(name) + "\\s*\\(");
        Matcher m = decl.matcher(source);
        int seen = -1;
        int from = -1;
        while (m.find()) {
            seen++;
            if (seen == occurrence) {
                from = m.end();
                break;
            }
        }
        if (from < 0) {
            return "";
        }
        int open = source.indexOf('{', from);
        if (open < 0) {
            return "";
        }
        int depth = 0;
        boolean inLine = false;
        boolean inBlock = false;
        boolean inStr = false;
        boolean inChr = false;
        for (int i = open; i < source.length(); i++) {
            char c = source.charAt(i);
            char next = i + 1 < source.length() ? source.charAt(i + 1) : '\0';
            if (inLine) {
                if (c == '\n') {
                    inLine = false;
                }
                continue;
            }
            if (inBlock) {
                if (c == '*' && next == '/') {
                    inBlock = false;
                    i++;
                }
                continue;
            }
            if (inStr || inChr) {
                if (c == '\\') {
                    i++;
                } else if ((inStr && c == '"') || (inChr && c == '\'')) {
                    inStr = inChr = false;
                }
                continue;
            }
            if (c == '/' && next == '/') {
                inLine = true;
                i++;
                continue;
            }
            if (c == '/' && next == '*') {
                inBlock = true;
                i++;
                continue;
            }
            if (c == '"') {
                inStr = true;
                continue;
            }
            if (c == '\'') {
                inChr = true;
                continue;
            }
            if (c == '{') {
                depth++;
            } else if (c == '}') {
                depth--;
                if (depth == 0) {
                    return source.substring(open, i + 1);
                }
            }
        }
        return "";
    }
}
