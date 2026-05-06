#!/bin/bash
set -e

# 获取Token
TOKEN=$(curl -s -X POST http://localhost:8080/api/auth/admin/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123","tenantId":1}' | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['accessToken'])")

echo "TOKEN obtained: ${TOKEN:0:20}..."

# 辅助函数：创建会话
create_session() {
  curl -s -X POST http://localhost:8000/api/chat/sessions \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{}' | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['id'])"
}

# 辅助函数：发送消息并提取text事件的完整文本
send_and_extract() {
  local sid="$1"
  local msg="$2"
  local scenario="$3"
  
  local tmpfile="/tmp/sse_scenario_${scenario}.txt"
  
  curl -s -N -X POST http://localhost:8000/api/chat/send \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"session_id\":\"${sid}\",\"message\":\"${msg}\"}" \
    --max-time 120 > "$tmpfile" 2>&1
  
  echo ""
  echo "【场景${scenario}】用户：${msg}"
  echo "AI完整回复："
  
  python3 -c "
import json, sys
with open('$tmpfile', 'r') as f:
    lines = f.readlines()
is_text = False
parts = []
for line in lines:
    line = line.rstrip()
    if line == 'event: text':
        is_text = True
    elif line.startswith('data:') and is_text:
        try:
            d = json.loads(line[5:].strip())
            parts.append(d.get('content', ''))
        except:
            parts.append(line[5:].strip())
        is_text = False
    elif line.startswith('event:'):
        is_text = False
print(''.join(parts))
"
  
  echo ""
  echo "---"
}

# ========== 组A：基础对话 ==========
echo "========== 组A：基础对话 =========="
SID_A=$(create_session)
echo "Session A: $SID_A"

send_and_extract "$SID_A" "你好" "1"
send_and_extract "$SID_A" "你能做什么？" "2"
send_and_extract "$SID_A" "今天天气怎么样？" "3"
send_and_extract "$SID_A" "谢谢，再见" "4"

# ========== 组B：商品查询 ==========
echo "========== 组B：商品查询 =========="
SID_B=$(create_session)
echo "Session B: $SID_B"

send_and_extract "$SID_B" "有什么窗帘推荐？" "5"
send_and_extract "$SID_B" "有没有纱帘？" "6"

# ========== 组C：知识库 ==========
echo "========== 组C：知识库 =========="
SID_C=$(create_session)
echo "Session C: $SID_C"

send_and_extract "$SID_C" "雪尼尔面料的窗帘怎么清洗？" "7"
send_and_extract "$SID_C" "那涤纶的呢？清洗方法一样吗？" "8"
send_and_extract "$SID_C" "飘窗怎么量尺寸？" "9"

# ========== 组D：订单 ==========
echo "========== 组D：订单 =========="
SID_D=$(create_session)
echo "Session D: $SID_D"

send_and_extract "$SID_D" "帮我查一下最近的订单" "10"
send_and_extract "$SID_D" "订单号ORD-20250101001的状态是什么？" "11"

# ========== 组E：售后 ==========
echo "========== 组E：售后 =========="
SID_E=$(create_session)
echo "Session E: $SID_E"

send_and_extract "$SID_E" "我买的窗帘颜色不对，想退货" "12"
send_and_extract "$SID_E" "退货流程是什么？需要多久？" "13"

echo ""
echo "========== 全部场景执行完毕 =========="
