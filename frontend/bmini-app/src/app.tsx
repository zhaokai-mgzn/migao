import { useEffect, useRef, PropsWithChildren } from 'react'
import { useAuthStore } from './store/authStore'
import { setupErrorHandler, setupNetworkListener } from './utils/errorHandler'
import './app.scss'

function App({ children }: PropsWithChildren) {
  const initialized = useRef(false)

  useEffect(() => {
    if (initialized.current) return
    initialized.current = true

    // 初始化全局错误处理
    setupErrorHandler()

    // 初始化网络状态监听
    setupNetworkListener()

    // 初始化认证状态
    useAuthStore.getState().initialize()
  }, [])

  return children
}

export default App
