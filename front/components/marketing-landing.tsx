type ProductKey = 'deposit' | 'mortgage';
type Mode = 'replay' | 'live' | 'trace' | 'text';
type CustomerType = 'general' | 'professional';
type NavItem = '상담' | '리포트' | '규정 팩' | '문서' | '이력';

type LandingProductConfig = {
  label: string;
  customer: string;
  packVersion: string;
  packStatus: 'published' | 'demo';
  totalSeconds: number;
};

type Props = {
  product: ProductKey;
  mode: Mode;
  customerLabel: string;
  customerType: CustomerType;
  tutorialTarget: string;
  configs: Record<ProductKey, LandingProductConfig>;
  onProductChange: (value: ProductKey) => void;
  onModeChange: (value: Mode) => void;
  onCustomerChange: (value: string) => void;
  onCustomerTypeChange: (value: CustomerType) => void;
  onStart: () => void | Promise<void>;
  onNavigate: (value: NavItem) => void;
};

const modeLabels: Record<Mode, string> = { replay: 'REPLAY', live: 'LIVE', trace: 'TRACE', text: 'TEXT' };
const modeDescriptions: Record<Mode, string> = {
  replay: '준비된 녹취 재생',
  live: '실시간 마이크 입력',
  trace: '저장 이벤트 재생',
  text: '음성 없이 텍스트 검토',
};

const landingSteps = [
  { number: '01', label: '준비', title: '상담 기준을 고릅니다', body: '상품설명서와 규정에서 이번 상담에 필요한 항목을 준비합니다.', icon: 'book' as const },
  { number: '02', label: '상담', title: '대화에 맞춰 안내받습니다', body: '상담 중 필요한 순간에 지금 확인할 기준과 다음 행동을 보여줍니다.', icon: 'pulse' as const },
  { number: '03', label: '기록', title: '설명의 근거가 남습니다', body: '설명한 내용과 연결된 문서·페이지·발화가 상담 후 리포트로 이어집니다.', icon: 'check' as const },
];

function formatTime(seconds: number) {
  return `${Math.floor(seconds / 60).toString().padStart(2, '0')}:${Math.floor(seconds % 60).toString().padStart(2, '0')}`;
}

function Icon({ name, size = 24 }: { name: 'arrow' | 'book' | 'check' | 'document' | 'focus' | 'history' | 'lock' | 'play' | 'pulse' | 'spark' | 'target'; size?: number }) {
  const common = { width: size, height: size, viewBox: '0 0 24 24', fill: 'none', xmlns: 'http://www.w3.org/2000/svg', 'aria-hidden': true };
  const stroke = { stroke: 'currentColor', strokeWidth: 1.7, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const };

  if (name === 'arrow') return <svg {...common}><path d="M5 19 19 5M8 5h11v11" {...stroke} /></svg>;
  if (name === 'book') return <svg {...common}><path d="M5 4.5h10.8A2.2 2.2 0 0 1 18 6.7v12.8H7.2A2.2 2.2 0 0 1 5 17.3V4.5Z" {...stroke} /><path d="M5 17.2c0-1.2 1-2.2 2.2-2.2H18M9 8h5M9 11h4" {...stroke} /></svg>;
  if (name === 'check') return <svg {...common}><path d="m5 12.5 4.3 4.2L19 7" {...stroke} /><circle cx="12" cy="12" r="9" {...stroke} /></svg>;
  if (name === 'document') return <svg {...common}><path d="M7 3.8h7l3 3V20H7V3.8Z" {...stroke} /><path d="M14 3.8v3h3M9.5 11h5M9.5 14h5M9.5 17h3" {...stroke} /></svg>;
  if (name === 'focus') return <svg {...common}><circle cx="12" cy="12" r="3.2" {...stroke} /><path d="M12 3v3M12 18v3M3 12h3M18 12h3" {...stroke} /></svg>;
  if (name === 'history') return <svg {...common}><path d="M4.8 8.2A8 8 0 1 1 4 13" {...stroke} /><path d="M4.8 4.8v3.5H8.3M12 8v4l2.8 1.7" {...stroke} /></svg>;
  if (name === 'lock') return <svg {...common}><rect x="5" y="10" width="14" height="10" rx="2" {...stroke} /><path d="M8 10V7.5a4 4 0 0 1 8 0V10" {...stroke} /></svg>;
  if (name === 'play') return <svg {...common}><path d="m9 7 7 5-7 5V7Z" fill="currentColor" /></svg>;
  if (name === 'pulse') return <svg {...common}><path d="M3 12h4l2-6 4.5 12 2-6H21" {...stroke} /></svg>;
  if (name === 'spark') return <svg {...common}><path d="M12 2.8 14 10l7.2 2-7.2 2-2 7.2-2-7.2-7.2-2 7.2-2 2-7.2Z" {...stroke} /></svg>;
  return <svg {...common}><circle cx="12" cy="12" r="8.5" {...stroke} /><circle cx="12" cy="12" r="2.5" {...stroke} /><path d="M12 3.5v2M12 18.5v2M3.5 12h2M18.5 12h2" {...stroke} /></svg>;
}

