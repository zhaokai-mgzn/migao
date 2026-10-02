// case_ids: UI-030, CH-009, UI-017
/**
 * B 端 form 卡（`InteractiveMessage.tsx` 的 `FormCard`）**提交形态**与本地护栏（issue #5949）。
 *
 * 文件名 = 被测源文件同名（`tests/unit/components/<被测组件>.test.tsx`，
 * `.github/tech-stack.yml` 的 admin-web 规则：`src/components/…/<Name>.tsx` ⇒ 缺测门禁
 * 找的正是这个名字 —— 取别的名字会被 QA Growth Gate 判「缺测」而**看不出是命名问题**）。
 *
 * 病（可复算）：`frontend/admin-web/src/components/chat/InteractiveMessage.tsx` 的 `FormCard`
 * 曾把字段拼成 `label: value` 多行文本后 `sendMessage(lines)`；而后端「答卡轮」契约
 * （`app/graph/nodes.py::_card_accepts_answer` 的 form 分支）只认 `__FORM__|` 前缀
 * ⇒ **B 端 form 卡永远不成立答卡轮**（用户可感知：卡答了却没执行、又被重问一遍）。
 *
 * 本文件钉四件事：
 * ① 提交 = 请求体结构化 `card_answer={cardId, values}`（不再是自由文本当提交体）；
 * ② `cardId` 与服务端 `_card_identity` **同口径**（`component|title|formField keys`）；
 * ③ 缺必填**不得**发出提交（本地校验）；
 * ④ 已答锁：同一次事件内连点两次只提交一次（`submitted` state 在事件之后才提交 ⇒
 *    光靠 state 挡不住同 tick 的第二次）。
 *
 * 跨端形态判据（三端真源码 + 变异自证）：backend/ai-agent-service/tests/
 * test_card_form_submit_shape_cross_end_contract.py
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import React from 'react'

const mockUseChatStore = vi.fn()

vi.mock('@/store/chat', () => {
  const fn = (...args: any[]) => mockUseChatStore(...args)
  return { useChatStore: Object.assign(fn, { getState: () => mockUseChatStore() }) }
})

import InteractiveMessage from '@/components/chat/InteractiveMessage'

const FORM = {
  component: 'form' as const,
  title: '订单 — 收货信息',
  formFields: [
    { key: 'receiver', label: '收货人', required: true },
    { key: 'remark', label: '备注' },
  ],
  submitLabel: '提交',
}

function setup() {
  const sendMessage = vi.fn()
  mockUseChatStore.mockReturnValue({
    sendMessage,
    currentSessionId: 'sess_1',
    choiceSelections: {},
    toggleChoiceSelection: vi.fn(),
    clearChoiceSelections: vi.fn(),
  })
  return sendMessage
}

const submitBtn = () => screen.getByRole('button', { name: '提交' })

beforeEach(() => {
  mockUseChatStore.mockReset()
})

describe('FormCard 提交形态（结构化 card_answer）', () => {
  it('提交 = card_answer{cardId, values}；可读回显仍随 message 下发', () => {
    const sendMessage = setup()
    render(<InteractiveMessage interactive={FORM} />)

    fireEvent.change(screen.getByPlaceholderText('请输入收货人'), { target: { value: '张三' } })
    fireEvent.change(screen.getByPlaceholderText('请输入备注'), { target: { value: '尽快发货' } })
    fireEvent.click(submitBtn())

    expect(sendMessage).toHaveBeenCalledTimes(1)
    const [content, images, cardAnswer] = sendMessage.mock.calls[0]
    // 自由文本**不再是**提交体（它只是降级路径的载体：cardId 对不上时后端按普通消息走）
    expect(content).toBe('收货人: 张三\n备注: 尽快发货')
    expect(images).toBeUndefined()
    expect(cardAnswer).toEqual({
      // 与后端 `_card_identity` 同口径：component|title|formField keys
      cardId: 'form|订单 — 收货信息|receiver|remark',
      values: { receiver: '张三', remark: '尽快发货' },
    })
  })

  it('缺必填 → 不发提交 + 给出提示（本地校验）', () => {
    const sendMessage = setup()
    render(<InteractiveMessage interactive={FORM} />)

    fireEvent.click(submitBtn())

    expect(sendMessage).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent('收货人')
  })

  it('必填已填（非必填留空）→ 放行（校验不得过宽）', () => {
    const sendMessage = setup()
    render(<InteractiveMessage interactive={FORM} />)

    fireEvent.change(screen.getByPlaceholderText('请输入收货人'), { target: { value: ' 张三 ' } })
    fireEvent.click(submitBtn())

    expect(sendMessage).toHaveBeenCalledTimes(1)
    expect(sendMessage.mock.calls[0][2].values).toEqual({ receiver: ' 张三 ', remark: '' })
  })

  it('已答锁：同一次事件内连点两次只提交一次', () => {
    const sendMessage = setup()
    render(<InteractiveMessage interactive={FORM} />)
    fireEvent.change(screen.getByPlaceholderText('请输入收货人'), { target: { value: '张三' } })

    const btn = submitBtn()
    // 同一次 act（同一批更新）内两次点击：`submitted` state 还没提交 ⇒ 只有 ref 挡得住
    act(() => {
      btn.click()
      btn.click()
    })

    expect(sendMessage).toHaveBeenCalledTimes(1)
  })

  it('已答复只读（disabled）→ 不提交', () => {
    const sendMessage = setup()
    render(<InteractiveMessage interactive={FORM} disabled />)

    fireEvent.click(submitBtn())

    expect(sendMessage).not.toHaveBeenCalled()
  })
})
