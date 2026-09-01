import { defineConfig, type UserConfigExport } from '@tarojs/cli'
import path from 'path'

export default defineConfig(async (merge) => {
  const baseConfig: UserConfigExport = {
    projectName: 'mini-app',
    date: '2025-01-01',
    designWidth: 750,
    deviceRatio: {
      640: 2.34 / 2,
      750: 1,
      828: 1.81 / 2,
      375: 2 / 1,
    },
    sourceRoot: 'src',
    outputRoot: 'dist',
    plugins: [],
    // 显式定义 TARO_APP_* 环境变量替换（webpack DefinePlugin），不依赖 .env 文件：
    // Taro 的 dotenv 机制只注入 .env/.env.local 中的变量，CI 无 .env 文件时产物会残留
    // process.env 引用导致浏览器端 `process is not defined` 白屏（issue #2693）。
    defineConstants: {
      'process.env.TARO_APP_API_URL': JSON.stringify(process.env.TARO_APP_API_URL || ''),
      'process.env.TARO_APP_AI_API_URL': JSON.stringify(process.env.TARO_APP_AI_API_URL || ''),
    },
    copy: {
      patterns: [],
      options: {},
    },
    framework: 'react',
    compiler: 'webpack5',
    cache: {
      enable: false,
    },
    mini: {
      postcss: {
        pxtransform: {
          enable: true,
          config: {},
        },
        url: {
          enable: true,
          config: {
            limit: 1024,
          },
        },
        cssModules: {
          enable: false,
          config: {
            namingPattern: 'module',
            generateScopedName: '[name]__[local]___[hash:base64:5]',
          },
        },
      },
    },
    h5: {
      publicPath: '/',
      staticDirectory: 'static',
      postcss: {
        autoprefixer: {
          enable: true,
          config: {},
        },
        cssModules: {
          enable: false,
          config: {
            namingPattern: 'module',
            generateScopedName: '[name]__[local]___[hash:base64:5]',
          },
        },
      },
    },
    alias: {
      '@': path.resolve(__dirname, '..', 'src'),
    },
  }
  return baseConfig
})
