"""yaml_light — 极简 YAML 子集解析器（供 QA Growth Gate 引擎读 tech-stack.yml）。

支持: block mapping / block sequence / 标量(字符串/数字/布尔/null/空[]/{})。
不支持: anchor / tag。足够解析 tech-stack.yml 这类简单结构。
零依赖，替代 PyYAML。

## 多行标量的取值保真度（issue #5171）

本解析器是**面向行**的状态机，原先对**多行标量**取值不保真：

· `key: |` 的取值变成**字面字符串** `'|'`，而块内容行被当成**独立行**继续喂给状态机 ——
  它们的缩进更大 ⇒ `parse_sequence()` 当场 `break` ⇒ 该条目**之后的兄弟条目整段消失**
  （实测：`data_checks` 3 条 ⇒ 1 条，且 1 条的值还是 `'|'`）。
· `key: "第一行`（引号跨行）同理：值变成 `'"第一行'`，续行与后续条目一起消失。

两条路径**都不报错** ⇒ `render_cases.py` 照旧渲染成功、生成物新鲜度照旧绿 = **零信号**
（"绿了但没跑"家族：真值源静默缩水，下游全部跟着失真）。

⇒ `_logical_rows()` 现在先把**块标量**（`|` / `>`，含 `-`/`+` chomping 与缩进指示数字）与
**跨行引号标量**整段读成**一个逻辑行**，取值按 YAML 8.1.3 的折叠 / chomping 规则算，
与 `yaml.safe_load` 逐值一致。

## 仍未保真（如实登记，**有死亡条件**）

逐条钉在 `tests/unit_ci_workflows/test_yaml_light_scalar_fidelity.py` 的 `STILL_UNFAITHFUL`：
谁把某条补上了，对应断言**当场变红**，逼他更新那张表（本仓 §17.3 ④ 的口径）：

| 仍不保真的形态 | 现在的取值 |
|---|---|
| **转义序列不反转义**（`"a\\"b"` / `"a\\\\b"` / `"a\\/b"` / `"a\\nb"`） | 原样保留反斜杠 |
| **跨行 flow 集合**（`k: [a,` + 续行 `b]`） | `'[a,'`（后半段丢失） |
| **跨行裸标量**（`k: 第一行` + 缩进续行 `第二行`） | `'第一行'`（续行不在值里） |

⚠️ 第一条**正在生效**：`.github/cases/*.yml` 实测 **36 处**取值与 `yaml.safe_load` 不同
（31 处 `\\"` + 5 处 `\\\\` / `\\/`），即**已提交的生成物里就带着这些反斜杠**。
**本单有意不动它** —— 改了它会改 `.github/cases/**` 的渲染产物，而生成物是全仓唯一源头
（波及所有在飞包），属另一单的范围。
"""


import re

#: 「本行的值**不是**多行标量」的哨兵 —— `None` 是**合法取值**，不能拿它当缺省
_MISS = object()

#: 块标量头：`|` / `>` + 缩进指示数字与 chomping 指示符（YAML 允许两种顺序）
_BLOCK_HEAD_RE = re.compile(r"^([|>])([0-9]?)([+-]?)$|^([|>])([+-]?)([0-9]?)$")


def _strip_inline_comment(s: str) -> str:
    """去掉**引号外**且前面有空白的行内注释（`"确认"   # 说明` → `"确认"`）。

    为什么必须有（issue #3365 实证）：本解析器原先不处理行内注释 →
    `fallback: "确认"  # 点确认卡…` 解析出的值是**带引号带注释的整串**
    （`'"确认"  # 点确认卡…'`），而评测 harness 会把它当**用户消息**发给 agent →
    协议轮变成乱码文本、流程判断全错：OR-017 实测连发 6 轮加工项卡、order_create 永不发生。
    标准 YAML 规则：`#` 前有空白即起注释，**除非在引号内**（引号内的 `issue #3270` 必须保留）。
    """
    out = []
    quote = None
    for i, ch in enumerate(s):
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ('"', "'"):
            quote = ch
            out.append(ch)
            continue
        if ch == "#" and i > 0 and s[i - 1].isspace():
            break
        out.append(ch)
    return "".join(out).rstrip()


