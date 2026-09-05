import { landingPreview as preview } from '../lib/landing-preview';
import { WorkspaceIcon as Icon, WorkspaceIconName } from './workspace-icons';

type NavItem = '상담' | '리포트' | '기준 관리' | '규정 팩' | '문서' | '이력';
type Props = { onStart: () => void | Promise<void>; onNavigate: (value: NavItem) => void };

function StartButton({ onStart, quiet = false }: { onStart: Props['onStart']; quiet?: boolean }) {
  return <button className={`mlp-start${quiet ? ' is-quiet' : ''}`} type="button" onClick={() => void onStart()}>상담 시작하기<Icon name="arrow" size={18} /></button>;
}
function ExampleLabel() { return <span className="mlp-example">화면 예시</span>; }
function GuideContent() {
  return <><span className="mlp-guide-label"><Icon name="conversation" size={16} /> 쉬운 말 안내</span><h3>{preview.itemName}</h3><p>{preview.guidance}</p><div className="mlp-source-line"><Icon name="document" size={16} /><span>상품설명서</span><b>p.{preview.evidence.page}</b></div></>;
}

function DashboardPreview() {
  return <figure className="mlp-product-stage" aria-label="상담 대화와 가이드를 함께 보여주는 말틈 화면 예시">
    <div className="mlp-product-backdrop" aria-hidden="true" />
    <div className="mlp-product-window">
      <div className="mlp-window-top"><span><i /><i /><i /></span><b>말틈 상담</b><ExampleLabel /></div>
      <div className="mlp-product-layout">
        <aside className="mlp-product-nav" aria-hidden="true"><strong>m.</strong><Icon name="conversation" /><Icon name="document" /><Icon name="history" /></aside>
        <div className="mlp-product-body">
          <div className="mlp-mini-shortcuts">{(['mic', 'check', 'folder', 'book'] as WorkspaceIconName[]).map((icon, index) => <span key={icon}><Icon name={icon} size={18} />{['녹음', '필수 안내', '필요 서류', '기준 확인'][index]}</span>)}</div>
          <div className="mlp-mini-columns">
            <div className="mlp-mini-chat"><h3>상담 대화</h3><div className="mlp-mini-message"><span>고객</span><p>{preview.customer}</p></div><div className="mlp-mini-message is-teller"><span>상담원</span><p>{preview.teller}</p></div><span className="mlp-mini-chat-foot"><Icon name="mic" size={15} /> 화자별로 이어지는 대화</span></div>
            <div className="mlp-mini-guide"><header>상담 가이드</header><div><GuideContent /></div></div>
          </div>
        </div>
      </div>
    </div>
    <div className="mlp-product-float"><span><Icon name="document" size={23} /></span><div><strong>대화에서 근거까지</strong><small>필요한 기준을 같은 화면에</small></div><Icon name="check" size={20} /></div>
  </figure>;
}
function GuidancePreview() {
  return <figure className="mlp-feature-visual mlp-guidance-visual" aria-label="고객의 되물음에 쉬운 말 안내를 제시하는 화면 예시">
    <div className="mlp-visual-top"><span><Icon name="conversation" size={18} /> 상담 중</span><ExampleLabel /></div>
    <div className="mlp-customer-message"><span>고객</span><p>{preview.customer}</p></div>
    <div className="mlp-guidance-connector" aria-hidden="true"><Icon name="arrow" size={18} /></div>
    <div className="mlp-focus-guide"><GuideContent /></div>
  </figure>;
}
function EvidencePreview() {
  return <figure className="mlp-feature-visual mlp-evidence-visual" aria-label="상품설명서의 페이지와 원문이 연결된 근거 화면 예시">
    <div className="mlp-visual-top"><span><Icon name="document" size={18} /> 근거 원문</span><ExampleLabel /></div>
    <div className="mlp-paper-stack" aria-hidden="true" />
    <div className="mlp-evidence-paper"><div className="mlp-paper-heading"><span>ICBC 원화정기예금</span><b>상품설명서</b></div><div className="mlp-paper-section"><span>{preview.itemName}</span><b>p.{preview.evidence.page}</b></div><div className="mlp-paper-lines" aria-hidden="true"><i /><i /></div><blockquote>{preview.evidence.span}</blockquote><div className="mlp-paper-lines" aria-hidden="true"><i /><i /><i /></div><div className="mlp-paper-footer"><Icon name="book" size={17} /><span>설명의 기준이 되는 원문</span><b>{preview.evidence.page}</b></div></div>
  </figure>;
}
function ReportPreview() {
  const values = [{ label: '고지', value: preview.summary.met, state: 'met' }, { label: '부분 고지', value: preview.summary.partial, state: 'partial' }, { label: '미고지', value: preview.summary.unmet, state: 'unmet' }];
  return <figure className="mlp-feature-visual mlp-report-visual" aria-label="상담 종료 후 고지 상태와 위반 및 근거를 확인하는 리포트 화면 예시">
    <div className="mlp-visual-top"><span><Icon name="history" size={18} /> 상담 후</span><ExampleLabel /></div>
    <div className="mlp-report-paper"><header><span className="mlp-report-icon"><Icon name="document" size={26} /></span><div><h3>종료 리포트</h3><span>정기예금 상담</span></div><span className="mlp-report-state">상담 종료</span></header><div className="mlp-report-totals">{values.map(value => <div key={value.state} data-state={value.state}><strong>{value.value}</strong><span>{value.label}</span></div>)}</div><div className="mlp-report-row"><span>설명 이행</span><b>필수 항목 {preview.summary.items_total}개</b></div><div className="mlp-report-row"><span>위반 확인</span><b>{preview.summary.violations}건</b></div><div className="mlp-report-links"><span><Icon name="document" size={16} /> 근거 원문</span><span><Icon name="history" size={16} /> 상담 타임라인</span></div></div>
  </figure>;
}