function LandingBrand() {
  return <span className="landing-relaunch-brand"><img src="/assets/malteum-logo.png" alt="말틈" /></span>;
}

function ArrowLabel({ children }: { children: React.ReactNode }) {
  return <span className="landing-relaunch-arrow-label">{children}<Icon name="arrow" size={17} /></span>;
}

function ProductPreview() {
  return (
    <div className="landing-relaunch-visual" aria-label="말틈 상담 지원 화면 미리보기">
      <div className="landing-relaunch-visual-glow" aria-hidden="true" />
      <div className="landing-relaunch-visual-topline"><span>말틈 / 상담 라이브</span><span><i /> 연결됨</span></div>
      <div className="landing-relaunch-visual-window">
        <aside className="landing-relaunch-preview-nav">
          <div className="landing-relaunch-preview-mark"><span>m</span><b>말틈</b></div>
          <div className="landing-relaunch-preview-nav-item is-active"><Icon name="pulse" size={16} /><span>상담 지원</span></div>
          <div className="landing-relaunch-preview-nav-item"><Icon name="document" size={16} /><span>근거 문서</span></div>
          <div className="landing-relaunch-preview-nav-item"><Icon name="history" size={16} /><span>세션 이력</span></div>
          <div className="landing-relaunch-preview-nav-bottom"><span>현재 기준</span><strong>예적금 중도해지</strong><small>FIXT v1.4 · 발행됨</small></div>
        </aside>
        <div className="landing-relaunch-preview-main">
          <div className="landing-relaunch-preview-header"><div><span>REPLAY · 01:30</span><strong>고객 상담 진행 중</strong></div><span className="landing-relaunch-preview-avatar">A</span></div>
          <div className="landing-relaunch-preview-wave" aria-hidden="true"><span /><span /><span /><span /><span /><span /><span /><span /><span /><span /><span /><span /><span /><span /><span /><span /><span /><span /><span /><span /><span /></div>
          <div className="landing-relaunch-intervention"><div className="landing-relaunch-intervention-heading"><span><Icon name="spark" size={15} /> 지금 확인할 기준</span><b>02</b></div><h3>중도해지 이자율</h3><p>가입기간과 경과기간에 따라 적용이율이 달라질 수 있습니다.</p><div className="landing-relaunch-evidence"><span><Icon name="check" size={15} /> 근거 확인됨</span><small>상품설명서 p.3</small><Icon name="arrow" size={14} /></div></div>
          <div className="landing-relaunch-preview-transcript"><span>실시간 전사</span><p>“중도해지하게 되면 이자는 어떻게 되나요?”</p><b>다음 설명을 준비했어요</b></div>
        </div>
        <aside className="landing-relaunch-preview-checks"><div className="landing-relaunch-checks-head"><span>필수 안내</span><b>2 / 5</b></div><div className="landing-relaunch-check-item is-active"><Icon name="check" size={15} /><span>중도해지 이자율<small>근거 연결됨</small></span></div><div className="landing-relaunch-check-item"><span className="landing-relaunch-empty-check" /><span>만기 후 이자율<small>다음 항목</small></span></div><div className="landing-relaunch-check-item"><span className="landing-relaunch-empty-check" /><span>일부해지 대안<small>대기 중</small></span></div></aside>
      </div>
      <div className="landing-relaunch-floating-note"><span><Icon name="document" size={17} /></span><div><b>설명서와 연결된 답변</b><small>판정의 이유를 바로 확인합니다</small></div></div>
      <img className="landing-relaunch-mascot" src="/assets/malteum-mascot.png" alt="말틈 마스코트 바름이" />
    </div>
  );
}

