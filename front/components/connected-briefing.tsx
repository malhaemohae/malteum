'use client';

import { useEffect, useState } from 'react';
import { ApiBriefing, malteumApi } from '../lib/api';

type ProductKey = 'deposit' | 'mortgage';
type Mode = 'replay' | 'live' | 'trace' | 'text';
type CustomerType = 'general' | 'professional';
type NavItem = '상담' | '리포트' | '규정 팩' | '문서' | '이력';

type BriefingConfig = {
  label: string;
  customer: string;
  productCode: string;
  packVersion: string;
  packStatus: 'published' | 'demo';
  totalSeconds: number;
  briefing: {
    recentChange: string;
    mustSay: string[];
    mustNotSay: string[];
    documents: string[];
  };
};

type Props = {
  product: ProductKey;
  mode: Mode;
  customerLabel: string;
  customerType: CustomerType;
  config: BriefingConfig;
  micActive: boolean;
  micError?: string;
  onBack: () => void;
  onStart: () => void;
  onNavigate: (value: NavItem) => void;
};

const navItems: Array<{ key: NavItem; number: string; icon: string }> = [
  { key: '상담', number: '01', icon: '◉' },
  { key: '리포트', number: '02', icon: '▤' },
  { key: '규정 팩', number: '03', icon: '◫' },
  { key: '문서', number: '04', icon: '▥' },
  { key: '이력', number: '05', icon: '◷' },
];

function formatTime(seconds: number) {
  return `${Math.floor(seconds / 60).toString().padStart(2, '0')}:${Math.floor(seconds % 60).toString().padStart(2, '0')}`;
}

function modeLabel(mode: Mode) {
  return mode === 'replay' ? 'REPLAY' : mode === 'live' ? 'LIVE' : mode === 'trace' ? 'TRACE' : 'TEXT';
}

function productLabel(product: ProductKey) {
  return product === 'mortgage' ? '주택담보대출' : '예적금 중도해지';
}

function ConnectedBriefingScreen({ product, mode, customerLabel, customerType, config, micActive, micError, onBack, onStart, onNavigate }: Props) {
  const [remote, setRemote] = useState<ApiBriefing | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'fallback'>('loading');

  useEffect(() => {
    let active = true;
    setRemote(null);
    setState('loading');
    malteumApi.briefing(config.packVersion, customerType).then((value) => {
      if (!active) return;
      if (value.pack_version === config.packVersion) {
        setRemote(value);
        setState('ready');
      } else {
        setState('fallback');
      }
    }).catch(() => {
      if (active) setState('fallback');
    });
    return () => { active = false; };
  }, [config.packVersion, customerType]);

  const mustSay = remote?.must_say?.length ? remote.must_say.map((item) => item.name) : config.briefing.mustSay;
  const mustNotSay = remote?.must_not_say?.length ? remote.must_not_say.map((item) => item.examples?.[0] || item.name) : config.briefing.mustNotSay;
  const statusLabel = state === 'ready' ? '서버 브리핑 연결됨' : state === 'loading' ? '브리핑 확인 중' : '로컬 기준 · 서버 대체';
  const recentChange = remote?.generated_at ? `서버 생성 ${new Date(remote.generated_at).toLocaleString('ko-KR')} · ${remote.cached ? '캐시된 발행본' : '서버 생성본'}` : config.briefing.recentChange;
  const inputNote = mode === 'live'
    ? micActive
      ? '마이크가 연결되었습니다. 상담 화면에서 녹음·전사·판정이 이어집니다.'
      : micError || '상담 화면에서 녹음 시작 버튼을 눌러 입력을 켭니다.'
    : mode === 'replay'
      ? '준비된 녹취가 상담 화면에서 입력으로 재생됩니다.'
      : mode === 'text'
        ? '상담 화면에서 발화를 직접 입력해 같은 판정 경로를 사용합니다.'
        : '저장된 이벤트를 상담 화면에서 순서대로 재생합니다.';
  const startLabel = '상담 화면으로 이동';

  return <div className="product-app">
    <aside className="sidebar">
      <div className="sidebar-top"><div className="brand-mark brand-mark-dark"><img className="brand-logo" src="/assets/malteum-logo.png" alt="말틈" /></div><span className="workspace-label">상담 지원 워크스페이스</span></div>
      <div className="sidebar-session"><span>현재 세션</span><strong>{productLabel(product)}</strong><span className="sidebar-session-id">세션 생성 전</span></div>
      <nav className="sidebar-nav" aria-label="주 메뉴">{navItems.map((item) => <button className={`nav-item${item.key === '상담' ? ' is-active' : ''}`} key={item.key} type="button" onClick={() => onNavigate(item.key)}><span className="nav-number" aria-hidden="true">{item.number}</span><span className="nav-icon" aria-hidden="true">{item.icon}</span><span>{item.key}</span></button>)}</nav>
      <div className="sidebar-bottom"><div className="sidebar-helper"><div className="helper-avatar" aria-hidden="true">✓</div><div><strong>기준 가이드</strong><span>근거 기반 안내</span></div></div><button className="sidebar-new" type="button" onClick={onBack}><span aria-hidden="true">＋</span> 새 상담</button></div>
    </aside>
    <main className="workspace-main">
      <header className="workspace-heading"><div><span className="section-eyebrow">상담 브리핑</span><h1>이번 상담의 기준을 먼저 확인하세요.</h1><p>상담 중 필요한 항목과 피해야 할 표현을 짧게 확인한 뒤 라이브 화면으로 이동합니다.</p></div><div className="workspace-heading-action"><span className="demo-pill">{statusLabel}</span></div></header>
      <section className="briefing-card" data-tutorial="briefing-card"><div className="briefing-card-header"><div><span className="section-eyebrow">선택한 세션</span><h2>{config.label}</h2><p>{customerLabel || config.customer} · {modeLabel(mode)} · {customerType === 'professional' ? '전문금융소비자' : '일반금융소비자'} · {config.packVersion}</p></div><span className={`pack-status pack-status-${config.packStatus}`}>{config.packStatus === 'published' ? '발행 팩' : '데모 팩'}</span></div><div className="briefing-metrics"><div><strong>{mustSay.length}</strong><span>필수 안내</span></div><div><strong>{mustNotSay.length}</strong><span>주의 표현</span></div><div><strong>{formatTime(config.totalSeconds)}</strong><span>예상 시연</span></div></div><div className="briefing-columns"><div><span className="section-eyebrow">이번 상담에서 꼭 말할 것</span><ul>{mustSay.map((item) => <li key={item}><span className="status-mark status-met" aria-hidden="true">✓</span><span>{item}</span></li>)}</ul></div><div><span className="section-eyebrow">주의할 안내</span><ul className="briefing-warning-list">{mustNotSay.map((item) => <li key={item}><span className="briefing-warning-mark">!</span><span>{item}</span></li>)}</ul></div></div><div className="briefing-note"><span className="note-dot" aria-hidden="true" /><span><strong>입력 준비</strong>{inputNote}</span></div><div className="briefing-note"><span className="note-dot" aria-hidden="true" /><span><strong>최근 기준</strong>{recentChange}</span></div><div className="briefing-actions"><button type="button" className="text-button" onClick={onBack}>설정으로 돌아가기</button><button type="button" className="dark-button" onClick={onStart}>{startLabel} <span aria-hidden="true">↗</span></button></div></section>
    </main>
  </div>;
}

export default ConnectedBriefingScreen;
