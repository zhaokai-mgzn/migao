import React from 'react';

interface MibaoLogoProps {
  size?: number;
  className?: string;
}

export function MibaoLogo({ size = 32, className }: MibaoLogoProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 128 128"
      className={className}
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <linearGradient id="mibao-headGrad" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#3b82f6" />
          <stop offset="100%" stopColor="#2563eb" />
        </linearGradient>
        <linearGradient id="mibao-faceGrad" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor="#dbeafe" />
          <stop offset="100%" stopColor="#bfdbfe" />
        </linearGradient>
      </defs>
      {/* 天线 */}
      <line x1="64" y1="18" x2="64" y2="8" stroke="#3b82f6" strokeWidth="3" strokeLinecap="round" />
      <circle cx="64" cy="6" r="4" fill="#3b82f6" />
      <circle cx="64" cy="6" r="2" fill="#93c5fd" />
      {/* 左耳 */}
      <rect x="12" y="46" width="10" height="24" rx="5" fill="url(#mibao-headGrad)" />
      <rect x="14" y="50" width="6" height="16" rx="3" fill="#93c5fd" opacity="0.4" />
      {/* 右耳 */}
      <rect x="106" y="46" width="10" height="24" rx="5" fill="url(#mibao-headGrad)" />
      <rect x="108" y="50" width="6" height="16" rx="3" fill="#93c5fd" opacity="0.4" />
      {/* 头部主体 */}
      <rect x="22" y="18" width="84" height="80" rx="28" fill="url(#mibao-headGrad)" />
      {/* 面板/脸部 */}
      <rect x="32" y="34" width="64" height="50" rx="16" fill="url(#mibao-faceGrad)" />
      {/* 左眼 */}
      <ellipse cx="48" cy="54" rx="9" ry="10" fill="#2563eb" />
      <ellipse cx="48" cy="53" rx="6" ry="7" fill="#dbeafe" />
      <circle cx="46" cy="51" r="3" fill="#ffffff" />
      <circle cx="50" cy="56" r="1.5" fill="#ffffff" opacity="0.6" />
      {/* 右眼 */}
      <ellipse cx="80" cy="54" rx="9" ry="10" fill="#2563eb" />
      <ellipse cx="80" cy="53" rx="6" ry="7" fill="#dbeafe" />
      <circle cx="78" cy="51" r="3" fill="#ffffff" />
      <circle cx="82" cy="56" r="1.5" fill="#ffffff" opacity="0.6" />
      {/* 微笑 */}
      <path d="M52 70 Q64 80 76 70" stroke="#2563eb" strokeWidth="2.5" fill="none" strokeLinecap="round" />
      {/* 脸颊腮红 */}
      <ellipse cx="38" cy="68" rx="5" ry="3" fill="#93c5fd" opacity="0.5" />
      <ellipse cx="90" cy="68" rx="5" ry="3" fill="#93c5fd" opacity="0.5" />
      {/* 底部装饰条 */}
      <rect x="44" y="102" width="40" height="6" rx="3" fill="#3b82f6" />
      <rect x="54" y="112" width="20" height="5" rx="2.5" fill="#93c5fd" />
    </svg>
  );
}
