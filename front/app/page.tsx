'use client';

import { FormEvent, useEffect, useState } from 'react';

type ProductKey = 'deposit' | 'mortgage';
type Mode = 'replay' | 'live' | 'text';
type ChecklistStatus = 'met' | 'partial' | 'pending';

type ChecklistItem = {
  label: string;
  status: ChecklistStatus;
  source: string;
};

type ProductConfig = {
  label: string;
  customer: string;
  document: string;
  page: string;
  intervention: {
    type: string;
    title: string;
    body: string;
    quote: string;
    source: string;
    spoken: string;
    reference: string;
    caption: string;
  };
  timeline: {
    position: string;
    total: string;
    intervention: string;
  };
  checklist: ChecklistItem[];
  queryAnswer: string;
};

const productConfigs: Record<ProductKey, ProductConfig> = {
  deposit: {
    label: '예적금 중도해지',
    customer: '가상 고객 A',
    document: '신한 My플러스 정기예금 상품설명서',
    page: 'p.3',
    intervention: {
      type: '숫자 오류',
      title: '설명서 기준으로 확인해 주세요',
      body: '은행원이 말한 중도해지 이자율과 상품설명서 기준이 다릅니다.',
      quote: '“중도해지하시면 0.5% 정도는 받으세요.”',
      source: '상품설명서 p.3 · 중도해지 이자율',
      spoken: '0.5%',
      reference: '연 0.10%',
      caption: '가입 1개월 미만 기준',
    },
    timeline: {
      position: '00:35',
      total: '03:30',
      intervention: '00:35',
    },
    checklist: [
      { label: '우대이자율 미적용', status: 'met', source: '상품설명서 p.2' },
      { label: '중도해지 이자율', status: 'partial', source: '상품설명서 p.3' },
      { label: '만기후이자율', status: 'pending', source: '상품설명서 p.3' },
      { label: '일부해지 대안', status: 'pending', source: '상품설명서 p.4' },
      { label: '예금담보대출 대안', status: 'pending', source: '상품설명서 p.4' },
    ],
    queryAnswer: '만기 후 1개월 이내는 만기일 당시 일반정기예금 이율을 적용하고, 6개월을 넘기면 연 0.10%로 내려갑니다.',
  },
  mortgage: {
    label: '주택담보대출',
    customer: '가상 고객 B',
    document: '가계대출 상품설명서',
    page: 'p.12',
    intervention: {
      type: '금지 발언',
      title: '확정 전 안내임을 함께 표시해 주세요',
      body: '내부 결재 전 상담에서는 금리나 한도를 확정된 것처럼 안내하면 안 됩니다.',
      quote: '“이 금리로 확정이라고 보시면 돼요.”',
      source: '가계대출 상품설명서 p.12 · 금리 안내',
      spoken: '확정',
      reference: '심사·결재 후 확정',
      caption: '상담 단계 기준',
    },
    timeline: {
      position: '01:00',
      total: '04:00',
      intervention: '01:00',
    },
    checklist: [
      { label: 'LTV·담보인정비율', status: 'met', source: '상품설명서 p.12' },
      { label: '확정 전 안내', status: 'partial', source: '상품설명서 p.12' },
      { label: '중도상환수수료', status: 'pending', source: '상품설명서 p.2' },
      { label: '금리인하요구권', status: 'pending', source: '상품설명서 p.14' },
      { label: '필요 서류', status: 'pending', source: '상품설명서 p.3' },
    ],
    queryAnswer: '근저당은 대출을 담보하기 위해 부동산에 설정하는 권리입니다. 설정 비용과 말소 절차는 상품과 기관의 안내를 확인해야 합니다.',
  },
};

const modeLabels: Record<Mode, string> = {
  replay: 'REPLAY',
  live: 'LIVE',
  text: 'TEXT',
};

const modeDescriptions: Record<Mode, string> = {
  replay: '녹취 재생 · 기본',
  live: '실시간 녹음',
  text: '음성 없이 검토',
};

type AppScreen = 'landing' | 'dashboard';

type TutorialStep = {
  screen: AppScreen;
  target: string;
  label: string;
  title: string;
  body: string;
  button: string;
  spotlight?: {
    padding: number;
    radius: string;
  };
};