def _parse_scalar(s):
    s = _strip_inline_comment(s).strip()
    if s in ('', '~', 'null', 'Null', 'NULL'):
        return None
    if s in ('true', 'True', 'TRUE'):
        return True
    if s in ('false', 'False', 'FALSE'):
        return False
    if s in ('[]', '{}'):
        return [] if s == '[]' else {}
    # ⚠️ 保守判据（issue #3367 回归修复）：真值文件用 `- [misc.x] 说明… → 返回 []`，
    # 这种行**以 [ 开头、以 ] 结尾**，但内部还含 `[`/`]` —— 它不是 flow 序列，是散文。
    # 首版只管首尾括号，把这类真值行吞成序列 → 真值 ID 丢失 → Case Contract 门禁在 main 上
    # fail-closed 报红。故：**内部再出现括号就不当序列解析**。
    _inner = s[1:-1]
    if s.startswith('[') and s.endswith(']') and not any(c in _inner for c in '[]'):
        # flow 序列（issue #3367）：`[unit_price, subtotal, total]` 此前被原样当字符串，
        # 直接坑到金额断言 —— `checks` 收字符串后被按字符迭代 → 检查项全部静默跳过。
        # 只解析**标量**元素（用例里的形态就这些）；解析不出来时保留原字符串（向后兼容，
        # 由消费侧失败关闭兜底，不在这里抛异常打断整份用例加载）。
        inner = s[1:-1].strip()
        if not inner:
            return []
        parts, buf, quote = [], '', ''
        for ch in inner:
            if quote:
                if ch == quote:
                    quote = ''
                buf += ch
                continue
            if ch in ('"', "'"):
                quote = ch
                buf += ch
                continue
            if ch == ',':
                parts.append(buf)
                buf = ''
                continue
            buf += ch
        parts.append(buf)
        return [_parse_scalar(p) for p in parts if p.strip() != '']
    _inner_map = s[1:-1]
    if s.startswith('{') and s.endswith('}') and not any(c in _inner_map for c in '{}'):
        # flow 映射：`{夏日清风窗帘: 3}` → dict（expect_quantities 这类配置会用到）
        inner = s[1:-1].strip()
        if not inner:
            return {}
        out, buf, quote, depth = {}, '', '', 0
        items = []
        for ch in inner:
            if quote:
                if ch == quote:
                    quote = ''
                buf += ch
                continue
            if ch in ('"', "'"):
                quote = ch
                buf += ch
                continue
            if ch == ',' and depth == 0:
                items.append(buf)
                buf = ''
                continue
            buf += ch
        items.append(buf)
        for it in items:
            if ':' not in it:
                continue
            k, v = it.split(':', 1)
            out[_parse_scalar(k.strip()) if isinstance(_parse_scalar(k.strip()), str) else str(_parse_scalar(k.strip()))] = _parse_scalar(v)
        return out
    if len(s) >= 2 and s[0] in ('"', "'") and s[-1] == s[0]:
        return s[1:-1]
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _is_inline_map_key(rest):
    """判断 '- rest' 是否为内联映射 '- key: value'。

    仅当冒号前的 key 是单 token（无空白）时视为映射；
    否则是「含冒号的标量字符串」（如真值文本 '返回 {applicationId, status:"pending"}'），
    必须保持为字符串，避免被误拆成 dict。
    """
    k0 = rest.partition(':')[0].strip()
    return bool(k0) and not any(ch.isspace() for ch in k0)


def _head_value(stripped):
    """行的**值原文**（`key: v` / `- key: v` / `- v`）；不是值位置 ⇒ `None`（`-` 空项 ⇒ `''`）。

    与两个 `parse_*` 里的切片口径**逐字同源**（`_is_inline_map_key` 的判据也复用），
    否则"多行读取器认出来的头"与"状态机认出来的值"会分叉。
    """
    body = stripped
    if body.startswith('- ') or body == '-':
        rest = body[1:].strip()
        if ':' in rest and rest[0] not in ('"', "'") and _is_inline_map_key(rest):
            rest = rest.partition(':')[2]
        return rest.strip()
    if ':' in body:
        return body.partition(':')[2].strip()
    return None


def _quote_close(s, quote):
    """`s`（开引号**之后**的部分）里闭合引号的下标；没有 ⇒ `None`。

    `\\x`（双引号）/ `''`（单引号）是转义 ⇒ 不算闭合（口径同 `cases_yaml._find_close`）。
    """
    j = 0
    while j < len(s):
        ch = s[j]
        if quote == '"' and ch == '\\':
            j += 2
            continue
        if ch == quote:
            if quote == "'" and j + 1 < len(s) and s[j + 1] == "'":
                j += 2
                continue
            return j
        j += 1
    return None


def _fold_block(lines):
    """`>` 折叠标量（YAML 8.1.3）：非空行之间折成空格；连续空行折成**等量**换行；更缩进的行保留字面换行。

    `lines` = `[(文本, 是否比块缩进更深)]`。实测口径（本机 PyYAML 6.0.3）：
    `a|b` ⇒ `'a b'`；`a||b` ⇒ `'a\\nb'`；`a|||b` ⇒ `'a\\n\\nb'`；`a|  b|c` ⇒ `'a\\n  b\\nc'`。
    """
    out, i, n = [], 0, len(lines)
    need_sep, prev_more = False, False
    while i < n:
        text, more = lines[i]
        if text == '':
            k = 0
            while i < n and lines[i][0] == '':
                k += 1
                i += 1
            out.append('\n' * k)              # 空行前的断行被 trim，改由空行自身计数
            need_sep = False
            continue
        if need_sep:
            out.append('\n' if (more or prev_more) else ' ')
        out.append(text)
        need_sep, prev_more = True, more
        i += 1
    return ''.join(out)


