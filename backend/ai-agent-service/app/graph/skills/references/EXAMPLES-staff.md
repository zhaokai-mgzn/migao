# Staff Skill — Few-shot 示例

## ✅ 正确示例

### 例1: 查看员工列表
用户: "有哪些客服"
```
→ employee_manage(action="list", role="agent")
→ 展示客服列表：
  • 张三 · agent · 在线 · 上次登录 06-12 09:30
  • 李四 · agent · 离线 · 上次登录 06-11 18:00
```

### 例2: 创建新员工
用户: "新来了一个客服叫王五，帮他开个账号"
```
→ 进入收集流程：
  ask: "请提供王五的手机号和初始密码"
→ 用户: "138xxxx1234，初始密码123456"
→ confirm: "确认创建员工账号？姓名：王五，角色：客服，手机：138xxxx1234"
→ 用户: "确认"
→ employee_manage(action="create", name="王五", phone="138xxxx1234", role="agent", password="123456")
→ "员工账号已创建：王五（客服），账号ID：EMP-xxx"
```

### 例3: 禁用离职员工
用户: "张三离职了，把他账号停掉"
```
→ 先确认："确认禁用张三的账号吗？禁用后该员工将无法登录系统。"
→ 用户确认后: employee_manage(action="toggle_status", user_id="xxx", status="disabled")
→ "张三的账号已禁用"
```

## ❌ 错误示例

### 反例1: 不确认就删除员工
用户: "把李四删了"
```
❌ 直接调 employee_manage(action="delete", user_id="xxx")
✅ 二次确认风险："删除员工是不可逆操作，确认删除李四的账号吗？该员工的所有操作记录将保留但账号无法恢复。"
```

### 反例2: 创建员工跳必备字段
用户: "加个员工"
```
❌ employee_manage(action="create", name="新员工")（缺手机号、角色）
✅ 先收集完整信息再创建
```
