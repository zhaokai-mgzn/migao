import React from 'react';

interface MibaoLogoProps {
  size?: number;
  className?: string;
}

/** 米宝 AI 助手 Logo — 简洁几何机器人头像 */
export function MibaoLogo({ size = 32, className }: MibaoLogoProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 80 80"
      className={className}
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <linearGradient id="mb-head" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#6366f1" />
          <stop offset="100%" stopColor="#4f46e5" />
        </linearGradient>
        <linearGradient id="mb-face" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor="#eef2ff" />
          <stop offset="100%" stopColor="#e0e7ff" />
        </linearGradient>
      </defs>
      {/* 头部 */}
      <rect x="8" y="10" width="64" height="56" rx="20" fill="url(#mb-head)" />
      {/* 脸部面板 */}
      <rect x="16" y="22" width="48" height="36" rx="12" fill="url(#mb-face)" />
      {/* 左眼 */}
      <circle cx="30" cy="36" r="6" fill="#4f46e5" />
      <circle cx="28" cy="34" r="2.5" fill="white" />
      {/* 右眼 */}
      <circle cx="50" cy="36" r="6" fill="#4f46e5" />
      <circle cx="48" cy="34" r="2.5" fill="white" />
      {/* 微笑 */}
      <path d="M32 48 Q40 54 48 48" stroke="#4f46e5" strokeWidth="2" fill="none" strokeLinecap="round" />
    </svg>
  );
}