const tutorialSteps: TutorialStep[] = [
  {
    screen: 'landing',
    target: 'landing-hero',
    label: '01 · 시작 전 안내',
    title: '상담 전에 필요한 기준을 먼저 준비해요.',
    body: '말틈은 상품설명서와 규정에서 꼭 확인할 항목을 골라 상담 흐름에 맞춰 보여줍니다.',
    button: '다음으로',
  },
  {
    screen: 'landing',
    target: 'landing-start',
    label: '02 · 녹음 시작',
    title: '입력 없이 녹음으로 바로 시작해요.',
    body: '기본 시연은 준비된 녹취를 재생하고, LIVE를 고르면 녹음 고지 후 실시간 분석으로 이어집니다. 상담 유형과 모드는 세션 설정에서 바꿀 수 있어요.',
    button: '대시보드 보기',
  },
  {
    screen: 'dashboard',
    target: 'dashboard-header',
    label: '03 · 실시간 상태',
    title: '상담 연결 상태와 실행 모드를 확인해요.',
    body: '상단 상태 영역에서 연결 여부, REPLAY·LIVE·TEXT 모드와 상담 시간, 새 상담 시작 버튼을 확인합니다.',
    button: '다음으로',
    spotlight: { padding: 6, radius: '16px' },
  },
  {
    screen: 'dashboard',
    target: 'dashboard-recording',
    label: '04 · 녹음·분석',
    title: '녹음이 전사의 시작점입니다.',
    body: '오디오 흐름은 녹음·전사·판정·근거 순서로 이어집니다. 지금 재생 중인 구간과 자동 분석 상태를 한 줄에서 확인합니다.',
    button: '다음으로',
    spotlight: { padding: 4, radius: '16px' },
  },
  {
    screen: 'dashboard',
    target: 'dashboard-overview',
    label: '05 · 한눈에 보는 요약',
    title: '지금 어떤 상담인지 한 줄로 고정해둡니다.',
    body: '상담 상품, 고객 라벨, 사용 문서와 함께 필수 안내 수·개입 필요 건수·상담 상태를 한곳에서 봅니다.',
    button: '다음으로',
    spotlight: { padding: 4, radius: '16px' },
  },
  {
    screen: 'dashboard',
    target: 'dashboard-attention',
    label: '06 · 핵심 개입',
    title: '놓치면 안 되는 순간은 가장 크게 알려줘요.',
    body: '현재 발화와 설명서 기준을 나란히 비교합니다. 근거 원문 보기를 누르면 해당 문서 구간을 바로 확인할 수 있어요.',
    button: '다음으로',
    spotlight: { padding: 4, radius: '16px' },
  },
  {
    screen: 'dashboard',
    target: 'dashboard-transcript',
    label: '07 · 실시간 전사',
    title: '상담의 맥락은 전사 흐름으로 남습니다.',
    body: '은행원과 고객의 발화를 시간 순서대로 보고, 문제가 감지된 문장은 색으로 구분해 다시 찾기 쉽게 합니다.',
    button: '다음으로',
    spotlight: { padding: 4, radius: '16px' },
  },
  {
    screen: 'dashboard',
    target: 'dashboard-query',
    label: '08 · 규정 질의',
    title: '규정을 직접 물어볼 수도 있어요.',
    body: '상담 중 궁금한 내용을 입력하면 바름이가 짧은 답변과 연결된 근거를 함께 보여줍니다.',
    button: '다음으로',
    spotlight: { padding: 4, radius: '14px' },
  },
  {
    screen: 'dashboard',
    target: 'dashboard-checklist',
    label: '09 · 필수 안내',
    title: '필수 안내가 어디까지 진행됐는지 보여줘요.',
    body: '고지·부분·미고지 상태를 구분하고, 항목을 누르면 오른쪽 근거 카드가 해당 내용으로 바뀝니다.',
    button: '다음으로',
    spotlight: { padding: 4, radius: '16px' },
  },
  {
    screen: 'dashboard',
    target: 'dashboard-evidence',
    label: '10 · 근거 확인',
    title: '모든 안내는 문서 근거로 확인합니다.',
    body: '선택한 항목의 문서와 페이지를 미리 보고, 원문 전체 보기에서 실제 근거 구간을 열어 검토할 수 있어요.',
    button: '튜토리얼 끝내기',
    spotlight: { padding: 4, radius: '16px' },
  },
];

function BrandMark({ dark = false }: { dark?: boolean }) {
  return (
    <div className={`brand-mark${dark ? ' brand-mark-dark' : ''}`}>
      <img className="brand-logo" src="/assets/malteum-logo.png" alt="말틈" />
    </div>
  );
}

function StatusMark({ status }: { status: ChecklistStatus }) {
  return (
    <span className={`status-mark status-${status}`} aria-hidden="true">
      {status === 'met' ? '✓' : status === 'partial' ? '◐' : ''}
    </span>
  );
}

function Mascot({ small = false }: { small?: boolean }) {
  return (
    <img
      className={`mascot${small ? ' mascot-small' : ''}`}
      src="/assets/malteum-mascot.png"
      alt="바름이 캐릭터"
    />
  );
}

type TargetRect = {
  top: number;
  left: number;
  right: number;
  bottom: number;
  borderRadius: string;
};

