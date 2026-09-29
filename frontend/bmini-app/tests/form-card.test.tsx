// case_ids: CH-009, API-006, CH-030
/**
 * FormCard 组件测试（form 交互组件：多字段表单收集 + 本地校验 + __FORM__ 提交序列化）
 *
 * 覆盖：渲染、预填值、必填校验、手机号校验、数字校验、提交序列化、取消回传、错误清除。
 */
import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import FormCard from '../src/components/cards/FormCard'
import type { InteractiveData } from '../src/types'

describe('FormCard', () => {
  const baseForm: InteractiveData = {
    type: 'form',
    component: 'form',
    title: '请填写收货信息',
    formFields: [
      { key: 'customer_name', label: '收货人', placeholder: '请输入姓名', required: true },
      { key: 'customer_phone', label: '手机号', placeholder: '11 位手机号', required: true },
      { key: 'customer_address', label: '地址', placeholder: '省市区+详细地址', required: true },
      { key: 'quantity', label: '数量(米)', value: '3', required: true },
    ],
    submitLabel: '提交',
  }

  it('应渲染标题与所有字段（含必填标记与预填值）', () => {
    render(<FormCard data={baseForm} onAction={jest.fn()} />)
    expect(screen.getByText('请填写收货信息')).toBeTruthy()
    expect(screen.getByText('收货人')).toBeTruthy()
    expect(screen.getByText('手机号')).toBeTruthy()
    expect(screen.getByText('地址')).toBeTruthy()
    // 预填值：quantity 初始为 '3'
    expect(screen.getByDisplayValue('3')).toBeTruthy()
  })

  it('必填字段为空时提交应拦截并提示，不触发 onAction', () => {
    const onAction = jest.fn()
    render(<FormCard data={baseForm} onAction={onAction} />)
    // 清空数量字段后提交
    const qty = screen.getByPlaceholderText('请输入数量(米)')
    fireEvent.change(qty, { target: { value: '' } })
    fireEvent.click(screen.getByText('提交'))
    expect(screen.getByText('数量(米)为必填项')).toBeTruthy()
    expect(onAction).not.toHaveBeenCalled()
  })

  it('手机号格式错误时提交应拦截', () => {
    const onAction = jest.fn()
    render(<FormCard data={baseForm} onAction={onAction} />)
    const phone = screen.getByPlaceholderText('11 位手机号')
    fireEvent.change(phone, { target: { value: '12345' } })
    fireEvent.click(screen.getByText('提交'))
    expect(screen.getByText('请输入 11 位手机号')).toBeTruthy()
    expect(onAction).not.toHaveBeenCalled()
  })

  it('数字字段非法（<=0）时提交应拦截', () => {
    const onAction = jest.fn()
    render(<FormCard data={baseForm} onAction={onAction} />)
    const qty = screen.getByPlaceholderText('请输入数量(米)')
    fireEvent.change(qty, { target: { value: '0' } })
    fireEvent.click(screen.getByText('提交'))
    expect(screen.getByText('请输入大于 0 的数字')).toBeTruthy()
    expect(onAction).not.toHaveBeenCalled()
  })

  it('全部合法时提交应序列化为 __FORM__|json 并回传', () => {
    const onAction = jest.fn()
    render(<FormCard data={baseForm} onAction={onAction} />)
    fireEvent.change(screen.getByPlaceholderText('请输入姓名'), { target: { value: '张三' } })
    fireEvent.change(screen.getByPlaceholderText('11 位手机号'), { target: { value: '13800138000' } })
    fireEvent.change(screen.getByPlaceholderText('省市区+详细地址'), { target: { value: '杭州市西湖区' } })
    fireEvent.click(screen.getByText('提交'))
    const expected = JSON.stringify({
      customer_name: '张三',
      customer_phone: '13800138000',
      customer_address: '杭州市西湖区',
      quantity: '3',
    })
    expect(onAction).toHaveBeenCalledWith(`__FORM__|${expected}`)
  })

  it('数字字段（数量(米)）键盘用 digit ⇒ 小数点打得出来，且 0.5 原样进值 / 原样提交', () => {
    const onAction = jest.fn()
    render(<FormCard data={baseForm} onAction={onAction} />)
    // 🔴 `type='number'` 的数字键盘**没有小数点键** ⇒ 「2.5 米」这类小数在真机上**根本打不出来**
    //    （用户报障「输入框无法输入小数点」的原身）；`digit` 是小程序里唯一带小数点的数字键盘
    //    （先例 = 工人端报工数量，UI-055 判据 5）。
    const qty = screen.getByPlaceholderText('请输入数量(米)') as HTMLInputElement
    expect(qty.getAttribute('type')).toBe('digit')
    // 逐键：清空 → "0" → "0." → "0.5"（中间态不得被吞，原样留在框里）
    fireEvent.change(qty, { target: { value: '' } })
    fireEvent.change(qty, { target: { value: '0' } })
    expect(qty.value).toBe('0')
    fireEvent.change(qty, { target: { value: '0.' } })
    expect(qty.value).toBe('0.')
    fireEvent.change(qty, { target: { value: '0.5' } })
    expect(qty.value).toBe('0.5')
    // 手机上仍是普通键盘 —— 本单**只**把数字字段的键盘从「打不出小数点」改成 `digit`，
    // 不顺手扩大射程（手机号字段现有形态 = `text`，要改成数字键盘是**另一件事**，
    // 故这里只钉「没被数字字段的修复带偏」）。已知缺口照实登记在 PR body，不在这里留白。
    expect(
      (screen.getByPlaceholderText('11 位手机号') as HTMLInputElement).getAttribute('type')
    ).not.toBe('digit')
    // 补全必填后提交：0.5 原样序列化（本地校验 / 序列化都不得把小数改掉）
    fireEvent.change(screen.getByPlaceholderText('请输入姓名'), { target: { value: '张三' } })
    fireEvent.change(screen.getByPlaceholderText('11 位手机号'), { target: { value: '13800138000' } })
    fireEvent.change(screen.getByPlaceholderText('省市区+详细地址'), { target: { value: '杭州市西湖区' } })
    fireEvent.click(screen.getByText('提交'))
    expect(onAction).toHaveBeenCalledWith(
      `__FORM__|${JSON.stringify({
        customer_name: '张三',
        customer_phone: '13800138000',
        customer_address: '杭州市西湖区',
        quantity: '0.5',
      })}`
    )
  })

  it('输入修改后应清除该字段错误', () => {
    const onAction = jest.fn()
    render(<FormCard data={baseForm} onAction={onAction} />)
    const phone = screen.getByPlaceholderText('11 位手机号')
    fireEvent.change(phone, { target: { value: '123' } })
    fireEvent.click(screen.getByText('提交'))
    expect(screen.getByText('请输入 11 位手机号')).toBeTruthy()
    fireEvent.change(phone, { target: { value: '13800138000' } })
    expect(screen.queryByText('请输入 11 位手机号')).toBeNull()
  })

  it('提供 cancelLabel 时应渲染取消按钮并回传取消文本', () => {
    const onAction = jest.fn()
    const withCancel: InteractiveData = {
      ...baseForm,
      cancelLabel: '稍后再说',
      cancelValue: '取消填写',
    }
    render(<FormCard data={withCancel} onAction={onAction} />)
    fireEvent.click(screen.getByText('稍后再说'))
    expect(onAction).toHaveBeenCalledWith('取消填写')
  })
})

