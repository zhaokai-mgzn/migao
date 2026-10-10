/**
 * 时间展示的**单一真值**（issue #6666 判据 8）
 *
 * 为什么要收敛：head 之前 bmini 同族信息有**四份**写法 ——
 * 对话气泡（今天 `09:30` / 非今天 `10-09 09:30`）、坐席详情 `slice(11,16)`（跨天也不带日期）、
 * 坐席列表 `slice(5,16)`（今天也带日期）、「数据」页待办 `slice(0,16)`（恒带年份）。
 * 四份口径各自演进 ⇒ 同一个时间在不同面长得不一样，而**没有任何东西会因此变红**。
 *
 * 口径（取对话气泡那份，信息量最合手）：**今天只给 `HH:MM`，非今天给 `MM-DD HH:MM`**；
 * 解析不了 ⇒ 空串（**不编时间**）。
 */
export function formatMessageTime(value: string | null | undefined): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''

  const now = new Date()
  const isToday =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()

  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  if (isToday) return `${hours}:${minutes}`

  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${month}-${day} ${hours}:${minutes}`
}