function TutorialOverlay({
  screen,
  stepIndex,
  onNext,
  onPrevious,
  onSkip,
}: {
  screen: AppScreen;
  stepIndex: number;
  onNext: () => void;
  onPrevious: () => void;
  onSkip: () => void;
}) {
  const step = tutorialSteps[stepIndex];
  const [targetRect, setTargetRect] = useState<TargetRect | null>(null);
  const [dialogPlacement, setDialogPlacement] = useState<'bottom' | 'top'>('bottom');

  useEffect(() => {
    let frame = 0;
    let settleFrame = 0;
    setTargetRect(null);
    setDialogPlacement('bottom');

    function measureTarget() {
      const target = document.querySelector(`[data-tutorial="${step.target}"]`);
      if (!target) {
        setTargetRect(null);
        setDialogPlacement('bottom');
        return;
      }

      const rect = target.getBoundingClientRect();
      const dialog = document.querySelector('.tutorial-dialog');
      const dialogHeight = dialog?.getBoundingClientRect().height ?? 150;
      const compactViewport = window.matchMedia('(max-width: 680px)').matches;
      const bottomOffset = compactViewport ? 12 : 24;
      const topOffset = compactViewport ? 12 : 14;
      const bottomDialogTop = window.innerHeight - dialogHeight - bottomOffset;
      const topDialogBottom = topOffset + dialogHeight;
      const dialogGap = 18;
      const fitsBottom = rect.bottom <= bottomDialogTop - dialogGap;
      const fitsTop = rect.top >= topDialogBottom + dialogGap;
      setDialogPlacement((current) => {
        const next = !fitsBottom && fitsTop ? 'top' : 'bottom';
        return current === next ? current : next;
      });
      setTargetRect({
        top: rect.top,
        left: rect.left,
        right: rect.right,
        bottom: rect.bottom,
        borderRadius: getComputedStyle(target).borderRadius,
      });
    }

    const target = document.querySelector(`[data-tutorial="${step.target}"]`);
    const dialog = document.querySelector('.tutorial-dialog');
    if (target && step.target === 'landing-hero') {
      // The first landing step must preserve the brand header as the user's entry point.
      window.scrollTo({ top: 0, behavior: 'auto' });
    } else if (target) {
      const targetRect = target.getBoundingClientRect();
      const dialogHeight = dialog?.getBoundingClientRect().height ?? 150;
      const topInset = 18;
      const bottomInset = dialogHeight + 52;
      const safeHeight = Math.max(160, window.innerHeight - topInset - bottomInset);
      const desiredTop = targetRect.height > safeHeight
        ? topInset
        : topInset + (safeHeight - targetRect.height) / 2;
      const maxScrollTop = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
      const nextScrollTop = Math.min(
        maxScrollTop,
        Math.max(0, window.scrollY + targetRect.top - desiredTop),
      );
      window.scrollTo({ top: nextScrollTop, behavior: 'auto' });
    }

    frame = window.requestAnimationFrame(() => {
      measureTarget();
      settleFrame = window.requestAnimationFrame(measureTarget);
    });
    window.addEventListener('resize', measureTarget);
    window.addEventListener('scroll', measureTarget, { passive: true });

    return () => {
      window.cancelAnimationFrame(frame);
      window.cancelAnimationFrame(settleFrame);
      window.removeEventListener('resize', measureTarget);
      window.removeEventListener('scroll', measureTarget);
    };
  }, [screen, step.target]);

  if (!step) return null;

  const padding = step.spotlight?.padding ?? 0;
  const spotlightSafeMargin = 8;
  const focus = targetRect
    ? {
        top: Math.max(spotlightSafeMargin, targetRect.top - padding),
        left: Math.max(spotlightSafeMargin, targetRect.left - padding),
        right: Math.min(window.innerWidth - spotlightSafeMargin, targetRect.right + padding),
        bottom: Math.min(window.innerHeight - spotlightSafeMargin, targetRect.bottom + padding),
      }
    : null;
  const focusBorderRadius = step.spotlight?.radius ?? targetRect?.borderRadius ?? '0px';

  return (
    <>
      {focus ? (
        <>
          <div className="tutorial-shade tutorial-shade-top tutorial-shade-hit-area" style={{ height: `${focus.top}px` }} />
          <div className="tutorial-shade tutorial-shade-left tutorial-shade-hit-area" style={{ top: `${focus.top}px`, width: `${focus.left}px`, height: `${focus.bottom - focus.top}px` }} />
          <div className="tutorial-shade tutorial-shade-right tutorial-shade-hit-area" style={{ top: `${focus.top}px`, left: `${focus.right}px`, height: `${focus.bottom - focus.top}px` }} />
          <div className="tutorial-shade tutorial-shade-bottom tutorial-shade-hit-area" style={{ top: `${focus.bottom}px` }} />
          <div
            className="tutorial-focus-frame"
            aria-hidden="true"
            style={{
              top: `${focus.top}px`,
              left: `${focus.left}px`,
              width: `${focus.right - focus.left}px`,
              height: `${focus.bottom - focus.top}px`,
              borderRadius: focusBorderRadius,
            }}
          />
        </>
      ) : (
        <div className="tutorial-shade tutorial-shade-full" />
      )}

      <section className={`tutorial-dialog${dialogPlacement === 'top' ? ' tutorial-dialog-above' : ''}`} role="dialog" aria-labelledby="tutorial-title" aria-describedby="tutorial-body">
        <div className="tutorial-mascot-wrap">
          <Mascot />
        </div>
        <div className="tutorial-dialog-content">
          <div className="tutorial-dialog-topline">
            <span>{step.label}</span>
            <button className="tutorial-skip" type="button" onClick={onSkip}>건너뛰기</button>
          </div>
          <h2 id="tutorial-title">{step.title}</h2>
          <p id="tutorial-body">{step.body}</p>
          <div className="tutorial-dialog-actions">
            <button className="tutorial-previous" type="button" onClick={onPrevious} disabled={stepIndex === 0}>이전</button>
            <span className="tutorial-progress">{String(stepIndex + 1).padStart(2, '0')} / {String(tutorialSteps.length).padStart(2, '0')}</span>
            <button className="dark-button tutorial-next" type="button" onClick={onNext}>{step.button} <span aria-hidden="true">↗</span></button>
          </div>
        </div>
      </section>
    </>
  );
}

