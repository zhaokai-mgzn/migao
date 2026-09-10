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
  ask: "请提供王五的手机号和初始密码（也可由我随机生成后告知）"
→ 用户: "138xxxx1234，密码你定吧"
→ confirm: "确认创建员工账号？王五/客服/138xxxx1234/密码随机生成"
→ 用户: "确认"
→ employee_manage(action="create", name="王五", phone="138xxxx1234", role="agent", password="<随机>")
→ "员工账号已创建：王五（客服），初始密码：<随机>"
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

### 例4: 创建角色并分配权限（HR-005 场景）
用户: "新建'库管'角色，给商品管理权限"
```
→ role_manage(action="list_permissions")  # 查真实权限清单
→ role_manage(action="all")               # 查重名
→ 映射：商品管理 → perm_product_manage；无独立"库存"权限
→ ask: "角色编码用 warehouse_keeper 可以吗？"
→ 用户: "可以"
→ validate_input(target_tool="role_manage", target_action="create", params={name:"库管", code:"warehouse_keeper", permission_ids:["perm_product_manage","perm_product_list","perm_product_create","perm_product_category"]})
→ interact(component="confirm", fields=[{label:"角色",value:"库管(warehouse_keeper)"},{label:"权限",value:"商品管理、商品列表、新增商品、商品分类管理"}])
→ 用户: "确认"
→ role_manage(action="create", name="库管", code="warehouse_keeper", permission_ids=["perm_product_manage","perm_product_list","perm_product_create","perm_product_category"])
→ "角色「库管」已创建，编码 warehouse_keeper，权限：商品管理/商品列表/新增商品/商品分类管理"
```

### 例5: 重名角色避免重复创建
用户: "再建一个库管角色"
```
→ role_manage(action="all")  # 发现已有"库管"
→ "系统已有「库管」角色（编码 warehouse_keeper），是否需要：1. 查看/编辑它 2. 用其他名称新建？"
```