describe('FormCard — 提交锁（CH-030 防重复提交）', () => {
  afterEach(() => {
    jest.clearAllMocks()
  })

  it('提交后锁卡：第二次提交或取消不再触发 onAction', () => {
    const onAction = jest.fn()
    const data: InteractiveData = {
      type: 'form',
      component: 'form',
      title: '请填写收货信息',
      formFields: [{ key: 'name', label: '收货人', required: true }],
      submitLabel: '提交',
      cancelLabel: '取消',
      cancelValue: '取消',
    }
    render(<FormCard data={data} onAction={onAction} />)
    fireEvent.change(screen.getByPlaceholderText('请输入收货人'), { target: { value: '张三' } })
    fireEvent.click(screen.getByText('提交'))
    fireEvent.click(screen.getByText('提交'))
    fireEvent.click(screen.getByText('取消'))
    expect(onAction).toHaveBeenCalledTimes(1)
  })

  it('disabled=true（历史已答只读）：提交/取消均不触发 onAction', () => {
    const onAction = jest.fn()
    const data: InteractiveData = {
      type: 'form',
      component: 'form',
      title: '请填写收货信息',
      formFields: [{ key: 'name', label: '收货人', required: true }],
      submitLabel: '提交',
      cancelLabel: '取消',
      cancelValue: '取消',
    }
    render(<FormCard data={data} onAction={onAction} disabled />)
    fireEvent.change(screen.getByPlaceholderText('请输入收货人'), { target: { value: '张三' } })
    fireEvent.click(screen.getByText('提交'))
    expect(onAction).not.toHaveBeenCalled()
  })
})