export default function MarketingLanding({ product, mode, customerLabel, customerType, tutorialTarget, configs, onProductChange, onModeChange, onCustomerChange, onCustomerTypeChange, onStart, onNavigate }: Props) {
  const current = configs[product];

  return (
    <main className="landing-relaunch">
      <header className="landing-relaunch-header">
        <button className="landing-relaunch-brand-button" type="button" onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })} aria-label="말틈 홈으로 이동"><LandingBrand /></button>
        <nav className="landing-relaunch-nav" aria-label="랜딩페이지 메뉴">
          <a href="#landing-relaunch-why">말틈이 필요한 이유</a>
          <a href="#landing-relaunch-flow">작동 방식</a>
          <a href="#landing-relaunch-workspace">상담 화면</a>
        </nav>
        <div className="landing-relaunch-header-actions"><button className="landing-relaunch-history" type="button" onClick={() => onNavigate('이력')}><Icon name="history" size={16} /> 세션 이력</button><button className="landing-relaunch-header-cta" type="button" onClick={() => void onStart()}>상담 시작하기 <Icon name="arrow" size={16} /></button></div>
      </header>

      <section className="landing-relaunch-hero" aria-labelledby="landing-relaunch-title">
        <div className={`landing-relaunch-hero-copy${tutorialTarget === 'landing-hero' ? ' tutorial-focus' : ''}`} data-tutorial="landing-hero">
          <p className="landing-relaunch-eyebrow"><span /> 금융 상담을 위한 근거 기반 가이드</p>
          <h1 id="landing-relaunch-title">상담은 자연스럽게.<br /><em>근거는 또렷하게.</em></h1>
          <p className="landing-relaunch-hero-description">말틈은 상품설명서와 규정에서 필요한 기준을 찾아, 상담원이 놓치지 않도록 대화의 순간에 맞춰 보여줍니다. 상담 후에는 설명의 근거까지 한 번에 남습니다.</p>
          <div className="landing-relaunch-hero-actions"><button className={`landing-relaunch-primary${tutorialTarget === 'landing-start' ? ' tutorial-focus' : ''}`} data-tutorial="landing-start" type="button" onClick={() => void onStart()}>상담 시작하기 <Icon name="arrow" size={18} /></button><a className="landing-relaunch-secondary" href="#landing-relaunch-workspace">실제 화면 먼저 보기 <Icon name="play" size={16} /></a></div>
          <div className="landing-relaunch-trust-line"><span><Icon name="check" size={16} /> 상품설명서·규정 기반</span><i /><span><Icon name="lock" size={16} /> 상담 흐름을 방해하지 않게</span></div>
        </div>
        <ProductPreview />
      </section>

      <section className="landing-relaunch-intro" id="landing-relaunch-why" aria-labelledby="landing-relaunch-why-title">
        <div className="landing-relaunch-section-heading"><div><p className="landing-relaunch-section-kicker">말틈이 바꾸는 상담의 순간</p><h2 id="landing-relaunch-why-title">대화를 멈추지 않고,<br /><em>설명의 빈틈을 채웁니다.</em></h2></div><p>금융 상담에서 중요한 건 더 많은 정보를 띄우는 일이 아닙니다. 지금 고객에게 설명해야 할 한 가지를 놓치지 않는 일입니다.</p></div>
        <div className="landing-relaunch-feature-grid">
          <article className="landing-relaunch-feature-card landing-relaunch-feature-primary"><div className="landing-relaunch-feature-top"><span>01</span><Icon name="focus" size={28} /></div><div className="landing-relaunch-feature-art"><div className="landing-relaunch-focus-ring" /><div className="landing-relaunch-feature-signal"><span /><span /><span /><span /><span /></div><div className="landing-relaunch-feature-tag">지금 필요한 기준</div></div><h3>필요한 기준만, 한 번에</h3><p>한 번에 하나의 개입만 보여줘 상담의 리듬을 끊지 않습니다. 다음 행동이 생기면 조용하고 분명하게 알려줍니다.</p><a href="#landing-relaunch-workspace"><ArrowLabel>대시보드에서 보기</ArrowLabel></a></article>
          <article className="landing-relaunch-feature-card landing-relaunch-feature-document"><div className="landing-relaunch-feature-top"><span>02</span><Icon name="document" size={28} /></div><div className="landing-relaunch-document-art"><div><span>상품설명서</span><b>p.3</b></div><i /><i /><i /><strong><Icon name="check" size={15} /> 연결된 근거</strong></div><h3>판정에서 근거까지</h3><p>왜 확인해야 하는지 문서·페이지·발화로 이어집니다. 설명의 기준을 같은 화면에서 바로 열어볼 수 있습니다.</p></article>
          <article className="landing-relaunch-feature-card landing-relaunch-feature-record"><div className="landing-relaunch-feature-top"><span>03</span><Icon name="history" size={28} /></div><div className="landing-relaunch-record-art"><span /><span /><span /><span /><span /><b>기록</b></div><h3>상담이 끝나도 남는 기록</h3><p>고지 상태와 근거를 리포트로 남겨 다음 상담과 사후 점검까지 이어갑니다.</p></article>
        </div>
      </section>

      <section className="landing-relaunch-flow" id="landing-relaunch-flow" aria-labelledby="landing-relaunch-flow-title">
        <div className="landing-relaunch-flow-heading"><p className="landing-relaunch-section-kicker">복잡한 기준을 간단한 흐름으로</p><h2 id="landing-relaunch-flow-title">상담원은 대화에 집중하고,<br /><em>말틈은 옆에서 기준을 챙깁니다.</em></h2></div>
        <div className="landing-relaunch-step-list">{landingSteps.map((step, index) => <article className="landing-relaunch-step" key={step.number}><div className="landing-relaunch-step-number"><span>{step.number}</span><Icon name={step.icon} size={23} /></div><div><p>{step.label}</p><h3>{step.title}</h3><span>{step.body}</span></div>{index < landingSteps.length - 1 ? <i className="landing-relaunch-step-arrow" aria-hidden="true"><Icon name="arrow" size={18} /></i> : null}</article>)}</div>
      </section>

      <section className="landing-relaunch-workspace" id="landing-relaunch-workspace" aria-labelledby="landing-relaunch-workspace-title">
        <div className="landing-relaunch-workspace-copy"><p className="landing-relaunch-section-kicker">실제 상담 화면</p><h2 id="landing-relaunch-workspace-title">시선은 한 곳에,<br /><em>다음 행동은<br />또렷하게.</em></h2><p>녹음·전사·판정·근거를 한 화면에 모았습니다. 상담 중 시선이 분산되지 않도록 현재 개입을 가장 크게, 체크리스트와 근거를 곁에 둡니다.</p><div className="landing-relaunch-workspace-points"><div><Icon name="pulse" size={19} /><span><b>실시간 전사</b><small>현재 발화와 기준을 바로 비교</small></span></div><div><Icon name="check" size={19} /><span><b>필수 안내 체크</b><small>미확인 항목을 한눈에 확인</small></span></div><div><Icon name="document" size={19} /><span><b>근거 원문 연결</b><small>문서의 페이지까지 이어지는 기록</small></span></div></div><button className="landing-relaunch-workspace-button" type="button" onClick={() => void onStart()}>상담 화면 열기 <Icon name="arrow" size={17} /></button></div>
        <ProductPreview />
      </section>

      <section className="landing-relaunch-final-cta" aria-labelledby="landing-relaunch-cta-title"><div className="landing-relaunch-final-copy"><p className="landing-relaunch-section-kicker">이제 상담을 시작해보세요</p><h2 id="landing-relaunch-cta-title">상담을 시작하면,<br /><em>말틈이 옆에서 돕습니다.</em></h2><p>브리핑을 확인한 뒤 대시보드에서 녹음 시작 버튼을 누르세요. 같은 버튼으로 녹음을 멈출 수 있습니다.</p><button className="landing-relaunch-primary landing-relaunch-primary-dark" type="button" onClick={() => void onStart()}>상담 시작하기 <Icon name="arrow" size={18} /></button></div><div className="landing-relaunch-final-art"><div className="landing-relaunch-final-orbit landing-relaunch-final-orbit-one" /><div className="landing-relaunch-final-orbit landing-relaunch-final-orbit-two" /><img src="/assets/malteum-mascot.png" alt="" /></div></section>

      <section className="landing-relaunch-setup" aria-label="시연 설정"><div className="landing-relaunch-setup-heading"><div><p className="landing-relaunch-section-kicker">필요할 때만 조정하세요</p><h2>시연 환경 설정</h2></div><p>기본값으로 바로 시작해도 됩니다.<br />상담 유형과 입력 모드는 여기서 바꿀 수 있습니다.</p></div><details className="landing-relaunch-settings"><summary><span><Icon name="target" size={18} /> 시연 설정 열기</span><strong>{current.label} · {modeLabels[mode]} · {customerType === 'professional' ? '전문금융소비자' : '일반금융소비자'}</strong><Icon name="arrow" size={17} /></summary><div className="landing-relaunch-settings-panel"><div className="landing-relaunch-setting-group"><span>상담 유형</span><div>{(Object.keys(configs) as ProductKey[]).map((key) => <button type="button" className={key === product ? 'is-selected' : ''} key={key} aria-pressed={key === product} onClick={() => onProductChange(key)}>{configs[key].label}</button>)}</div></div><div className="landing-relaunch-setting-group"><span>입력 모드</span><div>{(Object.keys(modeLabels) as Mode[]).map((key) => <button type="button" className={key === mode ? 'is-selected' : ''} key={key} aria-pressed={key === mode} onClick={() => onModeChange(key)}>{modeLabels[key]}<small>{modeDescriptions[key]}</small></button>)}</div></div><div className="landing-relaunch-form-row"><label>가상 고객 라벨<input value={customerLabel} onChange={(event) => onCustomerChange(event.target.value)} placeholder={current.customer} /></label><label>고객 유형<select value={customerType} onChange={(event) => onCustomerTypeChange(event.target.value as CustomerType)}><option value="general">일반금융소비자</option><option value="professional">전문금융소비자</option></select></label></div></div></details></section>

      <footer className="landing-relaunch-footer"><div className="landing-relaunch-footer-brand"><LandingBrand /><span>금융 상담을 위한 근거 기반 가이드</span></div><div className="landing-relaunch-footer-links"><button type="button" onClick={() => onNavigate('규정 팩')}>규정 팩</button><button type="button" onClick={() => onNavigate('문서')}>문서·근거</button><button type="button" onClick={() => onNavigate('이력')}>세션 이력</button></div><small>© 2026 MALTEUM</small></footer>
    </main>
  );
}
