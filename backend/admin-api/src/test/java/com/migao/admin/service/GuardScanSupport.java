// case_ids: MC-100
package com.migao.admin.service;

/**
 * 元守卫**取块**共用的源码剥壳工具（issue #6956 第二部分 · 收口去重）。
 *
 * <p><b>为什么要有这个类</b>：本仓一族类级元守卫（MC-100 / MC-102 / MC-104 / PR-023 / PR-028）
 * 都要「读 Java 源码文本 → 取类体顶层的方法体 → 按方法体判形态」。它们的**取块粒度**各不相同
 * （签名归一方式、是否走逻辑行、深度计数口径都不同 ⇒ 各自的 {@code membersWithBody} 保持私有、
 * <b>有意不共用</b>），但它们**必须先做同一件事**：把注释 / 字符串字面量里的括号抹掉 ——
 * 否则花括号深度会被 {@code // 形如 &#123;} 或 {@code "{"} 带偏 ⇒ 其后方法整段扫不到、
 * 或 body 被截断成空壳而判据照绿（「收错了」比「没收到」更坏）。</p>
 *
 * <p>⚠️ 这段剥壳原先在 5 个守卫里**各有一份拷贝**（实测：MC-100 / MC-102 / MC-104 三份逐字相同，
 * PR-023 / PR-028 另有一份**能力更弱**的变体 —— 它不剥字符字面量与文本块）。各写一份的代价不是
 * 「多几行」，而是**修一处不等于修一类**：本包在 MC-102 上复现出的同款失明，正是因为修法没有承载体。
 * ⇒ 收敛到此一处，各守卫只保留自己的取块粒度。</p>
 */
final class GuardScanSupport {

    private GuardScanSupport() {
    }

    /**
     * 剥掉块注释 / 行注释 / 字符串字面量 / 字符字面量 / 文本块，**保留行结构**
     * （非换行字符变空格，换行原样留下）—— 行号与「4 空格缩进」判定都依赖它。
     *
     * <p>字符字面量（{@code '&#123;'}）与文本块（{@code """…"""}）也一并剥掉：它们是同一族的
     * 括号污染源，而 PR-023 / PR-028 原先那份变体<b>没盖到</b>这两类（本类取能力最强的那一份，
     * 并集覆盖）。</p>
     */
    static String stripCommentsAndStrings(String src) {
        StringBuilder out = new StringBuilder(src.length());
        int i = 0;
        int n = src.length();
        while (i < n) {
            char c = src.charAt(i);
            if (src.startsWith("/*", i)) {
                int j = src.indexOf("*/", i + 2);
                j = j < 0 ? n : j + 2;
                appendBlanks(out, src, i, j);
                i = j;
            } else if (src.startsWith("//", i)) {
                int j = src.indexOf('\n', i);
                j = j < 0 ? n : j;
                appendBlanks(out, src, i, j);
                i = j;
            } else if (src.startsWith("\"\"\"", i)) {
                int j = src.indexOf("\"\"\"", i + 3);
                j = j < 0 ? n : j + 3;
                appendBlanks(out, src, i, j);
                i = j;
            } else if (c == '"' || c == '\'') {
                int j = i + 1;
                while (j < n) {
                    if (src.charAt(j) == '\\') {
                        j += 2;
                        continue;
                    }
                    if (src.charAt(j) == c) {
                        j++;
                        break;
                    }
                    j++;
                }
                appendBlanks(out, src, i, Math.min(j, n));
                i = Math.min(j, n);
            } else {
                out.append(c);
                i++;
            }
        }
        return out.toString();
    }

    /** 把 {@code [from, to)} 逐字符写成空格，**换行原样保留**。 */
    private static void appendBlanks(StringBuilder out, String src, int from, int to) {
        for (int k = from; k < to; k++) {
            out.append(src.charAt(k) == '\n' ? '\n' : ' ');
        }
    }
}
