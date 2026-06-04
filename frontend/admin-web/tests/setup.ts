import '@testing-library/jest-dom'
import { vi, afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

// 每个测试后自动清理 DOM
afterEach(() => {
  cleanup()
})

// Mock next/navigation
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => '/',
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
  redirect: vi.fn(),
  notFound: vi.fn(),
}))

// Mock next/router (pages router)
vi.mock('next/router', () => ({
  useRouter: () => ({
    route: '/',
    pathname: '/',
    query: {},
    asPath: '/',
    push: vi.fn(),
    replace: vi.fn(),
    reload: vi.fn(),
    back: vi.fn(),
    prefetch: vi.fn().mockResolvedValue(undefined),
    beforePopState: vi.fn(),
    events: {
      on: vi.fn(),
      off: vi.fn(),
      emit: vi.fn(),
    },
    isFallback: false,
    isLocaleDomain: false,
    isReady: true,
    isPreview: false,
  }),
}))

// Mock sonner toast
vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
    loading: vi.fn(),
    dismiss: vi.fn(),
  },
}))

// Mock window.matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})

// Mock Element.prototype.scrollIntoView (jsdom 不支持)
Element.prototype.scrollIntoView = vi.fn()

// Mock lucide-react 图标
const iconStub = (name: string) => {
  const Component = (props: any) => {
    const React = require('react')
    return React.createElement('span', { 'data-testid': `icon-${name}`, ...props })
  }
  Component.displayName = name
  return Component
}

vi.mock('lucide-react', () => ({
  // 所有项目中使用的图标
  Plus: iconStub('plus'),
  X: iconStub('x'),
  ChevronUp: iconStub('chevron-up'),
  ChevronDown: iconStub('chevron-down'),
  ChevronLeft: iconStub('chevron-left'),
  ChevronRight: iconStub('chevron-right'),
  Search: iconStub('search'),
  Edit: iconStub('edit'),
  Trash2: iconStub('trash2'),
  Eye: iconStub('eye'),
  EyeOff: iconStub('eye-off'),
  Calendar: iconStub('calendar'),
  CalendarDays: iconStub('calendar-days'),
  RefreshCw: iconStub('refresh-cw'),
  MoreHorizontal: iconStub('more-horizontal'),
  Package: iconStub('package'),
  Image: iconStub('image'),
  ArrowUpDown: iconStub('arrow-up-down'),
  ClipboardList: iconStub('clipboard-list'),
  Users: iconStub('users'),
  MessageSquare: iconStub('message-square'),
  DollarSign: iconStub('dollar-sign'),
  FileUp: iconStub('file-up'),
  RotateCcw: iconStub('rotate-ccw'),
  Star: iconStub('star'),
  Tags: iconStub('tags'),
  Phone: iconStub('phone'),
  Mail: iconStub('mail'),
  MapPin: iconStub('map-pin'),
  Building2: iconStub('building2'),
  Shield: iconStub('shield'),
  ShieldCheck: iconStub('shield-check'),
  LogOut: iconStub('log-out'),
  User: iconStub('user'),
  Settings: iconStub('settings'),
  Bell: iconStub('bell'),
  Menu: iconStub('menu'),
  Home: iconStub('home'),
  ShoppingCart: iconStub('shopping-cart'),
  FileText: iconStub('file-text'),
  BarChart3: iconStub('bar-chart3'),
  BookOpen: iconStub('book-open'),
  Scissors: iconStub('scissors'),
  Bot: iconStub('bot'),
  Headphones: iconStub('headphones'),
  LayoutDashboard: iconStub('layout-dashboard'),
  Store: iconStub('store'),
  LucideIcon: iconStub('lucide-icon'),
  UserCircle: iconStub('user-circle'),
  Monitor: iconStub('monitor'),
  FolderTree: iconStub('folder-tree'),
  Zap: iconStub('zap'),
  Maximize2: iconStub('maximize2'),
  Minus: iconStub('minus'),
  Send: iconStub('send'),
  Loader2: iconStub('loader2'),
}))
