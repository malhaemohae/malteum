import type { Metadata } from 'next';
import './globals.css';
import './workspace.css';
import './workspace-service.css';
import './workspace-feedback.css';
import './landing-showcase.css';

export const metadata: Metadata = {
  title: '말틈 — 상담 컴플라이언스',
  description: '규정과 상품설명서 기준으로 상담을 확인하는 말틈 견본 화면',
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