function Landing({
  product,
  mode,
  customerLabel,
  tutorialTarget,
  onProductChange,
  onModeChange,
  onCustomerChange,
  onStart,
}: {
  product: ProductKey;
  mode: Mode;
  customerLabel: string;
  tutorialTarget: string;
  onProductChange: (value: ProductKey) => void;
  onModeChange: (value: Mode) => void;
  onCustomerChange: (value: string) => void;
  onStart: () => void;
}) {
  const current = productConfigs[product];

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onStart();
  }

  return (
    <main className="landing-page">
      <header className="landing-topbar">
        <BrandMark />
        <div className="landing-nav" aria-label="보조 메뉴">
          <span>규정 팩</span>
          <span>문서 추출</span>
          <span>세션 이력</span>
        </div>
      </header>

      <div className="landing-grid">
        <section className="landing-story" aria-labelledby="landing-title">
          <div className={`landing-hero-copy${tutorialTarget === 'landing-hero' ? ' tutorial-focus' : ''}`} data-tutorial="landing-hero">
            <div className="eyebrow eyebrow-cyan">실시간 금융 상담 컴플라이언스</div>
            <h1 id="landing-title">
              외우지 않아도,
              <br />
              <span>빠뜨리지 않습니다</span>
            </h1>
            <p className="landing-description">
              규정과 상품설명서에서 뽑은 항목을 녹음·전사 흐름에서 하나씩 확인하고,
              <br className="desktop-break" />
              설명했다는 근거를 남깁니다.
            </p>
          </div>

          <div className="verification-stage" aria-label="말틈이 확인하는 상담 흐름">
            <div className="landing-recording-badge" aria-hidden="true">
              <span className="landing-recording-dot" />
              <span className="landing-recording-bars"><i /><i /><i /><i /><i /></span>
              <span>녹음 대기 중</span>
            </div>
            <div className="verification-signal signal-one" aria-hidden="true" />
            <div className="verification-signal signal-two" aria-hidden="true" />
            <div className="verification-note">
              <span className="note-label">말틈이 지키는 흐름</span>
              <strong>녹음 → 전사 → 판정 → 근거<br />필요한 순간에 먼저 보여요.</strong>
            </div>
            <div className="verification-floor" aria-hidden="true" />
            <div className="verification-stack" aria-hidden="true">
              <div className="verification-sheet verification-sheet-back" />
              <div className="verification-sheet verification-sheet-mid" />
              <div className="verification-sheet verification-sheet-front">
                <div className="verification-sheet-header"><span>상담 기준</span><span>p.3</span></div>
                <div className="verification-sheet-row"><span className="verification-sheet-dot" /><span /><span /></div>
                <div className="verification-sheet-row"><span className="verification-sheet-dot verification-sheet-dot-cyan" /><span /><span /></div>
                <div className="verification-sheet-status"><span>근거 확인</span><strong>✓</strong></div>
              </div>
            </div>
          </div>
        </section>

        <form className="session-card" onSubmit={handleSubmit}>
          <div className="card-kicker">
            <span className="kicker-line" aria-hidden="true" />
            상담 세션 시작
          </div>
          <h2>녹음으로 시작하세요.</h2>
          <p className="card-intro">상담을 시작하면 전사와 기준 확인이 바로 이어집니다.</p>

          <button className={`record-button${tutorialTarget === 'landing-start' ? ' tutorial-focus' : ''}`} data-tutorial="landing-start" type="submit">
            <span className="record-button-visual" aria-hidden="true">
              <span className="record-button-ring" />
              <span className="record-button-mic">●</span>
            </span>
            <span className="record-button-copy">
              <strong>녹음으로 시작하기</strong>
              <small>{mode === 'live' ? '고지 후 실시간 녹음' : mode === 'text' ? '음성 없이 텍스트로 검토' : '준비된 녹취를 재생하며 자동 체크'}</small>
            </span>
            <span className="record-button-arrow" aria-hidden="true">↗</span>
          </button>

          <div className={`recording-helper recording-helper-${mode}`}>
            <span className="recording-pulse" aria-hidden="true" />
            <span>
              <strong>{mode === 'live' ? '녹음 고지 후 시작' : mode === 'text' ? '텍스트 검토 준비' : '녹취 자동 체크 준비'}</strong>
              <small>{current.label} · {current.customer}</small>
            </span>
            <span className="recording-duration">{current.timeline.total}</span>
          </div>

          <details className="landing-settings">
            <summary>
              <span className="settings-summary-label">세션 설정</span>
              <span className="settings-summary-value">{current.label} · {modeLabels[mode]}</span>
              <span className="settings-summary-arrow" aria-hidden="true">⌄</span>
            </summary>
            <div className="settings-panel">
              <fieldset className="choice-fieldset">
                <legend>상담 유형</legend>
                <div className="product-options">
                  {(Object.keys(productConfigs) as ProductKey[]).map((key) => {
                    const item = productConfigs[key];
                    const selected = key === product;
                    return (
                      <button
                        className={`product-option${selected ? ' is-selected' : ''}`}
                        key={key}
                        type="button"
                        aria-pressed={selected}
                        onClick={() => onProductChange(key)}
                      >
                        <span className="option-radio" aria-hidden="true">
                          {selected ? <span /> : null}
                        </span>
                        <span>
                          <strong>{item.label}</strong>
                          <small>{key === 'deposit' ? '3분 30초 시연' : '4분 시연'}</small>
                        </span>
                        <span className="option-arrow" aria-hidden="true">↗</span>
                      </button>
                    );
                  })}
                </div>
              </fieldset>

              <fieldset className="choice-fieldset mode-fieldset">
                <legend>실행 모드</legend>
                <div className="mode-options">
                  {(Object.keys(modeLabels) as Mode[]).map((key) => (
                    <button
                      className={`mode-option${key === mode ? ' is-selected' : ''}`}
                      key={key}
                      type="button"
                      aria-pressed={key === mode}
                      onClick={() => onModeChange(key)}
                    >
                      {modeLabels[key]}
                      <small>{modeDescriptions[key]}</small>
                    </button>
                  ))}
                </div>
              </fieldset>

              <label className="text-field">
                <span>가상 고객 라벨 <em>선택</em></span>
                <input
                  value={customerLabel}
                  onChange={(event) => onCustomerChange(event.target.value)}
                  placeholder={current.customer}
                  aria-label="가상 고객 라벨"
                />
              </label>
            </div>
          </details>

          <p className="privacy-note">
            <span className="tiny-lock" aria-hidden="true">□</span>
            실제 개인정보는 입력하지 않습니다.
          </p>

          <div className="session-card-footer">
            <span>녹음</span>
            <span>전사</span>
            <span>판정</span>
            <span>근거</span>
            <span className="footer-dot" aria-hidden="true" />
            <span>바로 대시보드로 이동</span>
          </div>
        </form>
      </div>

      <footer className="landing-footer">
        <span>말틈 · 금융 상담을 위한 근거 기반 가이드</span>
        <span className="footer-status"><span aria-hidden="true" /> 시스템 준비됨</span>
      </footer>
    </main>
  );
}

