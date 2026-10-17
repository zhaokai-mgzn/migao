// case_ids: MC-117
package com.migao.admin.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 🧱 <b>类级元守卫（issue #6956 · 现象 C）：T3 逻辑删除族必须判影响行数，未登记即红。</b>
 *
 * <h3>病根（不是「少写了几行 if」）</h3>
 * <p>{@code @TableLogic} 让 `xxxMapper.deleteById(id)` 变成
 * {@code UPDATE … SET deleted = 1 WHERE id = ? AND deleted = 0} —— <b>删不存在（或已被并发删掉）的行 = 0 行</b>。
 * 调用方普遍写成「先 {@code selectById} 判存在、再 {@code deleteById} 丢弃返回值」，于是并发双删时
 * <b>两个请求都回 200</b>（都通过了存在性判读），而真正生效的只有一次 —— 这正是 issue #6962 / #6961
 * 那一族「读改写」形态在删除面上的同族品。</p>
 *
 * <h3>为什么用台账（而不是一刀切全改）</h3>
 * <p>18 处丢弃返回值的形态里有一部分<b>本来就该幂等</b>：父单级联删明细、按差分集合清理 SKU/颜色 ——
 * 把它们也判 404 会让「重放一次同样的清理」失败（运维脚本 / 导入重试当场红）。所以判据是
 * <b>「未登记即红」</b>：新增/漏改立刻红，登记过的必须写明为什么可以丢 + 重启条件。</p>
 *
 * <h3>本守卫保证什么 / 不保证什么</h3>
 * <ul>
 *   <li><b>保证</b>：{@code service/*.java} 里**独立成句**的 {@code deleteById/deleteBatchIds} 调用，
 *       要么已改成读行数（不在射程），要么在台账里具名登记；台账条目必须逐字兑现；豁免只许缩短。</li>
 *   <li><b>不保证</b>「0 行时抛 404 还是 409」—— 不同入口语义不同，由各自的实例判据钉（见
 *       {@code #{@code OrderLogisticsServiceTest}} / {@code NotificationRuleServiceTest} / {@code ProductServiceTest}）。</li>
 * </ul>
 */
@DisplayName("🧱 类级元守卫（#6956）：T3 逻辑删除必须判影响行数（未登记即红 + 豁免只许缩短）")
class T3LogicalDeleteRowCountMetaGuardTest {

    /** 模块根（Surefire 的工作目录 = {@code backend/admin-api}）。 */
    private static final Path MODULE = Path.of("");
    private static final Path SERVICE_DIR = MODULE.resolve("src/main/java/com/migao/admin/service");
    private static final Path LEDGER = MODULE.resolve("src/test/resources/t3-delete-rowcount-ledger.json");

    private static final ObjectMapper JSON = new ObjectMapper();

    /** `xxxMapper.deleteById(…)` / `deleteBatchIds(…)` 的调用点（含前置的 `=` / `if (` / `return`，靠分组判消费）。 */
    private static final Pattern CALL = Pattern.compile(
            "(?m)^(?<lead>[ \\t]*)(?<prefix>[^;\\n]*?)(?<call>\\b\\w+Mapper\\.(?:deleteById|deleteBatchIds)\\s*\\([^;\\n]*\\))\\s*;");

    /** 返回值**被消费**的前缀形态：赋值 / 比较 / if / return / 断言。 */
    private static final Pattern CONSUMED_PREFIX = Pattern.compile(
            "(\\bint\\s+\\w+\\s*=\\s*$)|(=\\s*$)|(\\bif\\s*\\(.*)|(\\breturn\\s+.*)|(\\bassert\\w*\\s*\\(.*)");

    /** 方法头（类体顶层，4 空格缩进以修饰符开头）—— 用来算调用点所属方法名。 */
    private static final Pattern METHOD_HEAD = Pattern.compile(
            "^ {4}(?:public|private|protected|static|final|synchronized|abstract|default|native|strictfp)\\b[^;{]*\\{");

    private record Site(String file, String method, String call) {
        /**
         * 注册键 = 文件 + **调用锚**（不含方法名）。为什么不用方法名：本仓方法签名会跨行，
         * 「调用点属于哪个方法」只能靠启发式反推（实测会把 `saveColorsAndSkus` 认成前一个方法）
         * ⇒ 拿它当键会让台账与扫描器永远对不上。锚是逐字文本，两边都稳定。
         */
        String key() {
            return file + "::" + normalize(call);
        }
    }

    private record Exempt(String file, String method, String anchor, String reason) {
    }

    // ────────────────────────────────────────────── 判据 1：真语料

    @Test
    @DisplayName("未登记的「丢弃删除行数」调用必须判红；台账条目必须逐字兑现；豁免只许缩短")
    void unregisteredDiscardedDeleteCallsAreRed() throws IOException {
        Corpus real = realCorpus();
        List<Site> scanned = scan(real.files());
        List<String> problems = problems(real, scanned);

        System.out.println("[READING MC-117] 现取「丢弃行数」的删除调用 = " + scanned.size()
                + "，台账豁免 = " + real.exempt().size() + "（基线 " + real.exemptBaseline() + "）");
        scanned.forEach(s -> System.out.println("    · " + s.file().substring(s.file().lastIndexOf('/') + 1)
                + "#" + s.method() + " → " + s.call()));
        problems.forEach(p -> System.out.println("    ❌ " + p));

        assertThat(problems).as("「未登记即红」：新增/漏改必须登记或改判行数（issue #6956 · 现象 C）").isEmpty();
        assertThat(real.exempt().size())
                .as("豁免台账只许缩短（新增豁免必须写明为什么可以丢 + 重启条件）")
                .isLessThanOrEqualTo(real.exemptBaseline());
    }

    // ────────────────────────────────────────────── 判据 2：扫描器非盲 + 判别力自证（合成语料）

    @Test
    @DisplayName("扫描器非盲 + 判别力自证：丢弃形态判红、读行数形态判绿、注释/字符串里的假调用不算")
    void scannerSeesAndDiscriminates() throws IOException {
        Corpus real = realCorpus();
        // 扫描器非空跑自证：真语料里确实还有登记过的幂等形态（否则「0 处」可能只是扫描器瞎了）
        assertThat(scan(real.files())).as("扫描器必须真的扫到东西（0 处 ⇒ 判据失明，不是「全部合规」）").isNotEmpty();

        // ① 丢弃形态 ⇒ 红
        Map<String, String> bad = new LinkedHashMap<>();
        bad.put("src/main/java/com/migao/admin/service/DemoService.java", """
                package demo;
                class DemoService {
                    private DemoMapper demoMapper;
                    public void deleteDemo(String id) {
                        demoMapper.deleteById(id);
                    }
                }
                """);
        assertThat(problems(new Corpus(bad, syntheticLedger()), scan(bad)))
                .as("丢弃返回值必须判红（= 并发双删两个 200 的病根形态）").isNotEmpty();

        // ② 读行数形态 ⇒ 绿（这就是修后的样子）
        Map<String, String> good = new LinkedHashMap<>();
        good.put("src/main/java/com/migao/admin/service/DemoService.java", """
                package demo;
                class DemoService {
                    private DemoMapper demoMapper;
                    public void deleteDemo(String id) {
                        if (demoMapper.deleteById(id) == 0) {
                            throw new IllegalStateException("不存在");
                        }
                    }
                }
                """);
        assertThat(problems(new Corpus(good, syntheticLedger()), scan(good)))
                .as("读行数形态必须判绿（否则本守卫恒红噪声，没人能合入）").isEmpty();

        // ③ 注释 / 字符串里的假调用 ⇒ 不许算（否则任何人写一行 javadoc 都会红）
        Map<String, String> decoy = new LinkedHashMap<>();
        decoy.put("src/main/java/com/migao/admin/service/DemoService.java", """
                package demo;
                class DemoService {
                    private DemoMapper demoMapper;
                    /** 例：{@code demoMapper.deleteById(id);} 是被禁形态 */
                    public void deleteDemo(String id) {
                        String s = "demoMapper.deleteById(id);";
                        demoMapper.deleteById(id);
                    }
                }
                """);
        List<Site> decoySites = scan(decoy);
        assertThat(decoySites).as("注释/字符串里的调用不得被算进射程（只应算真调用那 1 条）").hasSize(1);

        // ④ 台账给不存在的对象盖章 ⇒ 红（防「登记过了」的假绿）
        Map<String, String> ghost = new LinkedHashMap<>(real.files());
        ghost.put(real.exempt().get(0).file(), real.files().get(real.exempt().get(0).file())
                .replace(real.exempt().get(0).anchor(), "demoMapper.deleteById(ghost);"));
        assertThat(problems(new Corpus(ghost, real.ledger()), scan(ghost)))
                .as("台账条目的锚在文件里找不到 ⇒ 必须判红（否则「登记」可以随便写）").isNotEmpty();
    }

    // ────────────────────────────────────────────── 判定本体

    /** 一次判定：扫描 + 台账核对（真语料 / 合成语料共用）。 */
    private static List<String> problems(Corpus c, List<Site> scanned) {
        List<String> problems = new ArrayList<>();
        Set<String> registered = new java.util.HashSet<>();
        for (Exempt e : c.exempt()) {
            String text = c.files().get(e.file());
            if (text == null) {
                problems.add("台账登记了射程外的文件：" + e.file());
                continue;
            }
            if (!normalize(text).contains(normalize(e.anchor()))) {
                problems.add("台账未兑现 / 给不存在的对象盖章：" + e.file() + "#" + e.method()
                        + " 里找不到锚 `" + e.anchor() + "`");
                continue;
            }
            if (e.reason() == null || e.reason().isBlank()) {
                problems.add("台账豁免缺理由：" + e.file() + "#" + e.method() + "（为什么可以丢弃行数？）");
            }
            registered.add(e.file() + "::" + normalize(e.anchor()));
        }
        for (Site s : scanned) {
            if (!registered.contains(s.key())) {
                problems.add("未登记的状态：丢弃删除行数 → " + s.file() + "#" + s.method()
                        + " `" + s.call() + "`（并发双删会两个都 200；要么判 0 行，要么在台账写明为什么可以丢）");
            }
        }
        return problems;
    }

    /** 现取「独立成句、返回值被丢弃」的删除调用。 */
    private static List<Site> scan(Map<String, String> files) {
        List<Site> out = new ArrayList<>();
        for (Map.Entry<String, String> e : files.entrySet()) {
            if (!e.getKey().contains("/service/") || !e.getKey().endsWith(".java")) {
                continue;
            }
            String src = stripCommentsAndStrings(e.getValue());
            String[] lines = src.split("\n", -1);
            Matcher m = CALL.matcher(src);
            while (m.find()) {
                if (CONSUMED_PREFIX.matcher(m.group("prefix").stripTrailing()).find()) {
                    continue;   // 返回值被消费 ⇒ 修后的形态，不在射程
                }
                int line = src.substring(0, m.start()).split("\n", -1).length - 1;
                out.add(new Site(e.getKey(), enclosingMethod(lines, line), m.group("call")));
            }
        }
        return out;
    }

    private static String enclosingMethod(String[] lines, int callLine) {
        for (int i = callLine; i >= 0; i--) {
            if (!METHOD_HEAD.matcher(lines[i]).matches()) {
                continue;
            }
            String head = lines[i].strip();
            int sp = head.indexOf('(');
            String beforeParen = sp < 0 ? head : head.substring(0, sp);
            int lastSp = beforeParen.lastIndexOf(' ');
            return beforeParen.substring(lastSp + 1).strip();
        }
        return "<unknown>";
    }

    /** 取方法体（从方法头行到配平的 `}`）—— 用于「锚必须逐字兑现」。 */
    private static String methodBody(String src, String name) {
        String stripped = stripCommentsAndStrings(src);
        String[] lines = stripped.split("\n", -1);
        Pattern head = Pattern.compile("^ {4}(?:public|private|protected|static|final|synchronized|abstract|default|native|strictfp)\\b.*\\b"
                + Pattern.quote(name) + "\\s*\\(");
        for (int i = 0; i < lines.length; i++) {
            if (!head.matcher(lines[i]).matches()) {
                continue;
            }
            int depth = 0;
            StringBuilder body = new StringBuilder();
            for (int j = i; j < lines.length; j++) {
                body.append(lines[j]).append('\n');
                for (char ch : lines[j].toCharArray()) {
                    if (ch == '{') depth++;
                    else if (ch == '}') depth--;
                }
                if (depth == 0 && j > i) break;
            }
            // 用**原文**取同一区间（锚要按原文逐字比对；剥壳后的文本把字符串换成了空白）
            String[] raw = src.split("\n", -1);
            StringBuilder rawBody = new StringBuilder();
            int d2 = 0;
            for (int j = i; j < raw.length; j++) {
                rawBody.append(raw[j]).append('\n');
                for (char ch : stripForDepth(raw[j]).toCharArray()) {
                    if (ch == '{') d2++;
                    else if (ch == '}') d2--;
                }
                if (d2 == 0 && j > i) break;
            }
            return rawBody.toString();
        }
        return null;
    }

    private static String stripForDepth(String line) {
        int idx = line.indexOf("//");
        return idx >= 0 ? line.substring(0, idx) : line;
    }

    /** 把注释 / 字符串 / 字符字面量替换成等长空白（保留换行 ⇒ 行号不变）。 */
    private static String stripCommentsAndStrings(String src) {
        char[] out = src.toCharArray();
        int i = 0, n = src.length();
        while (i < n) {
            char ch = src.charAt(i);
            if (ch == '/' && i + 1 < n && src.charAt(i + 1) == '/') {
                int end = src.indexOf('\n', i);
                end = end < 0 ? n : end;
                for (int k = i; k < end; k++) out[k] = ' ';
                i = end;
            } else if (ch == '/' && i + 1 < n && src.charAt(i + 1) == '*') {
                int end = src.indexOf("*/", i + 2);
                end = end < 0 ? n : end + 2;
                for (int k = i; k < end; k++) if (out[k] != '\n') out[k] = ' ';
                i = end;
            } else if (ch == '"' || ch == '\'') {
                char quote = ch;
                int k = i + 1;
                while (k < n) {
                    if (src.charAt(k) == '\\') { k += 2; continue; }
                    if (src.charAt(k) == quote) { k++; break; }
                    if (src.charAt(k) == '\n') break;
                    k++;
                }
                for (int j = i; j < k && j < n; j++) if (out[j] != '\n') out[j] = ' ';
                i = k;
            } else {
                i++;
            }
        }
        return new String(out);
    }

    /** 合成语料专用台账（空豁免）：真台账的豁免条目指向真实文件，套到迷你语料上会误判「射程外」。 */
    private static JsonNode syntheticLedger() {
        try {
            return JSON.readTree("{\"schema\":\"t3-delete-rowcount/1.0\",\"exempt\":[],\"exempt_baseline\":0}");
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    private static String normalize(String s) {
        // 扫描器抓到的调用片段**不含**结尾的 `;`（分组只到 `)`），台账里写的是完整语句 ⇒ 比对时去掉分号，
        // 否则「登记了却仍判未登记」（本单实测过的假红形态）。
        return s == null ? "" : s.replaceAll("\\s+", "").replaceAll(";+$", "");
    }

    // ────────────────────────────────────────────── 语料

    private record Corpus(Map<String, String> files, JsonNode ledger) {
        List<Exempt> exempt() {
            List<Exempt> out = new ArrayList<>();
            for (JsonNode e : ledger.path("exempt")) {
                out.add(new Exempt(e.path("file").asText(""), e.path("method").asText(""),
                        e.path("call_anchor").asText(""), e.path("reason").asText("")));
            }
            return out;
        }

        int exemptBaseline() {
            return ledger.path("exempt_baseline").asInt(-1);
        }
    }

    /** 从工作树读真语料：{@code service/} 下全部 Java 源 + 台账。 */
    private static Corpus realCorpus() throws IOException {
        Map<String, String> files = new LinkedHashMap<>();
        Path serviceDir = repoRoot().resolve("backend/admin-api/src/main/java/com/migao/admin/service");
        try (var stream = Files.list(serviceDir)) {
            for (Path p : stream.filter(x -> x.toString().endsWith(".java")).sorted().toList()) {
                files.put("backend/admin-api/src/main/java/com/migao/admin/service/" + p.getFileName(),
                        Files.readString(p, StandardCharsets.UTF_8));
            }
        }
        Path ledger = repoRoot().resolve("backend/admin-api/src/test/resources/t3-delete-rowcount-ledger.json");
        return new Corpus(files, JSON.readTree(ledger.toFile()));
    }

    /** 仓库根：Surefire 的工作目录是 {@code backend/admin-api}。 */
    private static Path repoRoot() {
        Path p = MODULE.toAbsolutePath();
        for (int i = 0; i < 5 && p != null; i++) {
            if (Files.isDirectory(p.resolve(".github/cases"))) {
                return p;
            }
            p = p.getParent();
        }
        throw new IllegalStateException("找不到仓库根（从 " + MODULE.toAbsolutePath() + " 向上 5 层未见 .github/cases）");
    }
}