def _read_block_scalar(raw, i, head_indent, head):
    """块标量（`|` / `>`）⇒ `(下一行下标, 值)`。

    内容行 = 缩进**大于头行缩进**的连续行（空行无条件属于它）—— 与
    `.github/cases_yaml.py` 的零依赖严格闸用的判据**同一口径**（那边也是
    「块标量内容行整行跳过」）。缩进自动探测取首个非空行的缩进；显式指示数字则以其为准。
    """
    m = _BLOCK_HEAD_RE.match(head)
    style = m.group(1) or m.group(4)
    digits = m.group(2) or m.group(6) or ''
    chomp = m.group(3) or m.group(5) or ''

    body, j = [], i
    block_indent = head_indent + int(digits) if digits else None
    while j < len(raw):
        line = raw[j]
        if not line.strip():
            body.append((None, ''))           # 空行：缩进无意义（chomping 才关心它）
            j += 1
            continue
        indent = len(line) - len(line.lstrip(' '))
        if indent <= head_indent:             # 回到父级 ⇒ 块结束
            break
        if block_indent is None:
            block_indent = indent             # 自动探测：首个非空行定缩进
        if indent < block_indent:
            break
        body.append((indent, line[block_indent:]))
        j += 1

    if style == '|':
        text = '\n'.join(t for _, t in body)
    else:
        text = _fold_block([(t, (ind is not None and ind > block_indent))
                            for ind, t in body])
    text += '\n'                              # 每个内容行都带一个行尾换行
    if chomp == '-':                          # strip：丢掉全部行尾换行
        text = text.rstrip('\n')
    elif chomp == '+':                        # keep：全保留（含尾部空行）
        pass
    else:                                     # clip（缺省）：至多一个
        text = text.rstrip('\n')
        if text:
            text += '\n'
    return j, text


def _read_multiline_quoted(raw, i, head):
    """跨行引号标量 ⇒ `(下一行下标, 值)`；**到文件结尾仍未闭合 ⇒ `None`**。

    `None` 的语义是"**不接管**"：保持旧行为（含引号的整串原样返回），绝不吞掉后面的行 ——
    没闭合的文件是非法 YAML，渲染腿的严格判定（`cases_yaml.require_strict`）会先拦下它，
    这里只需要"不把坏输入变成另一种坏"。
    """
    quote, cur, j = head[0], head[1:], i
    if _quote_close(cur, quote) is not None:
        # 同一行就闭合 ⇒ **不是**跨行标量（`""` / `"a"` 都走这条）⇒ 交回 `_parse_scalar`。
        # 少了这道前置，`skip_reason: ""` 会被当成"一个空的首段" ⇒ 值变成 `'\n'`（实测踩到）。
        return None
    parts = []                                # [(文本, 与上一段之间是否「转义换行」)]
    escaped = False
    while True:
        close = _quote_close(cur, quote)
        if close is not None:
            parts.append((cur[:close], escaped))
            break
        cont = quote == '"' and cur.endswith('\\') and not cur.endswith('\\\\')
        if cont:
            cur = cur[:-1]
        parts.append((cur, escaped))
        if j >= len(raw):
            return None                       # 到结尾都没闭合 ⇒ 不接管
        escaped, cur, j = cont, raw[j].strip(), j + 1

    out, k, n = [], 0, len(parts)
    need_sep = False
    while k < n:
        text, esc = parts[k]
        if text == '':
            e = 0
            while k < n and parts[k][0] == '':
                e += 1
                k += 1
            out.append('\n' * e)              # 空行折成等量换行（实测 `"a||b"` ⇒ `'a\\nb'`）
            need_sep = False
            continue
        if need_sep:
            out.append('' if esc else ' ')    # `\\` 续行：直接相接，不留空格
        out.append(text)
        need_sep = True
        k += 1
    return j, _parse_scalar(quote + ''.join(out) + quote)


