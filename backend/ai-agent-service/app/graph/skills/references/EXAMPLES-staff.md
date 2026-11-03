# Staff Skill — Few-shot 示例

> ✅ 员工账号**可建可改**（`employee_manage` 的 create/update，走确认卡；issue #7050）。
> ❌ 删除/停用（离职）/重置密码、建/改/删角色（岗位）、分配权限不在能力内（`role_manage` 只读）。

## ✅ 正确示例

### 例1: 查看员工列表
用户: "有哪些客服"
```
→ employee_manage(action="list", role="agent")
→ 展示：张三 · agent · 在线；李四 · agent · 离线
```

### 例2: 开新员工账号（收集 → 确认卡 → 建账号）
用户: "新来了个客服叫王五，帮他开个账号"
```
→ role_manage(action="list")                  # 拿真实岗位（不编造角色 id/code）
→ 收集四样：姓名、手机号（登录账号）、初始密码、岗位
→ interact(component="confirm", title="确认新建员工账号",
           content="王五 · 客服(agent) · 手机号 138****", confirmValue="确认创建员工王五")
→ 用户点确认后：employee_manage(action="create", name="王五", phone="138...", password="***", role="agent")
→ "员工【王五】已创建，登录手机号 138..."
```

### 例3: 商家要停用离职员工
用户: "张三离职了，把他账号停掉"
```
→ employee_manage(action="list", keyword="张三") 确认账号与当前状态
→ 如实说明：停用/删除不由黄金策执行（停用后该员工无法登录，属不可逆操作）
→ 引导商家到后台「组织管理 → 员工管理」页处理（不说"已禁用"）
```

### 例4: 建角色并分配权限（只读部分）
用户: "新建'库管'角色，给商品管理权限"
```
→ role_manage(action="list_permissions")  # 真实权限清单
→ role_manage(action="all")               # 查重名
→ 把角色名/编码建议/权限清单一次性给商家（如 code=warehouse_keeper）
→ 如实说明：建角色不在能力内 → 引导后台「组织管理 → 岗位权限」页（不发写确认卡）
```

### 例5: 重名角色
用户: "再建一个库管角色"
```
→ role_manage(action="all") 发现已有"库管"
→ "系统已有「库管」角色（编码 warehouse_keeper）。需要我先把它的权限清单列出来吗？"
```

## ❌ 错误示例

### 反例1: 跳过确认卡直接建账号
用户: "给他开个账号，手机号 13812345678，密码 Abc123456"
```
❌ 直接 employee_manage(action="create", ...)（未确认 ⇒ 确认门禁拦下，白跑一轮）
✅ 先发确认卡（谁 / 什么岗位 / 手机号），用户点确认后再 create
```

### 反例2: 猜岗位 / 擅自删除
用户: "加个员工"（未说明岗位）
```
❌ 猜一个岗位（如 operator）直接建 —— 服务端拒，且猜岗位 = 越权
✅ role_manage(action="list") 给出岗位清单，问清岗位后再走确认卡 → create
```
用户: "把李四删了"
```
❌ 直接调 employee_manage(action="delete", user_id="xxx")（本域没有这个 action；破坏性操作不由黄金策下发）
✅ 说明不可逆影响 + 引导后台「组织管理 → 员工管理」页自行确认后删除
```