export default function MarketingLanding({ onStart, onNavigate }: Props) {
  return <main className="mlp" id="mlp-top">
    <header className="mlp-header mlp-container"><a className="mlp-brand" href="#mlp-top" aria-label="말틈 홈"><img src="/assets/malteum-logo.png" alt="말틈" width="84" height="64" /></a><nav aria-label="랜딩페이지 메뉴"><a href="#mlp-features">서비스 소개</a><a href="#mlp-evidence">근거와 기록</a><a href="#mlp-flow">이용 방법</a></nav><StartButton onStart={onStart} quiet /></header>
    <section className="mlp-hero mlp-container" aria-labelledby="mlp-title"><div className="mlp-hero-copy"><p className="mlp-intro">금융 상담을 위한 AI 가이드</p><h1 id="mlp-title"><span>상담은 자연스럽게.</span><span>근거는 또렷하게.</span></h1><p className="mlp-description">설명해야 할 기준부터 놓치기 쉬운 안내까지.<br className="mlp-desktop-break" /> 말틈이 대화 옆에서 챙겨드립니다.</p><div className="mlp-hero-actions"><StartButton onStart={onStart} /><a className="mlp-text-link" href="#mlp-features">화면 살펴보기<Icon name="arrow" size={17} /></a></div></div><DashboardPreview /></section>
    <div className="mlp-capabilities mlp-container" aria-label="말틈 핵심 기능"><span><Icon name="mic" size={24} /> 화자별 실시간 전사</span><span><Icon name="check" size={24} /> 필요한 순간의 안내</span><span><Icon name="book" size={24} /> 문서로 이어지는 근거</span><span><Icon name="history" size={24} /> 상담 후에도 남는 기록</span></div>
    <section className="mlp-feature mlp-container" id="mlp-features" aria-labelledby="mlp-guide-title"><GuidancePreview /><div className="mlp-feature-copy"><span className="mlp-feature-label">상담 중 안내</span><h2 id="mlp-guide-title">지금 필요한 말이,<br />필요한 순간에.</h2><p>고객의 말을 들으며 필요한 안내를 확인하세요. 말틈은 놓친 설명과 이해를 돕는 표현을 하나씩 보여줍니다.</p><ul className="mlp-feature-points"><li><span><Icon name="conversation" size={20} /></span><div><h3>대화의 흐름은 그대로</h3><p>고객과 상담원의 말을 구분해 보여줍니다.</p></div></li><li><span><Icon name="check" size={20} /></span><div><h3>현재 확인할 내용에 집중</h3><p>확인이 필요한 안내를 한 번에 하나씩 봅니다.</p></div></li></ul><a className="mlp-text-link" href="#mlp-evidence">안내의 근거 살펴보기<Icon name="arrow" size={17} /></a></div></section>
    <section className="mlp-feature mlp-feature-reverse mlp-container" id="mlp-evidence" aria-labelledby="mlp-evidence-title"><div className="mlp-feature-copy"><span className="mlp-feature-label">근거 확인</span><h2 id="mlp-evidence-title">왜 필요한 안내인지,<br />원문으로 확인하세요.</h2><p>안내만 띄우고 끝내지 않습니다. 연결된 상품설명서와 규정의 페이지를 열어, 설명의 기준을 직접 확인할 수 있습니다.</p><ul className="mlp-feature-points"><li><span><Icon name="document" size={20} /></span><div><h3>문서·페이지·원문까지</h3><p>안내에서 연결된 근거로 바로 이어집니다.</p></div></li><li><span><Icon name="book" size={20} /></span><div><h3>같은 기준으로 설명</h3><p>상품별로 발행된 규정 팩을 바탕으로 안내합니다.</p></div></li></ul></div><EvidencePreview /></section>
    <section className="mlp-feature mlp-container" id="mlp-record" aria-labelledby="mlp-report-title"><ReportPreview /><div className="mlp-feature-copy"><span className="mlp-feature-label">상담 후 기록</span><h2 id="mlp-report-title">끝난 대화도,<br />설명의 근거로 남도록.</h2><p>상담이 끝나면 고지 상태와 확인한 내용을 리포트로 모아봅니다. 이력에서 지난 상담과 연결된 근거를 다시 확인하세요.</p><ul className="mlp-feature-points"><li><span><Icon name="check" size={20} /></span><div><h3>무엇을 설명했는지 한눈에</h3><p>고지·부분 고지·미고지 상태를 구분합니다.</p></div></li><li><span><Icon name="history" size={20} /></span><div><h3>상담 이후에도 이어지는 기록</h3><p>리포트와 타임라인으로 상담을 돌아봅니다.</p></div></li></ul><button className="mlp-text-link" type="button" onClick={() => onNavigate('이력')}>세션 이력 보기<Icon name="arrow" size={17} /></button></div></section>
    <section className="mlp-get-started" id="mlp-flow" aria-labelledby="mlp-flow-title"><div className="mlp-container"><div className="mlp-get-started-heading"><div><h2 id="mlp-flow-title">다음 상담부터,<br />말틈과 함께하세요.</h2><p>상담 기준을 고르고 녹음을 시작하면 됩니다.</p></div><StartButton onStart={onStart} /></div><ol className="mlp-steps"><li><span>01</span><div><h3>상담 준비</h3><p>상품과 고객 유형을 선택하고<br />필수 안내를 확인합니다.</p></div></li><li><span>02</span><div><h3>녹음 시작</h3><p>대시보드에서 녹음을 켜고<br />대화와 안내를 함께 확인합니다.</p></div></li><li><span>03</span><div><h3>리포트 확인</h3><p>상담을 종료하면 설명 이행과<br />근거를 모아볼 수 있습니다.</p></div></li></ol></div></section>
    <footer className="mlp-footer mlp-container"><a className="mlp-brand" href="#mlp-top" aria-label="말틈 홈"><img src="/assets/malteum-logo.png" alt="말틈" width="84" height="64" /></a><p>대화의 흐름을 지키는 금융 상담 가이드</p><div><button type="button" onClick={() => onNavigate('기준 관리')}>기준 관리</button><button type="button" onClick={() => onNavigate('이력')}>세션 이력</button></div><small>© 2026 말틈</small></footer>
  </main>;
}