function Sidebar({
  product,
  activeNav,
  onNavChange,
  onNewSession,
}: {
  product: ProductKey;
  activeNav: string;
  onNavChange: (value: string) => void;
  onNewSession: () => void;
}) {
  const navItems = [
    ['상담', '01', '⌁'],
    ['리포트', '02', '▥'],
    ['규정 팩', '03', '◈'],
    ['문서', '04', '▤'],
    ['이력', '05', '↺'],
  ];

  return (
    <aside className="sidebar">
      <div className="sidebar-top">
        <BrandMark dark />
        <span className="workspace-label">상담 지원 워크스페이스</span>
      </div>

      <div className="sidebar-session">
        <span>현재 세션</span>
        <strong>{productConfigs[product].label}</strong>
        <span className="sidebar-session-id">SESSION · 0828-A</span>
      </div>

      <nav className="sidebar-nav" aria-label="주 메뉴">
        {navItems.map(([label, number, icon]) => (
          <button
            className={`nav-item${activeNav === label ? ' is-active' : ''}`}
            key={label}
            type="button"
            onClick={() => onNavChange(label)}
          >
            <span className="nav-number" aria-hidden="true">{number}</span>
            <span className="nav-icon" aria-hidden="true">{icon}</span>
            <span>{label}</span>
            {label === '리포트' ? <span className="nav-count">1</span> : null}
          </button>
        ))}
      </nav>

      <div className="sidebar-bottom">
        <div className="sidebar-helper">
          <div className="helper-avatar" aria-hidden="true">✓</div>
          <div>
            <strong>기준 가이드</strong>
            <span>근거 기반 안내</span>
          </div>
        </div>
        <button className="sidebar-new" type="button" onClick={onNewSession}>
          <span aria-hidden="true">＋</span> 새 상담
        </button>
      </div>
    </aside>
  );
}

