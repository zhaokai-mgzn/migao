// case_ids: MC-022
package com.migao.admin.time;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 驻留守卫（<b>测试侧</b>）：业务「今天」在 {@code src/test/java} 里也只能有一个来源
 * （{@link BusinessClock}）—— issue #5651 收口时的实测缺陷。
 *
 * <h2>缺陷本体（实测，不是推断）</h2>
 *
 * <p>生产侧早就有单点时钟（issue #3802：{@code BusinessClock}，业务日固定
 * {@code Asia/Shanghai}），且有 {@link BusinessClockSourceGuardTest} 守 {@code src/main}。
 * <b>但测试侧没有任何守卫</b>，于是 5 条断言用裸 {@code LocalDate.now()} 取「今天」——</p>
 *
 * <ul>
 *   <li>CI runner 的 <b>JVM 默认时区 = UTC</b>，生产的业务日 = <b>+08</b>；
 *       两者在 <b>UTC 16:00–24:00（北京 00:00–08:00）差一天</b> ⇒ 每天红 8 小时；</li>
 *   <li>实测读数（required 检查 {@code admin-api unit tests}）：job 36280962072 跑在
 *       {@code 2026-09-26T23:58Z–00:00Z}，断言给出
 *       {@code expected: 2026-09-26 but was: 2026-09-27}（另两处 {@code -3/-4}、{@code 1/0}）；
 *       同一份代码在 UTC 00:00–16:00 窗口内**全绿**（本地 23:53Z 也是绿的 —— 本机 JVM 默认时区
 *       = +08，两侧恰好同区 ⇒ 「本地绿、CI 红」）。</li>
 *   <li>⇒ 这不是「某行写错」，而是<b>同一概念在测试侧又长出一份口径</b>，且<a>没有任何东西会因此变红</a>。</li>
 * </ul>
 *
 * <h2>判据（每条都有红证）</h2>
 * <ol>
 *   <li>{@link #testSourcesReadBusinessTimeOnlyViaBusinessClock()}：{@code src/test/java} 里
 *       不得出现下表的「时间口径」写法（**剥注释后**判定，见下）；</li>
 *   <li>{@link #ledgerOnlyShrinks()}：存量走<b>文件 × 规则</b>台账，条数**冻结**——
 *       新命中即红、超数即红、台账里的条目不再命中也要红（必须销账）；</li>
 *   <li>{@link #theClassesFixedByThisChangeAreClean()}：本单修掉的三个测试类**在扫描面内**
 *       且命中数为 **0**（实例判据；只登记「扫描面非空」是不够的 —— 那证明不了覆盖到它们）；</li>
 *   <li>{@link #testSourcesReadBusinessTimeOnlyViaBusinessClock()} 的第二段：扫描面必须真的有文件
 *       （路径漂移 ⇒ 判红，不是空跑通过）—— 原文这里写的是一个**不存在的方法** {@code scanSurfaceIsNotEmpty}，
 *       顺手改准（判据本身就在前一条里，没有第二个方法）；</li>
 *   <li>{@link #rulesHaveDiscriminatingPower()}：每条禁则必须能命中一个「已知坏样本」；</li>
 *   <li>{@link #detectsInjectedViolationInIsolatedTree(Path)}：把违规样本放进隔离目录，
 *       扫描器必须逐条报出（且不碰真源树）。</li>
 *   <li>{@link #familyRulesSeparateBusinessBasisFromDurationBrackets()}（issue #5689）：本单按族补齐的
 *       禁则<b>只判「当业务基准用」</b>，且<b>两侧都自证</b> —— 坏样本必红、合法形态（计时括号 / 夹具数据）
 *       必绿（只证一侧 = 分不清「没误伤」与「判别力为零」）；</li>
 *   <li>{@link #commentOnlyMentionsAreNotViolations()}：<b>只改注释</b>不会让族禁则红（对照读数 ——
 *       证明红证命中的是「日历投影」判定分支，不是锚失配）；</li>
 *   <li>{@link #manifestAndForbiddenRulesCannotDrift()}：族级覆盖清单的裁定 ≡ {@link #FORBIDDEN} 的
 *       needle 集合（只改一边 ⇒ 红）；</li>
 *   <li>{@link #everySpellingInTheTreeIsAdjudicated()}：测试树里现取的每个 {@code <类型>.now(} 拼写
 *       都必须已被裁定（未登记的新兄弟 ⇒ 红）+ 普查面不许空跑；</li>
 *   <li>{@link #outOfScopeSpellingsPresenceIsFrozen()}：本守卫<b>看不见</b>的墙钟入口冻结「今天有没有」——
 *       出现 ⇒ 红（要求人工裁定），消失 ⇒ 红（条目不许陈旧）；</li>
 *   <li>{@link #existingRulesAndLedgerSemanticsAreFrozen()}：既有 5 条禁则逐字仍在且仍是
 *       {@link Shape#ANYWHERE}，台账对<b>任意一条</b>注入 +1 必红；</li>
 *   <li>{@link #fixedClassesRawCensusIsReadLiveAndJudgedClean()}：三个已修类的族级<b>原始命中</b>按现取
 *       读数判（不许用旧口径的 0 充数），判红为 0 是逐处形态判定的结果。</li>
 * </ol>
 *
 * <h2>⚠️ 两条实测陷阱（本类自己踩过）</h2>
 * <ol>
 *   <li><b>必须剥注释</b>：修好的三个类的说明注释里就写着 {@code LocalDate.now()}
 *       （解释「为什么不许用」）—— 按原文扫描会把解释性注释读成违规
 *       （`migao-dev-flow` §23.4 T2：判据被自己的文案喂红）；</li>
 *   <li><b>判据语料必须排除判据自身</b>（§23.8 B1）：{@link BusinessClockSourceGuardTest}
 *       与<b>本文件</b>里，禁则的 needle 本身就是字面量（{@code "LocalDate.now("}）⇒ 扫描它们
 *       等于把守卫自己的规则表数成违规。故两者按<b>具名排除</b>处理（不是计数豁免）。</li>
 * </ol>
 *
 * <h2>为什么不是「给 surefire 设 -Duser.timezone=Asia/Shanghai」</h2>
 * <p>那个配置面确实能一处改全仓，但它<b>把墙钟留在判据里</b>：测试仍旧读「现在」，
 * 只是让两侧的<b>时区</b>偶然一致 ⇒ ① 跨业务日零点（+08 00:00）仍有窄竞态；
 * ② 在 IDE / 其它 runner 里跑，口径又不同（判据随环境漂移）；③ 存量 40 处隐患继续隐身。
 * 本单选择<b>逐测试注入生产侧同一只时钟</b>：判据的来源从「JVM 默认时区」换成「业务时钟」，
 * 与 runner 时区无关，且存量以台账显形（只许缩短）。</p>
 *
 * <h2>族级覆盖清单：本守卫到底枚举了哪些拼写、还漏了哪些（issue #5689）</h2>
 *
 * <p>缺陷结构：禁则 4 的意图逐字是「<b>时区真值只许出现在 {@code BusinessClock} 一处</b>」——
 * 那是<b>族级</b>意图；而禁则 1~3 只列了 {@code LocalDate} / {@code LocalDateTime} / {@code LocalTime}
 * 三个<b>拼写</b>。⇒ 意图是族级的、实现是点名的 ⇒ <b>兄弟拼写漏网</b>，而事故现场用的那个拼写
 * （{@code OffsetDateTime.now()}）恰恰就是漏掉的那个。⇒ 本单的交付物不是「再补三条针」，而是把
 * <b>覆盖清单本身</b>做成可判的：{@link #SPELLINGS} 具名登记 + 未登记即红 + 条目不许陈旧。</p>
 *
 * <p><b>枚举了哪些</b>（逐条在 {@link #SPELLINGS} 具名）：</p>
 * <ul>
 *   <li><b>入禁列</b>：{@code LocalDate.now} / {@code LocalDateTime.now} / {@code LocalTime.now}
 *       （既有三条，语义<b>冻结</b>）· {@code OffsetDateTime.now} / {@code ZonedDateTime.now} /
 *       {@code Instant.now}（本单补的三个兄弟 —— <b>按族补齐，不按"我见过哪个"</b>）·
 *       {@code Clock.system} / {@code System.currentTimeMillis}（非 {@code .now(} 形态的墙钟入口）·
 *       {@code "Asia/Shanghai"} / {@code ZoneId.of("Asia/Shanghai")} / {@code ZoneId.systemDefault}
 *       （时区真值面）；</li>
 *   <li><b>已核查、有意不覆盖</b>（{@link Disposition#OUT_OF_SCOPE}）：{@code System.nanoTime()} /
 *       {@code new Date()} / {@code Calendar.getInstance()} / {@code TimeZone.getTimeZone(..)} /
 *       {@code ZoneOffset.ofHours(..)} —— 逐条理由见 {@link #SPELLINGS}；它们今天在测试树里
 *       <b>现取 0 处</b>，出现 ⇒ 判据红（要求<b>人工回来裁定</b>，不是自动判违规）；</li>
 *   <li><b>普查面自动发现</b>：{@code <大写类型>.now(} 的<b>接收者名</b>逐个现取 —— 出现一个没裁过的
 *       兄弟拼写（如 {@code YearMonth.now(}）⇒ 红。<b>这条不需要人先想到它</b>，是"族级"的机械兜底。</li>
 * </ul>
 *
 * <h2>判别口径：什么算「当业务基准用」（危险），什么算「量时长」（合法）</h2>
 *
 * <ol>
 *   <li><b>当业务基准用 ⇒ 判红</b> = 读数的<b>日历/时钟投影</b>（{@link #BUSINESS_BASIS_PROJECTIONS}）：
 *       {@code .toLocalDate()} / {@code .toLocalTime()} / {@code .toLocalDateTime()} / {@code .getDayOf*}
 *       / {@code .getHour()} / {@code .getMinute()} / {@code .getSecond()} / {@code .getOffset()} /
 *       {@code .toEpochDay()} / {@code .atZone(} / {@code .atOffset(}。理由：{@code OffsetDateTime} /
 *       {@code ZonedDateTime} / {@code Instant} 的 {@code now()} 读到的<b>时刻与任何一只钟都相同</b>
 *       （这一点与 {@code LocalDate.now()} <b>不同</b> —— 如实登记），能「差一天」的只可能是它的
 *       <b>时区投影</b>，而投影用的正是 JVM 默认时区（CI runner = UTC，业务 = +08）。
 *       <b>判定的是投影，不是拼写本身。</b>同一个读数的<b>绑定名</b>在别处的投影也算
 *       （{@code OffsetDateTime now = OffsetDateTime.now();} … {@code now.toLocalDate()}）；
 *       这一层是<b>文件级</b>的（不解析作用域）⇒ 属保守方向（宁多判一次，不漏）。</li>
 *   <li><b>量时长 ⇒ 不判红</b> = 读数只作「与另一只读数比长短」的<b>端点</b>：闭区间
 *       {@code isBetween(a, b)} / {@code isAfter} / {@code isBefore} / 相减 {@code -} /
 *       {@code Duration.between(..)}；被测系统的输出只由「两个读数之差」决定 ⇒ 与"今天是哪天"无关。
 *       逐字沿用同族守卫 {@code tests/unit_ci_workflows/time_flaky_guard.py} 登记的那一格：
 *       「{@code const start = Date.now()} … {@code expect(Date.now() - start).toBeGreaterThanOrEqual(x)}
 *       = <b>不红</b>」。</li>
 *   <li><b>夹具数据 ⇒ 不判红</b> = 读数只作<b>输入</b>喂给被测系统（构造器 / 设值 / 方法实参）且不投影 ——
 *       被测系统的输出由那份输入唯一决定，墙钟漂移不改变判据（同 {@code time_flaky_guard} 的
 *       「{@code created_at: new Date().toISOString()} 塞进夹具 = 不在此列」）。</li>
 * </ol>
 *
 * <p><b>表示层投影</b>（{@code .toString()} / {@code .format(}）另判一格：<b>只有在断言语句里</b>才算危险
 * （期望值取自墙钟的文本 —— 同 {@code time_flaky_guard} 的形态 A「值流进了 {@code expect(...)} 的实参区间」）；
 * 在夹具实参位置不算（仓内现存那处正是这种：{@code AfterSalesIntegrationTest} 把 {@code now().toString()}
 * 喂给 mock 的响应体，断言只看状态字段）。</p>
 *
 * <h2>现存 5 处逐条判定（{@code ProcessingOrderServiceTest}，本单<b>不改它们的语义</b>）</h2>
 *
 * <p>🔴 计时括号改成注入时钟是<b>语义替换</b>，不是修复 ⇒ 本单不为了判据变绿去改它们。
 * 逐处（锚用<b>可检索文本</b>而不是行号 —— 行号几分钟就腐烂）：</p>
 * <ol>
 *   <li>{@code beforeIssue} / {@code afterIssue}（{@code updateStatusMainChain}）：<b>计时括号</b> ——
 *       两个读数是 {@code isBetween(beforeIssue, afterIssue)} 的两个端点，量的是「这次调用发生在哪一刻」；
 *       断言对象是<b>生产算出来的</b> {@code issuedAt}。⇒ 判定<b>合法</b>，处置 = <b>不改</b>；</li>
 *   <li>{@code beforeStart} / {@code afterStart}（同一条用例的 start 段）：同上（端点是
 *       {@code inProcessingAt} 的闭区间）⇒ 合法，不改；</li>
 *   <li>{@code poolGroupsByMaterialAndWarnsOverdueOrders} 里的 {@code java.time.OffsetDateTime now}：
 *       <b>夹具数据</b> —— 读数只用于造 {@code createdAt}（{@code now.minusHours(40/30/2/1)}），
 *       断言侧全部是<b>时长</b>读数（{@code waitHours} / {@code maxWaitHours} / 序）⇒ 合法，不改。</li>
 * </ol>
 * <p>⇒ 5 处在新禁列下的<b>原始命中是 5 次</b>（现取读数，判据 =
 * {@link #fixedClassesRawCensusIsReadLiveAndJudgedClean()}），<b>形态判定 = 全部合法</b>
 * （2 处计时括号 × 各 2 个读数 + 1 处夹具数据）⇒ 门禁命中 0。反过来说：这 5 处这次之所以"没被判红"，
 * 是<b>逐处形态判定</b>的结果，不是"新针没生效"（判别力自证见
 * {@link #familyRulesSeparateBusinessBasisFromDurationBrackets()}）。</p>
 *
 * <h2>明确的边界（<b>不要把本守卫读成覆盖面更大</b>）</h2>
 *
 * <ul>
 *   <li><b>只覆盖 Java 测试源码</b>（{@code backend/admin-api/src/test/java} 下的 {@code *.java}）：
 *       {@code src/main} 由 {@code BusinessClockSourceGuardTest} 管；前端 JS/TS 由
 *       {@code tests/unit_ci_workflows/time_flaky_guard.py} 管（形态不同 —— {@code new Date()} 才是那边的针）；</li>
 *   <li><b>非时间型的环境依赖一个字都看不见</b>：JVM 默认<b>地区</b> / <b>字符集</b>
 *       （{@code Locale.getDefault()} / {@code Charset.defaultCharset()}）、系统属性、文件系统大小写 ——
 *       它们与「两个今天」<b>同族</b>（"本机对了、runner 不对"），但不在本守卫射程；</li>
 *   <li><b>硬编码绝对日期</b>（{@code LocalDate.of(2026, 10, 1)}）不在禁列：它只有在「当业务日基准用」
 *       时才是炸弹，而「纯数据」（格式化断言）与它静态不可区分 ⇒ 只做普查不做门禁
 *       （同 {@code time_flaky_guard} 的形态 B 处置：把「为什么不假红」变成可复现读数）；</li>
 *   <li><b>不带时区投影的相等比较看不见</b>：{@code assertThat(x).isEqualTo(OffsetDateTime.now())} 两侧
 *       <b>时刻相同</b>，差的是<b>偏移表示</b>而不是时刻，而"生产侧是否也用了默认偏移"静态判不出来
 *       （今天现取 0 处）；如实登记为覆盖外，<b>不粉饰</b>；</li>
 *   <li><b>跨进程 / 库侧的墙钟看不见</b>：SQL 的 {@code now()} / {@code CURRENT_DATE}、DB 服务器时钟、
 *       {@code BusinessClock} 之外的时钟源 —— 本守卫只读源码文本；</li>
 *   <li><b>为什么不在全仓按字面量扫</b>：会命中<b>注释 / 历史留档 / 叙述句</b> ⇒ 判据被自己的文案喂红
 *       （{@code migao-dev-flow} §23.4 T2）。本仓现成例子：{@code LocalDate.now(} 在<b>非 Java</b> 文件里
 *       就有命中 —— {@code tests/agent_eval/eval_cases.py}、{@code docs/testing/mibao-verification-cases.md}、
 *       {@code .github/cases/misc.yml}（正是<b>登记本守卫</b>的那条用例的说明文字）⇒ 全仓扫描会把
 *       <b>文档</b>数成违规。⇒ 语料 = <b>剥注释后的 Java 测试源码</b>，且按具名排除两个守卫文件
 *       （§23.8 B1：判据语料必须排除判据自身）。</li>
 * </ul>
 */
class BusinessClockTestSourceGuardTest {

    /** 一条禁则 = needle + **判定形态** + 为什么它是缺陷（与 {@link BusinessClockSourceGuardTest} 同一组语义）。 */
    private record Rule(String name, String needle, Shape shape, String why) {
    }

    /**
     * 判定的**形态**：既有 5 条是 {@link #ANYWHERE}（任何一次出现都算命中，语义<b>冻结</b>）；
     * 本单（issue #5689）按族补齐的兄弟拼写是 {@link #AS_BUSINESS_BASIS}（只有「当业务基准用」才算命中）。
     *
     * <p>为什么必须分两种：既有 5 条的针（{@code LocalDate.now(} 等）本身就是「取今天」的拼写，一律判红是对的；
     * 而 {@code OffsetDateTime.now(} 在测试树里的语料**绝大多数是夹具数据与计时括号**
     * ⇒ 一律判红 = 把病治反（issue #5689 ① 明令禁止）⇒ 新针必须带形态判定。</p>
     */
    private enum Shape {
        /** 任何一次出现都算命中（既有 5 条，**冻结**：不许放宽、不许改名、不许删）。 */
        ANYWHERE,
        /** 只有「当业务基准用」的形态才算命中（计时括号 / 夹具数据 / 表示层投影放行）。 */
        AS_BUSINESS_BASIS
    }

    private static final List<Rule> FORBIDDEN = List.of(
            new Rule("无参 LocalDate.now()", "LocalDate.now(", Shape.ANYWHERE,
                    "取 JVM 默认时区（生产容器 / CI runner = UTC）⇒ 与业务日（+08）在 UTC 16:00–24:00 差一天"),
            new Rule("无参 LocalDateTime.now()", "LocalDateTime.now(", Shape.ANYWHERE,
                    "同上；与 +08 日零点相减算 TTL 时差 8 小时"),
            new Rule("无参 LocalTime.now()", "LocalTime.now(", Shape.ANYWHERE,
                    "同上（业务日/营业时段的比较基准）"),
            new Rule("业务时区字面量", "\"Asia/Shanghai\"", Shape.ANYWHERE,
                    "时区真值只许出现在 BusinessClock 一处（测试里再写一份 = 两处口径，迟早分叉）"),
            new Rule("ZoneId.of 业务时区", "ZoneId.of(\"Asia/Shanghai\")", Shape.ANYWHERE,
                    "同上（用 BusinessClock.BUSINESS_ZONE）"),
            // ── 族级补齐（issue #5689）：按**族**枚举，不按事故现场的拼写 ──────────────────
            new Rule("无参 OffsetDateTime.now()", "OffsetDateTime.now(", Shape.AS_BUSINESS_BASIS,
                    "**事故现场的拼写**（#5679 修复前的 PoolBoardUrgencyTest）。读数本身与任何一只钟"
                            + "**同一时刻**，危险的是它的**时区投影**（用 JVM 默认偏移：CI = UTC / 业务 = +08）"
                            + "—— 判别口径见类注释"),
            new Rule("无参 ZonedDateTime.now()", "ZonedDateTime.now(", Shape.AS_BUSINESS_BASIS,
                    "同上（带默认**时区**而不是偏移）；拼写不同、机制同一个 —— 按族补齐就是为了它这种"
                            + "「今天 0 处但迟早有人写」的兄弟"),
            new Rule("无参 Instant.now()", "Instant.now(", Shape.AS_BUSINESS_BASIS,
                    "绝对时刻，**本身与时区无关**（如实登记：这是它与两个兄弟唯一的差别）⇒ 入禁列的理由 ="
                            + "① 它的 `.atZone(` / `.atOffset(` 投影用的就是 JVM 默认时区；"
                            + "② 测试里的「现在」只许来自 BusinessClock（两处口径迟早分叉）"),
            new Rule("自造系统时钟", "Clock.system", Shape.ANYWHERE,
                    "与 src/main 侧守卫同一针：Clock 必须由 BusinessClock 单点创建 ——"
                            + " Clock.systemDefaultZone() / Clock.systemUTC() / Clock.system(zone) 三个拼写都落在这里；"
                            + "测试要钉时刻只用 Clock.fixed(..)"),
            new Rule("默认时区 ZoneId", "ZoneId.systemDefault(", Shape.ANYWHERE,
                    "JVM 默认时区就是本缺陷族的口径来源（禁则 4/5 的族级意图：时区真值只许出现在 BusinessClock 一处）"),
            new Rule("墙钟毫秒读数", "System.currentTimeMillis(", Shape.AS_BUSINESS_BASIS,
                    "与 Instant.now() 同族（绝对时刻）；投影面（`.atZone(` / `Instant.ofEpochMilli(..)` 之后再投影）"
                            + "由本类的形态判据覆盖"));

    /** 本单（issue #5689）按族补齐的禁则名 —— 判别力由 {@link #familyRulesSeparateBusinessBasisFromDurationBrackets()} 两侧自证。 */
    private static final List<String> FAMILY_RULES_ADDED_HERE = List.of(
            "无参 OffsetDateTime.now()", "无参 ZonedDateTime.now()", "无参 Instant.now()",
            "自造系统时钟", "默认时区 ZoneId", "墙钟毫秒读数");

    /** 本表的一条裁定：入禁列，还是已核查后**有意不覆盖**。 */
    private enum Disposition {
        /** 由 {@link #FORBIDDEN} 里同 needle 的规则判（裁定 ≡ 实现由判据钉住）。 */
        FORBIDDEN,
        /** 已逐条核查、本守卫**看不见**它 —— 出现与否被冻结（出现 ⇒ 红 ⇒ 人工回来裁定）。 */
        OUT_OF_SCOPE
    }

    /** 一条拼写的裁定。{@code needle} 同时是**普查针**（剥注释 + 掩字符串后统计）。 */
    private record Spelling(String needle, Disposition disposition, boolean presentInTree, String why) {
    }

    /**
     * 🔴 <b>族级覆盖清单</b>（issue #5689）：本守卫<b>声称覆盖</b>的「测试里的业务时间读取点 / 时区真值」
     * 的<b>全部</b>拼写，逐条具名 + 逐条裁定。它治的结构是「<b>意图是族级的、实现是点名的</b> ⇒ 兄弟拼写漏网」。
     *
     * <p>四条机械判据（{@link #manifestAndForbiddenRulesCannotDrift()} /
     * {@link #everySpellingInTheTreeIsAdjudicated()} / {@link #outOfScopeSpellingsPresenceIsFrozen()}）：</p>
     * <ol>
     *   <li><b>未登记即红（实例判据）</b>：{@code <大写类型>.now(} 的<b>接收者名</b>逐个现取，必须在本表具名 ——
     *       出现一个没裁过的兄弟（如 {@code YearMonth.now(}）⇒ 红，<b>不需要人先想到它</b>；</li>
     *   <li><b>裁定 ≡ 实现</b>：裁定为 {@link Disposition#FORBIDDEN} 的 needle 集合必须与 {@link #FORBIDDEN}
     *       里 needle 的集合<b>逐字相等</b> —— 只改表或只改规则表 ⇒ 必红（防「登记了但其实没判」）；</li>
     *   <li><b>条目不许陈旧</b>：{@link Disposition#OUT_OF_SCOPE} 的条目冻结<b>「树里今天有没有它」</b> ——
     *       登记为 0 处而现取 &gt; 0 ⇒ 红（本守卫看不见的墙钟入口出现了，必须人工回来裁定）；
     *       登记为「有」而现取 0 ⇒ 红（销账）；</li>
     *   <li><b>不许空跑</b>：普查面必须现取非空且真的读到本表里已入禁列的拼写（正则/路径失效 ⇒ 红）。</li>
     * </ol>
     */
    private static final List<Spelling> SPELLINGS = List.of(
            // ── 读取点：本守卫**判**的（入禁列）────────────────────────────────────────
            new Spelling("LocalDate.now(", Disposition.FORBIDDEN, true,
                    "既有禁则 1（语义冻结）：取 JVM 默认时区的**今天**"),
            new Spelling("LocalDateTime.now(", Disposition.FORBIDDEN, true,
                    "既有禁则 2（语义冻结）：JVM 默认时区的墙上时间"),
            new Spelling("LocalTime.now(", Disposition.FORBIDDEN, true,
                    "既有禁则 3（语义冻结）：营业时段/早晚判断的基准"),
            new Spelling("OffsetDateTime.now(", Disposition.FORBIDDEN, true,
                    "本单 ① 的**事故现场拼写**；按形态判（计时括号 / 夹具数据放行）"),
            new Spelling("ZonedDateTime.now(", Disposition.FORBIDDEN, false,
                    "本单 ① 按族补齐：今天 0 处，但**按族枚举**意味着它必须在禁列里 —— 否则下一次漏网的就是它"),
            new Spelling("Instant.now(", Disposition.FORBIDDEN, false,
                    "本单 ①；src/main 侧守卫把它当「绝对时刻」台账处理，测试侧按形态判（投影才判红）"),
            new Spelling("Clock.system", Disposition.FORBIDDEN, false,
                    "非 `.now(` 形态的**时钟来源**：Clock.systemDefaultZone() / Clock.systemUTC() / Clock.system(zone)"),
            new Spelling("System.currentTimeMillis(", Disposition.FORBIDDEN, true,
                    "非 `.now(` 形态的墙钟读数（毫秒）；投影面经 `Instant.ofEpochMilli(..)` / `new Date(..)`"),
            new Spelling("ZoneId.systemDefault(", Disposition.FORBIDDEN, false,
                    "时区真值面：显式写出「JVM 默认时区」—— 禁则 4/5 的族级意图"),
            new Spelling("\"Asia/Shanghai\"", Disposition.FORBIDDEN, true,
                    "既有禁则 4（语义冻结）：业务时区字面量只许出现在 BusinessClock"),
            new Spelling("ZoneId.of(\"Asia/Shanghai\")", Disposition.FORBIDDEN, true,
                    "既有禁则 5（语义冻结）：同上"),
            // ── 已核查、有意不覆盖（出现 ⇒ 红 ⇒ 人工裁定）────────────────────────────
            new Spelling("System.nanoTime(", Disposition.OUT_OF_SCOPE, true,
                    "只量时长（单调钟），没有「今天是哪天」的投影面 —— **出现即提醒**（本表第一次因它判红，"
                            + "登记 = 现取事实快照，issue #6237）。现取 1 个文件、均为**计时括号**（不是业务基准读取点）："
                            + "`InboundPostConcurrentRealDbTest` 用它给 4 个并发过账请求各记一对 `[start,end]` 纳秒读数，"
                            + "供「真重叠」证据（逐对区间求交 + 并集跨度 vs 各历时之和）——与 "
                            + "`familyRulesSeparateBusinessBasisFromDurationBrackets` 认定的「计时括号不误伤」同一族；"
                            + "复核口径见该文件 `printOverlapEvidence(..)`（换措辞 / 挪作业务基准用时必须回来复核）"),
            new Spelling("new Date()", Disposition.OUT_OF_SCOPE, false,
                    "空实参 `new Date()` 是墙钟读数（`new Date(x)` 是解析给定时刻，不算）；不纳入的理由："
                            + "`java.util.Date` 本身**没有时区投影面**，差一天要经 `.getHours()` / `.getDay()` /"
                            + " `SimpleDateFormat` 才出现，而它们在 Java 测试树里现取 0 处；且它是**前端**守卫"
                            + " time_flaky_guard 的主形态（纯 JS、零依赖）⇒ 不把两边的针混族。"
                            + "⚠️ 它一旦出现，本守卫**判不了**它（如实登记）"),
            new Spelling("Calendar.getInstance(", Disposition.OUT_OF_SCOPE, false,
                    "默认时区日历；投影面 = `.get(Calendar.DAY_OF_MONTH)` 这类 —— 今天 0 处，未纳入（出现即提醒）"),
            new Spelling("TimeZone.getTimeZone(", Disposition.OUT_OF_SCOPE, false,
                    "时区真值的另一种来源（今天 0 处）；未纳入（出现即提醒）"),
            new Spelling("ZoneOffset.ofHours(", Disposition.OUT_OF_SCOPE, true,
                    "「UTC 日边界贴 +08 标签」那个更差的拼写在测试侧的形态。**已核查 = 树里有**（本表第一次跑就"
                            + "因此判红 ⇒ 这条冻结判据是活的）：均在 BusinessClockTest —— ① 断言业务时区偏移 = +08 的"
                            + "**期望值**；② 复现该坏拼写的**红证夹具**。⇒ 它们不是产生「两个今天」的读取点，"
                            + "本守卫不判它；出现 / 消失都要求回来复核（登记 = 现取事实快照）"));

    /**
     * 判据语料里**排除**的文件（具名，带理由）—— 排除的是「守卫自己的 needle 字面量」，
     * <b>不是</b>「这些文件的违规豁免」（它们自己有没有违规，由各自的门禁管）。
     */
    private static final Map<String, String> SELF_EXCLUDED = Map.of(
            "com/migao/admin/time/BusinessClockSourceGuardTest.java",
            "src/main 侧守卫：类里就是自己的 needle 字面量与坏样本串（规则表被数成违规 = §23.8 B1）",
            "com/migao/admin/time/BusinessClockTestSourceGuardTest.java",
            "本文件（测试侧守卫）：同上，且台账/红证样本里也有 needle 字面量");

    /**
     * 存量台账（键 = {@code <相对 src/test/java 的路径>|<规则名>}，值 = 该文件里允许出现的次数）。
     *
     * <p>🔴 <b>只许缩短</b>：① 不在台账里的新命中 ⇒ 红；② 计数超出 ⇒ 红；
     * ③ 台账里记着、现在<b>不再命中</b>的条目 ⇒ 红（必须销账）。
     * ⚠️ 计数是<b>现取</b>的读数，不写死历史数字；每次销账都要先跑
     * {@code python3 -c …} 或本类失败信息里的现取清单。</p>
     *
     * <p><b>修法（全部同一招）</b>：把 {@code LocalDate.now()} 换成注入的
     * {@code BusinessClock}（{@code @Spy private BusinessClock businessClock = new BusinessClock();}
     * + {@code @InjectMocks} 会注入进被测服务）⇒ 夹具与生产同源同区。
     * 本单已按此修掉三个类（见 {@link #theClassesFixedByThisChangeAreClean()}）。</p>
     */
    private static final Map<String, Integer> LEDGER = Map.ofEntries(
            // 2026-10-02（issue #5955）销账**一条残留**（只许缩短）：`BriefingControllerTest` 全改用注入的
            // `BusinessClock`（`businessClock.today()`）⇒ 该类归零，台账条目删除。
            // `DailyBriefingServiceTest` 的 ×2 **保留**：现存两处是带 `BusinessClock.BUSINESS_ZONE` 的
            // 显式时区写法（`LocalDate.now(BusinessClock.BUSINESS_ZONE)`，本类规则 needle 是 `LocalDate.now(`）
            // —— 它们不是「裸 now()」，但仍在 needle 射程内 ⇒ 台账照旧登记。
            Map.entry("com/migao/admin/controller/BusinessFlowIntegrationTest.java|无参 LocalDateTime.now()", 1),
            Map.entry("com/migao/admin/controller/UploadControllerTest.java|无参 LocalDateTime.now()", 1),
            Map.entry("com/migao/admin/service/AutoBatchDispatchTest.java|无参 LocalDate.now()", 13),
            Map.entry("com/migao/admin/service/AutoBatchDueScanRealDbTest.java|无参 LocalDate.now()", 4),
            Map.entry("com/migao/admin/service/AutoBatchDueScanServiceTest.java|无参 LocalDate.now()", 9),
            Map.entry("com/migao/admin/service/AutoBatchMountPointTest.java|无参 LocalDate.now()", 2),
            Map.entry("com/migao/admin/service/DailyBriefingServiceTest.java|无参 LocalDate.now()", 2),
            Map.entry("com/migao/admin/service/DailyBriefingServiceTest.java|业务时区字面量", 1),
            Map.entry("com/migao/admin/service/DailyBriefingServiceTest.java|ZoneId.of 业务时区", 1),
            Map.entry("com/migao/admin/time/BusinessClockTest.java|无参 LocalDate.now()", 2),
            Map.entry("com/migao/admin/time/BusinessClockTest.java|业务时区字面量", 1),
            Map.entry("com/migao/admin/time/BusinessClockTest.java|ZoneId.of 业务时区", 1));

    /** 本单修掉的三个测试类（实例判据：必须在扫描面内且命中为 0）。 */
    private static final List<String> FIXED_BY_THIS_CHANGE = List.of(
            "com/migao/admin/service/PoolBoardUrgencyTest.java",
            "com/migao/admin/service/InboundOrderServiceTest.java",
            "com/migao/admin/service/ProcessingOrderServiceTest.java");

    // ── 扫描器（纯函数，便于注入式红证）────────────────────────────────────────

    /** 剥掉 `//` 与 `/* *\/` 注释（字符串字面量内不剥——needle 本身可能就在字符串里）。 */
    static String stripComments(String src) {
        StringBuilder out = new StringBuilder(src.length());
        int i = 0;
        int n = src.length();
        while (i < n) {
            char c = src.charAt(i);
            // 🔴 认引号（issue #5689 实测的修正）：字符串/字符字面量内的 `//` **不是**注释 ——
            //    `"jdbc:postgresql://…"` / `"https://…"` 这类字面量曾把**行尾整段**吃掉 ⇒ 行尾的时间
            //    读取点被判据看不见（族级针实测少 8 处）。既有 5 条禁则的逐针命中数实测**不受影响**
            //    ⇒ 台账 40 处 / 13 条的语义未变（§23.6：注解是读数不是结论，这里给的是实跑读数）。
            if (c == '"' || c == '\'') {
                out.append(c);
                i++;
                while (i < n) {
                    char inner = src.charAt(i);
                    out.append(inner);
                    i++;
                    if (inner == '\\') {
                        if (i < n) {
                            out.append(src.charAt(i));
                            i++;
                        }
                        continue;
                    }
                    if (inner == c) {
                        break;
                    }
                }
                continue;
            }
            if (src.startsWith("/*", i)) {
                int j = src.indexOf("*/", i + 2);
                i = (j < 0) ? n : j + 2;
                continue;
            }
            if (src.startsWith("//", i)) {
                int j = src.indexOf('\n', i);
                i = (j < 0) ? n : j;
                continue;
            }
            out.append(c);
            i++;
        }
        return out.toString();
    }

    /**
     * 把字符串/字符字面量的**内容**换成等长空白（保留 {@code \n}）—— 供**形态判定**用。
     *
     * <p>为什么形态判定要掩字符串、而既有 5 条禁则<b>不掩</b>：既有禁则的 needle 本身可能就是字符串
     * （{@code "Asia/Shanghai"}）且语义<b>冻结</b>不许放宽；而形态判定问的是「这里是不是一个**读取点**」——
     * 判据语料里的「拼写样本文本」（如扫描器自己的坏样本串）不是读取点。</p>
     */
    static String maskLiterals(String code) {
        char[] out = code.toCharArray();
        int i = 0;
        int n = code.length();
        while (i < n) {
            char c = code.charAt(i);
            if (c != '"' && c != '\'') {
                i++;
                continue;
            }
            int j = i + 1;
            while (j < n) {
                if (code.charAt(j) == '\\') {
                    j += 2;
                    continue;
                }
                if (code.charAt(j) == c) {
                    break;
                }
                j++;
            }
            for (int k = i + 1; k < Math.min(j, n); k++) {
                if (out[k] != '\n') {
                    out[k] = ' ';
                }
            }
            i = Math.min(j, n - 1) + 1;
        }
        return new String(out);
    }

    /** {@code <大写类型>.now(} 的**接收者名**普查针（变量名 {@code foo.now(} 不在面内 —— 那是方法调用，不是时钟拼写）。 */
    private static final Pattern NOW_RECEIVER = Pattern.compile("\\b([A-Z][A-Za-z0-9_]*)\\s*\\.\\s*now\\s*\\(");

    /** 「当业务基准用」的判据 = 读数的**日历/时钟投影**（把时刻变成「今天是哪天 / 现在几点 / 偏移多少」）。 */
    private static final Set<String> BUSINESS_BASIS_PROJECTIONS = Set.of(
            "toLocalDate", "toLocalTime", "toLocalDateTime",
            "getDayOfMonth", "getDayOfWeek", "getDayOfYear",
            "getHour", "getMinute", "getSecond", "getOffset",
            "toEpochDay", "atZone", "atOffset");

    /** 表示层投影：读数的**文本**（偏移写进字符串里）—— 只在**断言语句**里才算危险（见类注释）。 */
    private static final Set<String> TEXT_PROJECTIONS = Set.of("toString", "format");

    /** {@code Type N = X.now()} 的绑定名捕获（输入 = 语句起点到读数起点）。 */
    private static final Pattern BINDING_TAIL =
            Pattern.compile("([A-Za-z_][A-Za-z0-9_]*)\\s*=\\s*(?:java\\.time\\.)?$");

    /** 一次扫描的结果：命中（键 = 文件|规则名 → 次数）+ 扫到的文件数 + 族级普查（拼写 → 原始出现次数）。 */
    private record Scan(Map<String, Integer> hits, int files, Map<String, Integer> census) {
    }

    private static Scan scan(Path root) throws IOException {
        Map<String, Integer> hits = new LinkedHashMap<>();
        Map<String, Integer> census = new LinkedHashMap<>();
        int files = 0;
        try (Stream<Path> walk = Files.walk(root)) {
            for (Path file : walk.filter(p -> p.toString().endsWith(".java")).sorted().toList()) {
                files++;
                String rel = root.relativize(file).toString().replace('\\', '/');
                if (SELF_EXCLUDED.containsKey(rel)) {
                    continue;
                }
                String code = stripComments(Files.readString(file, StandardCharsets.UTF_8));
                String shapeView = maskLiterals(code);
                for (Rule rule : FORBIDDEN) {
                    int count = countHits(code, shapeView, rule);
                    if (count > 0) {
                        hits.merge(rel + "|" + rule.name(), count, Integer::sum);
                    }
                }
                Matcher matcher = NOW_RECEIVER.matcher(shapeView);
                while (matcher.find()) {
                    census.merge(matcher.group(1) + ".now(", 1, Integer::sum);
                }
                // 非 `.now(` 形态的登记项（`Clock.system` / `new Date()` / `TimeZone.getTimeZone(` …）逐条现取。
                // ⚠️ 普查按**掩字符串**的视图统计（字符串里的拼写不是读取点）⇒ `"Asia/Shanghai"` 这类 needle
                // 本身在字符串里、其普查值恒 0；它由 ANYWHERE 规则在**未掩**视图上判，不靠普查值。
                for (Spelling spelling : SPELLINGS) {
                    if (spelling.needle().endsWith(".now(")) {
                        continue;   // 已由接收者普查统计 ⇒ 不重复计数
                    }
                    int n = countOccurrences(shapeView, spelling.needle());
                    if (n > 0) {
                        census.merge(spelling.needle(), n, Integer::sum);
                    }
                }
            }
        }
        return new Scan(hits, files, census);
    }

    /** 一条规则在一个文件上的命中数：{@code ANYWHERE} 数出现次数；{@code AS_BUSINESS_BASIS} 只数「当业务基准用」的形态。 */
    private static int countHits(String code, String shapeView, Rule rule) {
        if (rule.shape() == Shape.ANYWHERE) {
            return countOccurrences(code, rule.needle());
        }
        int count = 0;
        int idx = shapeView.indexOf(rule.needle());
        while (idx >= 0) {
            if (isBusinessBasisUse(shapeView, idx, rule.needle())) {
                count++;
            }
            idx = shapeView.indexOf(rule.needle(), idx + rule.needle().length());
        }
        return count;
    }

    /** 一次出现是否算「**当业务基准用**」（危险）—— 判别口径见类注释（三条形态 + 表示层一格）。 */
    static boolean isBusinessBasisUse(String code, int idx, String needle) {
        List<String> chain = callChain(code, matchParen(code, idx + needle.length() - 1));
        if (chain.stream().anyMatch(BUSINESS_BASIS_PROJECTIONS::contains)) {
            return true;
        }
        boolean inAssertion = code.substring(statementStart(code, idx), idx).stripLeading().startsWith("assert");
        if (inAssertion && chain.stream().anyMatch(TEXT_PROJECTIONS::contains)) {
            return true;
        }
        String bound = boundName(code, idx);
        if (bound == null) {
            return false;
        }
        for (int i = code.indexOf(bound); i >= 0; i = code.indexOf(bound, i + 1)) {
            if (i > 0 && (Character.isLetterOrDigit(code.charAt(i - 1)) || code.charAt(i - 1) == '_')) {
                continue;
            }
            if (callChain(code, i + bound.length()).stream().anyMatch(BUSINESS_BASIS_PROJECTIONS::contains)) {
                return true;
            }
        }
        return false;
    }

    /** 语句起点（上一个 `;` / `{` / `}` 之后）—— 只用来判「这条读数是不是在断言语句里」。 */
    private static int statementStart(String code, int idx) {
        int i = idx;
        while (i > 0 && code.charAt(i - 1) != ';' && code.charAt(i - 1) != '{' && code.charAt(i - 1) != '}') {
            i--;
        }
        return i;
    }

    /** {@code Type N = X.now()} 的绑定名 {@code N}（没有绑定 ⇒ null）。 */
    private static String boundName(String code, int idx) {
        Matcher matcher = BINDING_TAIL.matcher(code.substring(statementStart(code, idx), idx));
        return matcher.find() ? matcher.group(1) : null;
    }

    /**
     * 从 {@code pos} 起收集连续的 {@code .方法(..)} 的**方法名**（实参文本不收集 —— 否则别的对象的投影
     * 会被误算成这条读数的）。开头先「剥壳」：读数可能被包在别的调用里
     * （{@code Instant.ofEpochMilli(System.currentTimeMillis()).atZone(..)}）。
     */
    private static List<String> callChain(String code, int pos) {
        List<String> methods = new ArrayList<>();
        int i = pos;
        while (i < code.length() && (code.charAt(i) == ')' || Character.isWhitespace(code.charAt(i)))) {
            i++;
        }
        while (i < code.length() && code.charAt(i) == '.') {
            int j = i + 1;
            while (j < code.length() && (Character.isLetterOrDigit(code.charAt(j)) || code.charAt(j) == '_')) {
                j++;
            }
            if (j == i + 1) {
                break;
            }
            methods.add(code.substring(i + 1, j));
            int k = j;
            while (k < code.length() && Character.isWhitespace(code.charAt(k))) {
                k++;
            }
            i = (k < code.length() && code.charAt(k) == '(') ? matchParen(code, k) + 1 : j;
        }
        return methods;
    }

    /** 与 {@code code.charAt(open)}（`(`）配对的 `)` 下标；不平衡时返回末尾。 */
    private static int matchParen(String code, int open) {
        int depth = 0;
        for (int i = open; i < code.length(); i++) {
            char c = code.charAt(i);
            if (c == '(') {
                depth++;
            } else if (c == ')') {
                depth--;
                if (depth == 0) {
                    return i;
                }
            }
        }
        return code.length() - 1;
    }

    private static int countOccurrences(String haystack, String needle) {
        int count = 0;
        int idx = haystack.indexOf(needle);
        while (idx >= 0) {
            count++;
            idx = haystack.indexOf(needle, idx + needle.length());
        }
        return count;
    }

    /** 台账对账：返回**问题清单**（空 = 干净）。纯函数 ⇒ 注入式红证可反复调用。 */
    private static List<String> reconcile(Map<String, Integer> hits, Map<String, Integer> ledger) {
        List<String> problems = new ArrayList<>();
        for (Map.Entry<String, Integer> hit : hits.entrySet()) {
            Integer allowed = ledger.get(hit.getKey());
            if (allowed == null) {
                problems.add("未登记的新命中：" + hit.getKey() + " ×" + hit.getValue()
                        + "（修法：改用注入的 BusinessClock —— 见类注释「修法」）");
            } else if (hit.getValue() > allowed) {
                problems.add("超出台账：" + hit.getKey() + " 实际 ×" + hit.getValue()
                        + " > 允许 ×" + allowed + "（台账只许缩短）");
            }
        }
        for (Map.Entry<String, Integer> entry : ledger.entrySet()) {
            if (!hits.containsKey(entry.getKey())) {
                problems.add("台账残留（现在已不再命中，必须销账）：" + entry.getKey());
            }
        }
        return problems;
    }

    private static Path testRoot() {
        List<Path> candidates = List.of(
                Path.of("src/test/java"),
                Path.of("backend/admin-api/src/test/java"));
        for (Path candidate : candidates) {
            if (Files.isDirectory(candidate)) {
                return candidate;
            }
        }
        throw new AssertionError("找不到 test 源根（candidates=" + candidates + "，cwd="
                + Path.of("").toAbsolutePath() + "）—— 路径漂移不得静默跳过（红）");
    }

    // ── 判据 ────────────────────────────────────────────────────────────────

    @Test
    @DisplayName("测试侧的业务时间读取点不得新增（src/test/java 里除台账外一律判红）")
    void testSourcesReadBusinessTimeOnlyViaBusinessClock() throws IOException {
        Scan scan = scan(testRoot());
        List<String> problems = reconcile(scan.hits(), LEDGER);
        assertThat(problems)
                .as("测试侧出现了**新的**业务时间口径（issue #5651 收口实测：裸 now() 与 +08 业务日"
                        + "在 UTC 16:00–24:00 差一天 ⇒ required 检查每天红 8 小时）。"
                        + "修法 = 注入生产侧同一只 BusinessClock（见类注释）")
                .isEmpty();
        assertThat(scan.files())
                .as("扫到的测试源文件数（现取读数，不写死历史数字）")
                .isGreaterThan(100);
    }

    @Test
    @DisplayName("台账只许缩短：✔未登记即红 ✔超数即红 ✔不再命中即红（必须销账）")
    void ledgerOnlyShrinks() {
        assertThat(reconcile(Map.of("a|无参 LocalDate.now()", 1), Map.of()))
                .as("未登记的新命中必须判红")
                .hasSize(1);
        assertThat(reconcile(Map.of("a|无参 LocalDate.now()", 3), Map.of("a|无参 LocalDate.now()", 2)))
                .as("超出台账必须判红")
                .hasSize(1);
        assertThat(reconcile(Map.of(), Map.of("a|无参 LocalDate.now()", 1)))
                .as("台账残留（不再命中）必须判红 ⇒ 存量只能缩短")
                .hasSize(1);
        assertThat(reconcile(Map.of("a|无参 LocalDate.now()", 1), Map.of("a|无参 LocalDate.now()", 1)))
                .as("命中 == 台账 ⇒ 干净（否则台账退化成恒红）")
                .isEmpty();
    }

    @Test
    @DisplayName("🔴 本单修掉的三个测试类：在扫描面内、且命中为 0（实例判据）")
    void theClassesFixedByThisChangeAreClean() throws IOException {
        Scan scan = scan(testRoot());
        for (String rel : FIXED_BY_THIS_CHANGE) {
            assertThat(Files.isRegularFile(testRoot().resolve(rel)))
                    .as("受管文件必须存在（路径漂移不得静默跳过）：" + rel)
                    .isTrue();
            List<String> hits = scan.hits().entrySet().stream()
                    .filter(e -> e.getKey().startsWith(rel + "|"))
                    .map(Map.Entry::getKey)
                    .toList();
            assertThat(hits)
                    .as(rel + " 仍在用 JVM 默认时区取业务日（CI 的 UTC runner 上，"
                            + "UTC 16:00–24:00 必红 —— 2026-09-26T23:59Z 实测）")
                    .isEmpty();
        }
    }

    @Test
    @DisplayName("每条禁则都能命中一个「已知坏样本」（防 needle 写错后守卫变空断言）")
    void rulesHaveDiscriminatingPower() {
        String bad = """
                class Bad {
                    LocalDate a = LocalDate.now();
                    LocalDateTime b = LocalDateTime.now();
                    LocalTime c = LocalTime.now();
                    String d = "Asia/Shanghai";
                    ZoneId e = ZoneId.of("Asia/Shanghai");
                    OffsetDateTime f = OffsetDateTime.now();
                    ZonedDateTime g = ZonedDateTime.now();
                    Instant h = Instant.now();
                    Clock i = Clock.systemDefaultZone();
                    ZoneId j = ZoneId.systemDefault();
                    long k = System.currentTimeMillis();
                }
                """;
        String code = stripComments(bad);
        for (Rule rule : FORBIDDEN) {
            assertThat(countOccurrences(code, rule.needle()))
                    .as("禁则「" + rule.name() + "」在坏样本上命中 0 次 ⇒ needle 写错了（守卫是空断言）")
                    .isGreaterThan(0);
        }
        assertThat(stripComments("// LocalDate.now()\n/* LocalTime.now() */\n"))
                .as("注释里的提及不得被读成违规（§23.4 T2：判据被自己的文案喂红）")
                .doesNotContain("now(");
    }

    @Test
    @DisplayName("🔴 族禁则两侧自证：当业务基准用 ⇒ 命中；计时括号 / 夹具数据 ⇒ 不命中（判别力 + 不误伤）")
    void familyRulesSeparateBusinessBasisFromDurationBrackets() {
        Map<String, String> bad = Map.of(
                "无参 OffsetDateTime.now()",
                "LocalDate today = OffsetDateTime.now().toLocalDate();",
                "无参 ZonedDateTime.now()",
                "LocalTime t = ZonedDateTime.now().toLocalTime();",
                "无参 Instant.now()",
                "LocalDate d = Instant.now().atOffset(ZoneOffset.UTC).toLocalDate();",
                "自造系统时钟",
                "Clock c = Clock.systemDefaultZone();",
                "默认时区 ZoneId",
                "ZoneId z = ZoneId.systemDefault();",
                "墙钟毫秒读数",
                "LocalDate d = Instant.ofEpochMilli(System.currentTimeMillis()).atZone(z).toLocalDate();");
        Map<String, String> legal = Map.of(
                "无参 OffsetDateTime.now()", """
                        OffsetDateTime beforeIssue = OffsetDateTime.now();
                        processingOrderService.updateStatus("po-1", issue, TENANT, "u1");
                        OffsetDateTime afterIssue = OffsetDateTime.now();
                        assertThat(captor.getValue().getIssuedAt()).isBetween(beforeIssue, afterIssue);
                        """,
                "无参 ZonedDateTime.now()", """
                        ZonedDateTime start = ZonedDateTime.now();
                        svc.run();
                        assertThat(Duration.between(start, ZonedDateTime.now()).toMillis()).isGreaterThanOrEqualTo(0L);
                        """,
                "无参 Instant.now()", """
                        Instant t0 = Instant.now();
                        svc.run();
                        assertThat(Duration.between(t0, Instant.now()).toMillis()).isGreaterThanOrEqualTo(0L);
                        """,
                "自造系统时钟",
                "Clock c = Clock.fixed(Instant.parse(\"2026-09-27T00:00:00Z\"), ZoneOffset.UTC);",
                "默认时区 ZoneId",
                "ZoneId z = BusinessClock.BUSINESS_ZONE;",
                "墙钟毫秒读数", """
                        long diffMs = expiration.getTime() - System.currentTimeMillis();
                        when(m.getExpiration()).thenReturn(new java.util.Date(System.currentTimeMillis() + 600000));
                        """);

        assertThat(bad.keySet())
                .as("坏样本必须覆盖本单按族补齐的每一条（漏一条 ⇒ 该条没有判别力自证）")
                .containsExactlyInAnyOrderElementsOf(FAMILY_RULES_ADDED_HERE);

        List<String> problems = new ArrayList<>();
        for (Rule rule : FORBIDDEN) {
            String badSample = bad.get(rule.name());
            if (badSample == null) {
                continue;   // 既有 5 条由 rulesHaveDiscriminatingPower 用 needle 级坏样本自证
            }
            if (countHits(badSample, badSample, rule) == 0) {
                problems.add("禁则「" + rule.name() + "」在**当业务基准用**的坏样本上命中 0 次"
                        + "（needle 写错，或形态判据退化成空断言）：" + badSample);
            }
            String legalSample = legal.get(rule.name());
            if (countHits(legalSample, legalSample, rule) > 0) {
                problems.add("禁则「" + rule.name() + "」把**合法形态**（计时括号 / 夹具数据 / 业务时钟常量）"
                        + "也判红了 —— 那是把病治反（issue #5689 ①）：" + legalSample);
            }
        }
        assertThat(problems)
                .as("新族禁则必须**两侧都自证**：坏样本红 + 合法样本绿。只证一侧 = 分不清「没误伤」与「判别力为零」")
                .isEmpty();
    }

    @Test
    @DisplayName("对照读数：**只改注释**不会让族禁则红（红证命中的是「日历投影」判定分支，不是锚失配）")
    void commentOnlyMentionsAreNotViolations() {
        Rule rule = FORBIDDEN.stream().filter(r -> r.needle().equals("OffsetDateTime.now(")).findFirst()
                .orElseThrow(() -> new AssertionError("禁则表里找不到 OffsetDateTime.now(（改名 ⇒ 红）"));
        String commented = """
                class C {
                    // LocalDate today = OffsetDateTime.now().toLocalDate();
                    /* LocalTime t = ZonedDateTime.now().toLocalTime(); */
                }
                """;
        assertThat(countHits(commented, maskLiterals(commented), rule))
                .as("不剥注释时的命中（证明 needle 与形态判定**确实**能命中这条链）")
                .isGreaterThan(0);
        String stripped = stripComments(commented);
        assertThat(countHits(stripped, maskLiterals(stripped), rule))
                .as("**只改注释**的对照读数：剥注释后命中必须是 0 —— 证明红证命中的是「日历投影」判定分支，"
                        + "而不是本会话实测过的另一种形态（只改注释也能让**锚/计数型**判据红）")
                .isZero();
    }

    @Test
    @DisplayName("🔴 族级覆盖清单的裁定 ≡ 实现（只改表 / 只改 FORBIDDEN ⇒ 必红）")
    void manifestAndForbiddenRulesCannotDrift() {
        Set<String> declared = SPELLINGS.stream()
                .filter(s -> s.disposition() == Disposition.FORBIDDEN)
                .map(Spelling::needle)
                .collect(Collectors.toCollection(LinkedHashSet::new));
        Set<String> implemented = FORBIDDEN.stream()
                .map(Rule::needle)
                .collect(Collectors.toCollection(LinkedHashSet::new));
        assertThat(declared)
                .as("族级覆盖清单里裁定为 FORBIDDEN 的 needle 必须与 FORBIDDEN 的 needle 集合**逐字相等**："
                        + "「登记了但没判」（假覆盖）与「判了但没登记」（漏登记）都红")
                .isEqualTo(implemented);
        assertThat(FORBIDDEN.stream().map(Rule::name).toList())
                .as("本单按族补齐的六条禁则必须真的在 FORBIDDEN 里（否则它们的判别力自证根本不跑）")
                .containsAll(FAMILY_RULES_ADDED_HERE);
    }

    @Test
    @DisplayName("🔴 实例判据：测试树里现取的每个 <大写类型>.now( 拼写都必须已被裁定（未登记的新兄弟 ⇒ 红）")
    void everySpellingInTheTreeIsAdjudicated() throws IOException {
        Scan scan = scan(testRoot());
        Set<String> adjudicated = SPELLINGS.stream()
                .map(Spelling::needle)
                .collect(Collectors.toCollection(LinkedHashSet::new));
        Set<String> live = scan.census().keySet().stream()
                .filter(k -> k.endsWith(".now("))
                .collect(Collectors.toCollection(TreeSet::new));
        assertThat(live)
                .as("普查面（现取）：测试树里出现过的 <大写类型>.now( 拼写 = %s。出现一个没裁过的兄弟即红 ——"
                        + "处置 = 在 SPELLINGS 具名登记并裁定（入禁列 / 有意不覆盖 + 理由）", live)
                .isSubsetOf(adjudicated);
        assertThat(live)
                .as("不许空跑：本守卫声称覆盖「测试里的业务时间读取点」，普查却一个都没读到 ⇒ 正则/路径失效（红）")
                .contains("OffsetDateTime.now(");
    }

    @Test
    @DisplayName("🔴 覆盖不到的墙钟入口：冻结「树里今天有没有它」（出现 ⇒ 红；销账遗漏 ⇒ 红）")
    void outOfScopeSpellingsPresenceIsFrozen() throws IOException {
        Scan scan = scan(testRoot());
        List<String> problems = new ArrayList<>();
        int declared = 0;
        for (Spelling spelling : SPELLINGS) {
            if (spelling.disposition() != Disposition.OUT_OF_SCOPE) {
                continue;
            }
            declared++;
            boolean present = scan.census().getOrDefault(spelling.needle(), 0) > 0;
            if (present != spelling.presentInTree()) {
                problems.add("覆盖外拼写 `" + spelling.needle() + "` 登记 presentInTree="
                        + spelling.presentInTree() + " 而现取=" + present + "（" + spelling.why() + "）");
            }
        }
        assertThat(problems)
                .as("本守卫**看不见**的墙钟入口必须有活着的登记：出现 ⇒ 人工裁定它是不是「当业务基准用」；"
                        + "消失 ⇒ 销账（条目不许陈旧）")
                .isEmpty();
        assertThat(declared)
                .as("覆盖外的登记不许清空（全删 = 把「看不见」说成「已覆盖」）")
                .isGreaterThan(0);
    }

    @Test
    @DisplayName("🔴 零回归：既有 5 条禁则逐字仍在、仍是 ANYWHERE；台账对任意一条注入 +1 必红")
    void existingRulesAndLedgerSemanticsAreFrozen() {
        List<String> existing = List.of("LocalDate.now(", "LocalDateTime.now(", "LocalTime.now(",
                "\"Asia/Shanghai\"", "ZoneId.of(\"Asia/Shanghai\")");
        assertThat(FORBIDDEN.stream().map(Rule::needle).filter(existing::contains).toList())
                .as("既有 5 条禁则的 needle 逐字仍在、各出现一次（改名 / 删除 / 重复 ⇒ 红）")
                .containsExactlyElementsOf(existing);
        assertThat(FORBIDDEN.stream().filter(r -> existing.contains(r.needle())).map(Rule::shape).toList())
                .as("既有 5 条必须仍是 ANYWHERE（改成形态判定 = 放宽，issue #5689 边界明令禁止）")
                .containsOnly(Shape.ANYWHERE);
        Map<String, Integer> hits = new LinkedHashMap<>(LEDGER);
        Map.Entry<String, Integer> any = hits.entrySet().iterator().next();
        any.setValue(any.getValue() + 1);
        assertThat(reconcile(hits, LEDGER))
                .as("对台账里**任意一条**注入 +1 ⇒ 必须红（存量 40 处 / 13 条的语义未变：只许缩短）")
                .hasSize(1);
        assertThat(LEDGER)
                .as("存量台账不许清空（清空 = 把病说成已治）")
                .isNotEmpty();
        assertThat(LEDGER.values()).allSatisfy(count -> assertThat(count).isPositive());
    }

    @Test
    @DisplayName("🔴 三个已修类的族级读数：原始命中按现取判（不许用旧口径的 0 充数）、判红为 0")
    void fixedClassesRawCensusIsReadLiveAndJudgedClean() throws IOException {
        int raw = 0;
        int judged = 0;
        for (String rel : FIXED_BY_THIS_CHANGE) {
            String code = stripComments(Files.readString(testRoot().resolve(rel), StandardCharsets.UTF_8));
            String shapeView = maskLiterals(code);
            for (Rule rule : FORBIDDEN) {
                if (rule.shape() != Shape.AS_BUSINESS_BASIS) {
                    continue;
                }
                raw += countOccurrences(shapeView, rule.needle());
                judged += countHits(code, shapeView, rule);
            }
        }
        assertThat(judged)
                .as("三个已修类在**新族禁列**下的判红数（形态判定口径）必须是 0")
                .isZero();
        assertThat(raw)
                .as("三个已修类在**新族禁列**下的**原始命中**（现取读数；issue #5689 验收 7 要求如实报出）——"
                        + "ProcessingOrderServiceTest 今天 5 处，全是计时括号 / 夹具数据（逐处判定见类注释）；"
                        + "判红 0 是**逐处形态判定**的结果，不是「新针没生效」")
                .isGreaterThanOrEqualTo(5);
    }

    @Test
    @DisplayName("隔离目录注入违规 ⇒ 扫描器逐条报出（守卫自身判别力自证，不碰真源树）")
    void detectsInjectedViolationInIsolatedTree(@TempDir Path tempDir) throws IOException {
        Path sample = tempDir.resolve("com/migao/admin/service/InjectedSampleTest.java");
        Files.createDirectories(sample.getParent());
        Files.writeString(sample, """
                package com.migao.admin.service;
                class InjectedSampleTest {
                    void t() {
                        java.time.LocalDate today = java.time.LocalDate.now();
                        java.time.LocalDate businessDay = java.time.OffsetDateTime.now().toLocalDate();
                    }
                }
                """, StandardCharsets.UTF_8);

        Scan scan = scan(tempDir);
        assertThat(scan.hits())
                .as("隔离目录里的违规必须被逐条报出（且命中键带文件名）—— 含**新族**的「当业务基准用」形态")
                .containsKey("com/migao/admin/service/InjectedSampleTest.java|无参 LocalDate.now()")
                .containsKey("com/migao/admin/service/InjectedSampleTest.java|无参 OffsetDateTime.now()");
        assertThat(reconcile(scan.hits(), Map.of()))
                .as("未登记的注入命中 ⇒ 对账必须判红（两条）")
                .hasSize(2);
    }
}