def _take_multiline(raw, i, head_indent, stripped):
    """本行的值是块标量 / 跨行引号标量 ⇒ `(下一行下标, 最终值)`；否则 `None`。

    ⚠️ 本函数**每一行都会被调一次**（`load()` 的热路径）⇒ 判断顺序按"**命中的可能性从低到高**
    排"，把最贵的 `_strip_inline_comment()`（逐字符状态机）只留给真正可能命中的行：
    绝大多数行的值是裸标量、或"同一行就闭合"的引号标量，几次首字符比较就出去了
    （实测 1034KB 用例库一轮：先做 `_strip_inline_comment` 57.9ms → 142.3ms；换序后 79.6ms）。
    """
    val = _head_value(stripped)
    if val is None:
        return None
    head = val.strip()
    if not head:
        return None
    first = head[0]
    if first in ('"', "'"):
        if _quote_close(head[1:], first) is not None:
            return None                       # 同一行就闭合（最常见）⇒ 不是跨行标量
        return _read_multiline_quoted(raw, i, _strip_inline_comment(val).strip())
    if first in '|>':                         # 块标量头只可能以这两个字符开头
        head = _strip_inline_comment(val).strip()
        if _BLOCK_HEAD_RE.match(head):
            return _read_block_scalar(raw, i, head_indent, head)
    return None


def _logical_rows(text):
    """原文 ⇒ **逻辑行** `(indent, content, value)`（`value is _MISS` = 交给 `_parse_scalar`）。

    多行标量的**内容行整段不进 rows** —— 这正是「静默丢行」的病灶所在：它们以前被当成
    独立行喂给面向行的状态机（缩进更大 ⇒ `parse_sequence()` 直接 `break`），
    该条目之后的兄弟条目随之消失，且没有任何检查会红。
    """
    raw = text.split('\n')
    rows, i = [], 0
    while i < len(raw):
        line = raw[i]
        stripped = line.strip()
        i += 1
        if not stripped or stripped.startswith('#'):
            continue
        indent = len(line) - len(line.lstrip(' '))
        taken = _take_multiline(raw, i, indent, stripped)
        if taken is None:
            rows.append((indent, stripped, _MISS))
        else:
            i, value = taken
            rows.append((indent, stripped, value))
    return rows


def _row_scalar(text, value):
    """行内标量的取值：多行读取器接管过 ⇒ 用它算好的**最终值**（`None` 也是合法值 ⇒ 用哨兵判）。"""
    return _parse_scalar(text) if value is _MISS else value


def load(text):
    rows = _logical_rows(text)

    if not rows:
        return {}

    pos = 0
    n = len(rows)

    def peek():
        return rows[pos] if pos < n else (None, None, _MISS)

    def parse_node(indent):
        nonlocal pos
        if pos >= n:
            return None
        content = peek()[1]
        if content.startswith('- ') or content == '-':
            return parse_sequence(indent)
        return parse_mapping(indent)

    def parse_mapping(indent):
        nonlocal pos
        result = {}
        while pos < n:
            cur_indent, content, value = peek()
            if cur_indent is None or cur_indent < indent:
                break
            if cur_indent > indent or content.startswith('- ') or content == '-':
                break
            if ':' not in content:
                pos += 1
                continue
            key, _, val = content.partition(':')
            key = key.strip()
            val = val.strip()
            pos += 1
            if val == '':
                if pos < n and rows[pos][0] > indent:
                    result[key] = parse_node(rows[pos][0])
                else:
                    result[key] = None
            else:
                result[key] = _row_scalar(val, value)
        return result

    def parse_sequence(indent):
        nonlocal pos
        result = []
        while pos < n:
            cur_indent, content, value = peek()
            if cur_indent is None or cur_indent < indent:
                break
            if cur_indent > indent:
                break
            if not (content.startswith('- ') or content == '-'):
                break
            rest = content[1:].strip()
            if rest == '':
                pos += 1
                if pos < n and rows[pos][0] > indent:
                    result.append(parse_node(rows[pos][0]))
                else:
                    result.append(None)
            elif ':' in rest and rest[0] not in ('"', "'") and _is_inline_map_key(rest):
                pos += 1  # 消费 '- key: value'
                item = {}
                k, _, v = rest.partition(':')
                k, v = k.strip(), v.strip()
                if v == '':
                    item[k] = parse_node(rows[pos][0]) if pos < n and rows[pos][0] > indent else None
                else:
                    item[k] = _row_scalar(v, value)
                while pos < n:
                    cur_indent, content, value2 = peek()
                    if cur_indent is None or cur_indent <= indent:
                        break
                    if content.startswith('- ') or content == '-':
                        break
                    if ':' not in content:
                        pos += 1
                        continue
                    k2, _, v2 = content.partition(':')
                    k2, v2 = k2.strip(), v2.strip()
                    pos += 1
                    if v2 == '':
                        item[k2] = parse_node(rows[pos][0]) if pos < n and rows[pos][0] > cur_indent else None
                    else:
                        item[k2] = _row_scalar(v2, value2)
                result.append(item)
            else:
                pos += 1
                result.append(_row_scalar(rest, value))
        return result

    return parse_node(rows[0][0])


def load_file(path):
    with open(path, encoding='utf-8') as f:
        return load(f.read())