function Dashboard({
  product,
  mode,
  customerLabel,
  tutorialTarget,
  activeNav,
  onNavChange,
  onNewSession,
}: {
  product: ProductKey;
  mode: Mode;
  customerLabel: string;
  tutorialTarget: string;
  activeNav: string;
  onNavChange: (value: string) => void;
  onNewSession: () => void;
}) {
  const config = productConfigs[product];
  const recordingInfo = mode === 'live'
    ? {
        label: '녹음·분석 중',
        detail: '고지 완료 · 마이크 입력',
        position: config.timeline.position,
        progress: product === 'deposit' ? 17 : 25,
      }
    : mode === 'text'
      ? {
          label: '텍스트 분석 중',
          detail: '음성 없이 동일 판정 경로',
          position: '—',
          progress: 0,
        }
      : {
          label: '녹취 재생 중',
          detail: 'REPLAY · 음성 자동 체크',
          position: config.timeline.position,
          progress: product === 'deposit' ? 17 : 25,
        };
  const [selectedItem, setSelectedItem] = useState(1);
  const [showEvidence, setShowEvidence] = useState(false);
  const [interventionResolved, setInterventionResolved] = useState(false);
  const [query, setQuery] = useState('');
  const [queryAsked, setQueryAsked] = useState(false);
  const completedCount = config.checklist.filter((item) => item.status === 'met').length;
  const selectedChecklist = config.checklist[selectedItem];
  const transcriptRows = product === 'deposit'
    ? [
        { speaker: '고객', text: '지금 해지하면 얼마나 받을 수 있어요?', time: '00:05' },
        { speaker: '은행원', text: '우대이자율은 중도해지하시면 적용이 안 되고요, 기준에 따라 안내드릴게요.', time: '00:15' },
        { speaker: '은행원', text: config.intervention.quote.replaceAll('“', '').replaceAll('”', ''), time: '00:35', highlighted: true },
        { speaker: '고객', text: '네? 중간에 깨면 그것밖에 못 받아요?', time: '01:10' },
      ]
    : [
        { speaker: '고객', text: '가능한 금리와 한도가 어떻게 되나요?', time: '00:05' },
        { speaker: '은행원', text: 'LTV와 소득을 확인해서 예상 금리와 한도를 안내드릴게요.', time: '00:30' },
        { speaker: '은행원', text: config.intervention.quote.replaceAll('“', '').replaceAll('”', ''), time: '01:00', highlighted: true },
        { speaker: '고객', text: '그럼 정확한 금리는 언제 알 수 있나요?', time: '02:20' },
      ];

  function handleQuery(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (query.trim()) setQueryAsked(true);
  }

  return (
    <div className="product-app">
      <Sidebar product={product} activeNav={activeNav} onNavChange={onNavChange} onNewSession={onNewSession} />

      <main className="dashboard-main">
        <header className="dashboard-header">
          <div>
            <h1>상담 라이브</h1>
          </div>
          <div className={`dashboard-actions${tutorialTarget === 'dashboard-header' ? ' tutorial-focus' : ''}`} data-tutorial="dashboard-header">
            <span className="connection-status"><span aria-hidden="true" /> 연결됨</span>
            <span className={`recording-badge recording-badge-${mode}`}><span aria-hidden="true" /> {recordingInfo.label}</span>
            <span className="mode-badge">{modeLabels[mode]}</span>
            <span className="elapsed-time">{recordingInfo.position}</span>
            <button className="header-new" type="button" onClick={onNewSession}>새 상담</button>
          </div>
        </header>

        <section className={`recording-strip recording-strip-${mode}${tutorialTarget === 'dashboard-recording' ? ' tutorial-focus' : ''}`} data-tutorial="dashboard-recording" aria-label="녹음과 분석 진행 상태">
          <div className="recording-strip-main">
            <div className="recording-strip-label">
              <span className="recording-wave-icon" aria-hidden="true"><i /><i /><i /><i /><i /></span>
              <span><strong>{recordingInfo.label}</strong><small>{recordingInfo.detail}</small></span>
            </div>
            <span className="recording-time">{recordingInfo.position} <b>/</b> {config.timeline.total}</span>
          </div>
          <div className="recording-progress" aria-hidden="true"><span style={{ width: `${recordingInfo.progress}%` }} /></div>
          <div className="recording-flow" aria-label="녹음에서 근거 확인까지의 처리 흐름">
            <span className="is-complete">녹음</span><b aria-hidden="true">→</b>
            <span className="is-complete">전사</span><b aria-hidden="true">→</b>
            <span className="is-current">판정</span><b aria-hidden="true">→</b>
            <span>근거</span>
          </div>
        </section>

        <section className={`session-overview${tutorialTarget === 'dashboard-overview' ? ' tutorial-focus' : ''}`} data-tutorial="dashboard-overview" aria-label="현재 상담 요약">
          <div className="overview-product">
            <span className="overview-label">현재 상담</span>
            <strong>{config.label}</strong>
            <span>{customerLabel || config.customer} · {config.document}</span>
          </div>
          <div className="overview-metrics">
            <div>
              <span className="metric-icon metric-icon-check" aria-hidden="true">✓</span>
              <div className="metric-copy">
                <span>필수 안내</span>
                <strong>{completedCount}<small> / {config.checklist.length}</small></strong>
              </div>
            </div>
            <div>
              <span className="metric-icon metric-icon-alert" aria-hidden="true">!</span>
              <div className="metric-copy">
                <span>개입 필요</span>
                <strong className="metric-warn">2</strong>
              </div>
            </div>
            <div>
              <span className="metric-icon metric-icon-live" aria-hidden="true">●</span>
              <div className="metric-copy">
                <span>상담 상태</span>
                <strong className="metric-live">진행 중</strong>
              </div>
            </div>
          </div>
        </section>

        <div className="dashboard-layout">
          <section className="primary-column">
            <article className={`attention-card${interventionResolved ? ' is-resolved' : ''}`}>
              <div className="attention-header">
                <span className="attention-time">{config.timeline.intervention}</span>
              </div>

              {!interventionResolved ? (
                <>
                  <div className="attention-title-row">
                    <div>
                      <h2>{config.intervention.title}</h2>
                      <p>{config.intervention.body}</p>
                    </div>
                  </div>
                  <div className="quote-line">{config.intervention.quote}</div>
                  <div className={`comparison-grid${tutorialTarget === 'dashboard-attention' ? ' tutorial-focus' : ''}`} data-tutorial="dashboard-attention">
                    <div className="comparison-cell spoken-cell">
                      <span>말씀</span>
                      <strong>{config.intervention.spoken}</strong>
                      <small>현재 발화</small>
                    </div>
                    <div className="comparison-operator" aria-hidden="true">≠</div>
                    <div className="comparison-cell reference-cell">
                      <span>설명서 기준</span>
                      <strong>{config.intervention.reference}</strong>
                      <small>{config.intervention.caption}</small>
                    </div>
                  </div>
                  <div className="attention-footer">
                    <span className="source-caption"><span className="source-mark" aria-hidden="true" /> {config.intervention.source}</span>
                    <div className="attention-actions">
                      <button className="text-button" type="button" onClick={() => setShowEvidence(true)}>근거 원문 보기 <span aria-hidden="true">↗</span></button>
                      <button className="dark-button" type="button" onClick={() => setInterventionResolved(true)}>확인했어요</button>
                    </div>
                  </div>
                </>
              ) : (
                <div className="resolved-state">
                  <span className="resolved-check" aria-hidden="true">✓</span>
                  <div>
                    <h2>확인 기록을 남겼습니다</h2>
                    <p>다음 개입이 발생하면 이 자리에서 안내합니다.</p>
                  </div>
                  <button className="text-button" type="button" onClick={() => setInterventionResolved(false)}>다시 보기</button>
                </div>
              )}
            </article>

            <article className="transcript-card">
              <div className="section-heading">
                <div>
                  <span className="section-eyebrow">실시간 전사</span>
                  <h2>상담 흐름</h2>
                </div>
                <span className="live-indicator"><span aria-hidden="true" /> LIVE</span>
              </div>
              <div className={`transcript-list${tutorialTarget === 'dashboard-transcript' ? ' tutorial-focus' : ''}`} data-tutorial="dashboard-transcript">
                {transcriptRows.map((row) => (
                  <div className={`transcript-row${row.highlighted ? ' is-highlighted' : ''}`} key={`${row.time}-${row.speaker}`}>
                    <span className={`speaker ${row.speaker === '은행원' ? 'speaker-bank' : 'speaker-customer'}`}>{row.speaker}</span>
                    <p>{row.text}</p>
                    <time>{row.time}</time>
                  </div>
                ))}
              </div>
              <form className={`query-bar${tutorialTarget === 'dashboard-query' ? ' tutorial-focus' : ''}`} data-tutorial="dashboard-query" onSubmit={handleQuery}>
                <span className="query-icon" aria-hidden="true">?</span>
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="규정을 직접 물어보세요"
                  aria-label="규정 질의"
                />
                <button type="submit" aria-label="질의 보내기">↗</button>
              </form>
              {queryAsked ? (
                <div className="query-answer">
                  <div className="query-answer-label">기준 가이드의 답변</div>
                  <p>{config.queryAnswer}</p>
                  <button className="text-button" type="button" onClick={() => setShowEvidence(true)}>근거 원문 보기 <span aria-hidden="true">↗</span></button>
                </div>
              ) : null}
            </article>
          </section>

          <aside className="secondary-column">
            <article className="checklist-card">
              <div className="checklist-header">
                <div>
                  <span className="section-eyebrow">필수 안내</span>
                  <h2>진행 상태</h2>
                </div>
                <strong>{completedCount} <small>/ {config.checklist.length}</small></strong>
              </div>
              <div className="progress-track"><span style={{ width: `${(completedCount / config.checklist.length) * 100}%` }} /></div>
              <div className={`checklist-items${tutorialTarget === 'dashboard-checklist' ? ' tutorial-focus' : ''}`} data-tutorial="dashboard-checklist">
                {config.checklist.map((item, index) => (
                  <button
                    className={`checklist-item${selectedItem === index ? ' is-selected' : ''}`}
                    key={item.label}
                    type="button"
                    onClick={() => setSelectedItem(index)}
                  >
                    <StatusMark status={item.status} />
                    <span className="checklist-copy">
                      <strong>{item.label}</strong>
                      <small>{item.status === 'met' ? '고지' : item.status === 'partial' ? '부분' : '미고지'}</small>
                    </span>
                    <span className="checklist-chevron" aria-hidden="true">›</span>
                  </button>
                ))}
              </div>
              <div className="density-row"><span>전문용어 밀도</span><strong>보통</strong></div>
            </article>

            <article className="evidence-card">
              <div className="evidence-heading">
                <div>
                  <span className="section-eyebrow">선택한 항목의 근거</span>
                  <h2>{selectedChecklist.label}</h2>
                </div>
                <span className="evidence-page">{selectedChecklist.source.replace('상품설명서 ', '')}</span>
              </div>
              <div className={`evidence-content${tutorialTarget === 'dashboard-evidence' ? ' tutorial-focus' : ''}`} data-tutorial="dashboard-evidence">
                <div className="document-preview">
                  <div className="document-topline"><span>{config.document}</span><span>{config.page}</span></div>
                  <div className="document-copy">
                    <p>
                      {selectedItem === 1
                        ? '중도해지 시 적용이율은 가입기간과 경과기간에 따라 달라질 수 있습니다.'
                        : selectedItem === 0
                          ? '중도해지 시 우대이자율은 적용되지 않을 수 있습니다.'
                          : '해당 상품의 안내 조건과 적용 기준을 확인합니다.'}
                    </p>
                  </div>
                </div>
                <button className="evidence-link" type="button" onClick={() => setShowEvidence(true)}>
                  원문 전체 보기 <span aria-hidden="true">↗</span>
                </button>
              </div>
            </article>
          </aside>
        </div>

        <footer className="dashboard-footer">
          <span>세션 이벤트 저장 중 · append-only</span>
          <span>계약 팩 {product === 'deposit' ? 'DEP-2026.08-v4' : 'LOAN-2026.08-v1'}</span>
          <span>마지막 동기화 1초 전</span>
        </footer>
      </main>

      {showEvidence ? (
        <div className="evidence-overlay" role="presentation" onClick={() => setShowEvidence(false)}>
          <section className="evidence-modal" role="dialog" aria-modal="true" aria-labelledby="evidence-title" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <div>
                <span className="section-eyebrow">근거 원문</span>
                <h2 id="evidence-title">{selectedChecklist.label}</h2>
              </div>
              <button className="modal-close" type="button" onClick={() => setShowEvidence(false)} aria-label="근거 원문 닫기">×</button>
            </div>
            <div className="modal-meta">
              <span>{config.document}</span>
              <span>{selectedChecklist.source}</span>
              <span>pack_version · {product === 'deposit' ? 'DEP-2026.08-v4' : 'LOAN-2026.08-v1'}</span>
            </div>
            <div className="modal-document">
              <div className="modal-page-number">{config.page.replace('p.', '')}</div>
              <div className="modal-document-text">
                <span className="document-line short" />
                <span className="document-line" />
                <span className="document-line medium" />
                <span className="document-line" />
                <span className="document-line highlighted" />
                <span className="document-line highlighted short" />
                <span className="document-line" />
                <span className="document-line medium" />
                <span className="document-line" />
                <span className="document-line short" />
              </div>
              <div className="modal-quote">“{product === 'deposit' ? '중도해지 시 적용이율은 가입기간에 따라 달라집니다.' : '대출금리 및 한도는 심사·결재 결과에 따라 달라질 수 있습니다.'}”</div>
            </div>
            <div className="modal-footer"><span>출처 스팬이 일치하는 원문만 표시합니다.</span><button className="dark-button" type="button" onClick={() => setShowEvidence(false)}>닫기</button></div>
          </section>
        </div>
      ) : null}
    </div>
  );
}

