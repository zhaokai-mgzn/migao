'use client'

/**
 * 「安装位置」的**常用空间快捷词**（issue #7856）。
 *
 * 语义 = 这一扇窗装在那户人家的哪个空间（**不是**部位 / 帘种 —— 那个是 `curtainType`）。
 * 口径（用户 2026-10-26 需求）：**自由文本**，chips 只是**录入捷径** ——
 * 点一下把值填进输入框，再点一次清空；商家照样可以自己敲（不在词表里的也叫安装位置，
 * 不许把词表当成值域校验）。
 *
 * 两个录入面共用这一份（下单页的行内录入 / 改单弹层的行内录入）—— 词表只许有一处，
 * 两个面各写一份必然漂。
 */
export const INSTALL_ROOM_OPTIONS = [
  '主卧',
  '次卧',
  '儿童房',
  '长辈房',
  '书房',
  '客厅',
  '餐厅',
  '阳台',
  '飘窗',
  '厨房',
  '卫生间',
  '玄关',
  '影音室',
  '办公室',
] as const

export interface InstallRoomChipsProps {
  /** 当前输入值（用于回显选中态；纯空白视为未选） */
  value: string
  /** 点chip ⇒ 填入该空间名；点已选中的 ⇒ 传空串（由上游清空） */
  onPick: (room: string) => void
}

export default function InstallRoomChips({ value, onPick }: InstallRoomChipsProps) {
  const current = value.trim()
  return (
    <div className="mt-1.5 flex flex-wrap gap-1.5">
      {INSTALL_ROOM_OPTIONS.map((room) => {
        const active = current === room
        return (
          <button
            key={room}
            type="button"
            data-testid={`install-room-chip-${room}`}
            aria-pressed={active}
            onClick={() => onPick(active ? '' : room)}
            className={
              active
                ? 'px-2.5 py-1 rounded-full border border-primary-500 bg-primary-50 text-xs text-primary-700'
                : 'px-2.5 py-1 rounded-full border border-neutral-200 text-xs text-neutral-600 hover:border-neutral-300'
            }
          >
            {room}
          </button>
        )
      })}
    </div>
  )
}
