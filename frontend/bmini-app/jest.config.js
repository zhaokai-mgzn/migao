/** @type {import('jest').Config} */
module.exports = {
  preset: 'ts-jest',
  testEnvironment: 'jsdom',
  roots: ['<rootDir>/tests'],
  setupFiles: ['<rootDir>/tests/setup.ts'],
  moduleNameMapper: {
    // 路径别名 @/* -> src/*
    '^@/(.*)$': '<rootDir>/src/$1',
    // Mock Taro
    '^@tarojs/taro$': '<rootDir>/tests/__mocks__/@tarojs/taro.ts',
    '^@tarojs/components$': '<rootDir>/tests/__mocks__/@tarojs/components.tsx',
    '^@tarojs/react$': '<rootDir>/tests/__mocks__/@tarojs/react.ts',
    // 忽略样式文件
    '\\.(css|scss|sass|less)$': '<rootDir>/tests/__mocks__/styleMock.ts',
    // 忽略图片
    '\\.(png|jpg|jpeg|gif|svg)$': '<rootDir>/tests/__mocks__/fileMock.ts',
  },
  transform: {
    '^.+\\.tsx?$': ['ts-jest', {
      tsconfig: {
        jsx: 'react-jsx',
        module: 'commonjs',
        esModuleInterop: true,
        allowSyntheticDefaultImports: true,
        strict: true,
        noImplicitAny: false,
        baseUrl: './',
        paths: { '@/*': ['./src/*'] },
      },
    }],
  },
  testMatch: ['<rootDir>/tests/**/*.test.{ts,tsx}'],
  moduleFileExtensions: ['ts', 'tsx', 'js', 'jsx', 'json'],
  collectCoverageFrom: [
    'src/**/*.{ts,tsx}',
    '!src/**/*.d.ts',
    '!src/**/*.scss',
    '!src/app.tsx',
    '!src/app.config.ts',
  ],
}