export default function Home() {
  const [screen, setScreen] = useState<AppScreen>('landing');
  const [product, setProduct] = useState<ProductKey>('deposit');
  const [mode, setMode] = useState<Mode>('replay');
  const [customerLabel, setCustomerLabel] = useState('가상 고객 A');
  const [activeNav, setActiveNav] = useState('상담');
  const [tutorialStep, setTutorialStep] = useState(0);
  const [tutorialOpen, setTutorialOpen] = useState(true);
  const currentTutorialStep = tutorialSteps[tutorialStep];

  function moveTutorial(nextStep: number) {
    const next = tutorialSteps[nextStep];
    if (!next) {
      setTutorialOpen(false);
      return;
    }

    if (next.screen !== screen) {
      setScreen(next.screen);
      window.scrollTo({ top: 0, behavior: 'auto' });
    }

    setTutorialStep(nextStep);
  }

  function handleTutorialNext() {
    if (tutorialStep === tutorialSteps.length - 1) {
      setTutorialOpen(false);
      return;
    }

    moveTutorial(tutorialStep + 1);
  }

  function handleTutorialPrevious() {
    if (tutorialStep > 0) moveTutorial(tutorialStep - 1);
  }

  function startSession() {
    setActiveNav('상담');
    setScreen('dashboard');
    window.scrollTo({ top: 0, behavior: 'auto' });
    if (tutorialOpen && currentTutorialStep.screen === 'landing') {
      const dashboardStep = tutorialSteps.findIndex((step) => step.screen === 'dashboard');
      setTutorialStep(dashboardStep);
    }
  }

  function newSession() {
    setScreen('landing');
    setCustomerLabel(product === 'deposit' ? '가상 고객 A' : '가상 고객 B');
    window.scrollTo({ top: 0, behavior: 'auto' });
    setTutorialStep(0);
    setTutorialOpen(true);
  }

  const page = screen === 'landing' ? (
      <Landing
        product={product}
        mode={mode}
        customerLabel={customerLabel}
        tutorialTarget={tutorialOpen ? currentTutorialStep.target : ''}
        onProductChange={(value) => {
          setProduct(value);
          setCustomerLabel(value === 'deposit' ? '가상 고객 A' : '가상 고객 B');
        }}
        onModeChange={setMode}
        onCustomerChange={setCustomerLabel}
        onStart={startSession}
      />
  ) : (
    <Dashboard
      product={product}
      mode={mode}
      customerLabel={customerLabel}
      tutorialTarget={tutorialOpen ? currentTutorialStep.target : ''}
      activeNav={activeNav}
      onNavChange={setActiveNav}
      onNewSession={newSession}
    />
  );

  return (
    <>
      {page}
      {tutorialOpen ? (
        <TutorialOverlay
          screen={screen}
          stepIndex={tutorialStep}
          onNext={handleTutorialNext}
          onPrevious={handleTutorialPrevious}
          onSkip={() => setTutorialOpen(false)}
        />
      ) : null}
    </>
  );
}
