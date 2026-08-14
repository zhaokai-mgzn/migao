"""yaml_light — 极简 YAML 子集解析器（供二郎神引擎读 tech-stack.yml）。

支持: block mapping / block sequence / 标量(字符串/数字/布尔/null/空[]/{})。
不支持: flow style / 多行字符串 / anchor / tag。足够解析 tech-stack.yml 这类简单结构。
零依赖，替代 PyYAML。
"""


def _parse_scalar(s):
    s = s.strip()
    if s in ('', '~', 'null', 'Null', 'NULL'):
        return None
    if s in ('true', 'True', 'TRUE'):
        return True
    if s in ('false', 'False', 'FALSE'):
        return False
    if s in ('[]', '{}'):
        return [] if s == '[]' else {}
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


def load(text):
    rows = []
    for line in text.split('\n'):
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        indent = len(line) - len(line.lstrip(' '))
        rows.append((indent, stripped))

    if not rows:
        return {}

    pos = 0
    n = len(rows)

    def peek():
        return rows[pos] if pos < n else (None, None)

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
            cur_indent, content = peek()
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
                result[key] = _parse_scalar(val)
        return result

    def parse_sequence(indent):
        nonlocal pos
        result = []
        while pos < n:
            cur_indent, content = peek()
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
                    item[k] = _parse_scalar(v)
                while pos < n:
                    cur_indent, content = peek()
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
                        item[k2] = _parse_scalar(v2)
                result.append(item)
            else:
                pos += 1
                result.append(_parse_scalar(rest))
        return result

    return parse_node(rows[0][0])


def load_file(path):
    with open(path, encoding='utf-8') as f:
        return load(f.read())
