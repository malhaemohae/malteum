'use client';

import { FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import { ApiCandidate, ApiDocument, ApiError, ApiEvent, ApiEvidence, ApiHealth, ApiPackSummary, ApiReport, ApiSessionSummary, ServerMessage, apiUrl, malteumApi, wsUrl } from '../lib/api';
import { MicrophoneCaptureError, Pcm16Capture } from '../lib/audio';
import ConnectedBriefingScreen from '../components/connected-briefing';
import MarketingLanding from '../components/marketing-landing';

type ProductKey = 'deposit' | 'mortgage';
type Mode = 'replay' | 'live' | 'trace' | 'text';
type CustomerType = 'general' | 'professional';
type AppScreen = 'landing' | 'briefing' | 'dashboard' | 'report' | 'packs' | 'documents' | 'history';
type ChecklistStatus = 'met' | 'partial' | 'unmet' | 'waived';
type Speaker = 'teller' | 'customer' | 'system';
type NavItem = '상담' | '리포트' | '규정 팩' | '문서' | '이력';
type ConnectionState = 'local' | 'checking' | 'connecting' | 'connected' | 'fallback' | 'error';
type InterventionKind = 'number' | 'forbidden' | 'risk' | 'rephrase' | 'answer' | 'nudge' | 'documents' | 'briefing';
type Severity = 'critical' | 'warning' | 'info';

type Evidence = {
  ref: string;
  doc: string;
  page: number;
  span: string;
  quote: string;
  legalBasis?: string;
  pageImageUrl?: string;
  bbox?: [number, number, number, number];
  pageSize?: [number, number];
  context?: string;
};

type ChecklistItem = {
  code: string;
  label: string;
  status: ChecklistStatus;
  source: string;
  plainLanguage: string;
  evidenceCode: string;
  required: boolean;
};

type InterventionSeed = {
  kind: InterventionKind;
  label: string;
  title: string;
  body: string;
  quote?: string;
  spoken?: string;
  reference?: string;
  caption?: string;
  source?: string;
  evidenceCode?: string;
  severity?: Severity;
};

type DemoEvent = {
  id: string;
  at: number;
  speaker?: Speaker;
  text?: string;
  highlighted?: boolean;
  status?: { code: string; value: ChecklistStatus };
  alert?: {
    type: string;
    severity: Severity;
    message: string;
    intervention: InterventionSeed;
  };
  assist?: InterventionSeed;
};

type QueryResult = {
  question: string;
  answer: string | null;
  evidenceCode?: string;
};

type ProductConfig = {
  label: string;
  customer: string;
  productCode: string;
  packVersion: string;
  packStatus: 'published' | 'demo';
  document: string;
  totalSeconds: number;
  briefing: {
    recentChange: string;
    mustSay: string[];
    mustNotSay: string[];
    documents: string[];
  };
  checklist: ChecklistItem[];
  evidence: Record<string, Evidence>;
  queryAnswers: Array<{ matches: string[]; answer: string; evidenceCode: string }>;
  events: DemoEvent[];
};

type TranscriptRow = {
  id: string;
  speaker: Speaker;
  text: string;
  time: number;
  highlighted?: boolean;
};

type Intervention = InterventionSeed & { id: string; time: number; sourceEventId: string };

type SessionState = {
  sessionId: string;
  product: ProductKey;
  mode: Mode;
  customerLabel: string;
  currentSeconds: number;
  eventCursor: number;
  transcript: TranscriptRow[];
  checklist: ChecklistItem[];
  activeIntervention: Intervention | null;
  alertCount: number;
  violationCount: number;
  assistAdopted: number;
  acknowledgedCount: number;
  queryResult: QueryResult | null;
  eventLog: string[];
  ended: boolean;
  customerType: CustomerType;
  connectionState: ConnectionState;
  serverSeq: number;
  wsUrl?: string;
  reportUrl?: string;
  report?: ApiReport;
  partialText?: string;
  lastError?: string;
  evidenceRefsByCode: Record<string, string>;
  verdictVersions: Record<string, number>;
  remoteEvidence: Record<string, Evidence>;
  remoteProgress?: { met: number; partial: number; itemsTotal: number; remaining: string[]; termDensity?: string };
  serverEventCount: number;
  localReplay: boolean;
  serverPackVersion?: string;
};

type TutorialStep = {
  screen: 'landing' | 'briefing' | 'dashboard';
  target: string;
  label: string;
  title: string;
  body: string;
  button: string;
  spotlight?: { padding: number; radius: string };
};

const evidence = {
  depositRate: {
    ref: 'FIXT-EV-0005',
    doc: '신한 My플러스 정기예금 상품설명서',
    page: 3,
    span: '중도해지 시 적용이율은 가입기간과 경과기간에 따라 달라질 수 있습니다.',
    quote: '1개월 미만 중도해지 시 적용이율은 연 0.10%입니다.',
    legalBasis: '상품설명서 p.3 · 중도해지 이자율',
  },
  depositBenefit: {
    ref: 'FIXT-EV-0003',
    doc: '신한 My플러스 정기예금 상품설명서',
    page: 2,
    span: '중도해지 시 우대이자율은 적용되지 않을 수 있습니다.',
    quote: '중도해지하는 경우 우대이자율을 적용하지 않습니다.',
    legalBasis: '상품설명서 p.2 · 우대이자율 미적용',
  },
  depositMaturity: {
    ref: 'FIXT-EV-9001',
    doc: '신한 My플러스 정기예금 상품설명서',
    page: 3,
    span: '만기 후 1개월 이내는 만기일 당시 일반정기예금 이율을 적용하고, 6개월을 넘기면 연 0.10%로 내려갑니다.',
    quote: '만기 후 1개월 이내는 만기일 당시 일반정기예금 이율을 적용하고, 6개월을 넘기면 연 0.10%로 내려갑니다.',
    legalBasis: '상품설명서 p.3 · 만기후이자율',
  },
  depositPartial: {
    ref: 'FIXT-EV-0025',
    doc: '신한 My플러스 정기예금 상품설명서',
    page: 4,
    span: '일부해지는 약정된 조건과 횟수에 따라 가능합니다.',
    quote: '전액을 해지하지 않고 일부해지 조건을 먼저 확인할 수 있습니다.',
    legalBasis: '상품설명서 p.4 · 일부해지 대안',
  },
  depositLoan: {
    ref: 'FIXT-EV-0027',
    doc: '신한 My플러스 정기예금 상품설명서',
    page: 6,
    span: '예금담보대출은 납입액의 100%까지 가능합니다.',
    quote: '해지 대신 예금을 담보로 납입액의 100%까지 대출할 수 있습니다.',
    legalBasis: '상품설명서 p.6 · 예금담보대출 대안',
  },
  mortgageRate: {
    ref: 'MTG-DEMO-EV-0005',
    doc: '가계대출 상품설명서',
    page: 12,
    span: '대출금리 및 한도는 심사·결재 결과에 따라 달라질 수 있습니다.',
    quote: '대출금리와 한도는 심사·결재 결과에 따라 확정됩니다.',
    legalBasis: '가계대출 상품설명서 p.12 · 확정 전 안내',
  },
  mortgageFee: {
    ref: 'MTG-DEMO-EV-0010',
    doc: '가계대출 상품설명서',
    page: 2,
    span: '중도상환수수료는 대출 실행 시점과 상환 조건에 따라 달라질 수 있습니다.',
    quote: '중도상환수수료와 면제 조건은 상품별 기준을 확인해야 합니다.',
    legalBasis: '가계대출 상품설명서 p.2 · 중도상환수수료',
  },
  mortgageLand: {
    ref: 'MTG-DEMO-EV-0014',
    doc: '가계대출 상품설명서',
    page: 13,
    span: '근저당권은 대출금의 담보를 위해 부동산에 설정하는 권리입니다.',
    quote: '근저당권은 대출을 담보하기 위해 부동산에 설정하는 권리입니다.',
    legalBasis: '가계대출 상품설명서 p.13 · 근저당권',
  },
  mortgageRateCut: {
    ref: 'MTG-DEMO-EV-0016',
    doc: '가계대출 상품설명서',
    page: 14,
    span: '신용상태가 개선된 경우 금리인하요구권을 행사할 수 있습니다.',
    quote: '신용상태가 좋아지면 금리인하를 요구할 수 있습니다.',
    legalBasis: '가계대출 상품설명서 p.14 · 금리인하요구권',
  },
  mortgageDocuments: {
    ref: 'MTG-DEMO-EV-0020',
    doc: '가계대출 상품설명서',
    page: 3,
    span: '신청 시 등기부등본과 소득 증빙 등 필요한 서류를 제출해야 합니다.',
    quote: '등기부등본과 소득 증빙 서류를 준비해 주세요.',
    legalBasis: '가계대출 상품설명서 p.3 · 필요 서류',
  },
} satisfies Record<string, Evidence>;

const productConfigs: Record<ProductKey, ProductConfig> = {
  deposit: {
    label: '예적금 중도해지',
    customer: '가상 고객 A',
    productCode: 'SHB-MYPLUS-TD',
    packVersion: 'DEP-2026.08-v4',
    packStatus: 'published',
    document: '신한 My플러스 정기예금 상품설명서',
    totalSeconds: 210,
    briefing: {
      recentChange: '2026.08.26 · 중도해지 설명 항목과 대안 안내를 반영한 발행본',
      mustSay: ['우대이자율 미적용', '중도해지 이자율', '만기후이자율', '일부해지 대안', '예금담보대출 대안'],
      mustNotSay: ['만기 후에도 지금 금리가 그대로라고 단정하기', '해지 판단을 무조건 이득이라고 단정하기'],
      documents: ['신한 My플러스 정기예금 상품설명서', '금융소비자보호법', '설명의무 이행 가이드라인'],
    },
    checklist: [
      { code: 'DEP-INT-004', label: '우대이자율 미적용', status: 'unmet', source: '상품설명서 p.2', plainLanguage: '중간에 해지하면 우대 조건으로 더 받기로 한 이자는 적용되지 않을 수 있습니다.', evidenceCode: 'depositBenefit', required: true },
      { code: 'DEP-INT-002', label: '중도해지 이자율', status: 'unmet', source: '상품설명서 p.3', plainLanguage: '만기까지 두지 않고 찾으면 처음 약속한 이자가 아니라 낮은 이자로 계산됩니다.', evidenceCode: 'depositRate', required: true },
      { code: 'DEP-INT-003', label: '만기후이자율', status: 'unmet', source: '상품설명서 p.3', plainLanguage: '만기가 지나도 같은 이율이 계속 붙는 것은 아니므로 기간별 기준을 확인합니다.', evidenceCode: 'depositMaturity', required: true },
      { code: 'DEP-LIM-001', label: '일부해지 대안', status: 'unmet', source: '상품설명서 p.4', plainLanguage: '전액을 해지하지 않고 일부 금액만 찾을 수 있는지 먼저 확인합니다.', evidenceCode: 'depositPartial', required: true },
      { code: 'DEP-LON-001', label: '예금담보대출 대안', status: 'unmet', source: '상품설명서 p.6', plainLanguage: '해지 대신 예금을 담보로 필요한 금액만 마련할 수 있는지 확인합니다.', evidenceCode: 'depositLoan', required: true },
    ],
    evidence: { depositRate: evidence.depositRate, depositBenefit: evidence.depositBenefit, depositMaturity: evidence.depositMaturity, depositPartial: evidence.depositPartial, depositLoan: evidence.depositLoan },
    queryAnswers: [
      { matches: ['만기', '이자'], answer: evidence.depositMaturity.quote, evidenceCode: 'depositMaturity' },
      { matches: ['담보', '대출'], answer: evidence.depositLoan.quote, evidenceCode: 'depositLoan' },
    ],
    events: [
      { id: 'FIXT-EV-0001', at: 5, speaker: 'customer', text: '지금 해지하면 얼마나 받을 수 있어요?' },
      { id: 'FIXT-EV-0003', at: 15, speaker: 'teller', text: '우대이자율은 중도해지하시면 적용이 안 되고요, 기준에 따라 안내드릴게요.', status: { code: 'DEP-INT-004', value: 'met' } },
      { id: 'FIXT-EV-0005', at: 35, speaker: 'teller', text: '중도해지하시면 0.5% 정도는 받으세요.', highlighted: true, status: { code: 'DEP-INT-002', value: 'partial' }, alert: { type: 'number_mismatch', severity: 'warning', message: '설명서 기준 중도해지 이자율을 확인해 주세요.', intervention: { kind: 'number', label: '숫자 오류', title: '설명서 기준으로 확인해 주세요', body: '현재 발화의 수치와 상품설명서 기준이 다릅니다.', quote: '“중도해지하시면 0.5% 정도는 받으세요.”', spoken: '0.5%', reference: '연 0.10%', caption: '가입 1개월 미만 기준', source: '상품설명서 p.3 · 중도해지 이자율', evidenceCode: 'depositRate', severity: 'warning' } } },
      { id: 'FIXT-EV-0009', at: 70, speaker: 'customer', text: '네? 중간에 깨면 그것밖에 못 받아요?', assist: { kind: 'rephrase', label: '재진술', title: '고객이 다시 물었어요', body: '직전 설명을 같은 의미의 쉬운 말로 다시 안내할 수 있습니다.', quote: '만기까지 두지 않고 중간에 찾으시면, 처음 약속한 이자가 아니라 훨씬 낮은 이자로 계산됩니다.', source: '승인된 쉬운 말 사전', evidenceCode: 'depositRate' } },
      { id: 'FIXT-EV-9001', at: 90, speaker: 'customer', text: '만기 지나서 그냥 두면 이자가 어떻게 되나요?', status: { code: 'DEP-INT-003', value: 'met' }, assist: { kind: 'answer', label: '역질문', title: '근거 있는 답변을 준비했어요', body: '고객 질문에 대한 설명서 기준 답변입니다.', quote: evidence.depositMaturity.quote, source: '상품설명서 p.3 · 만기후이자율', evidenceCode: 'depositMaturity' } },
      { id: 'FIXT-EV-0017', at: 110, speaker: 'teller', text: '그냥 두셔도 돼요. 만기 지나도 지금 금리가 그대로 계속 붙거든요.', highlighted: true, alert: { type: 'forbidden_phrase', severity: 'warning', message: '확정되지 않은 내용을 단정하지 않도록 설명서 기준을 확인해 주세요.', intervention: { kind: 'forbidden', label: '금지 발언', title: '확정 전 안내임을 함께 표시해 주세요', body: '만기 후 이율은 기간별 기준이 있으므로 현재 금리가 그대로라고 단정할 수 없습니다.', quote: '“지금 금리가 그대로 계속 붙거든요.”', spoken: '그대로', reference: '기간별 만기후이자율', caption: '상품설명서 기준', source: '상품설명서 p.3 · 만기후이자율', evidenceCode: 'depositMaturity', severity: 'warning' } } },
      { id: 'FIXT-EV-0021', at: 135, speaker: 'teller', text: '중도해지 이율은 다시 정정해서 안내드리겠습니다.', status: { code: 'DEP-INT-002', value: 'partial' } },
      { id: 'FIXT-EV-0024', at: 160, assist: { kind: 'nudge', label: '누락 넛지', title: '대안 안내가 아직 남아 있어요', body: '해지 전에 일부해지와 예금담보대출 대안을 함께 안내해 보세요.', quote: '해지 대신 일부해지나 예금담보대출이 가능한지 먼저 확인해 주세요.', source: '상품설명서 p.4·p.6', evidenceCode: 'depositLoan' } },
      { id: 'FIXT-EV-0026', at: 175, speaker: 'teller', text: '일부해지가 가능한지 먼저 확인해 드리겠습니다.', status: { code: 'DEP-LIM-001', value: 'met' } },
      { id: 'FIXT-EV-0027', at: 180, speaker: 'teller', text: '예금담보대출로 필요한 금액만 마련하는 방법도 있습니다.', status: { code: 'DEP-LON-001', value: 'met' } },
      { id: 'FIXT-EV-0029', at: 185, speaker: 'customer', text: '해지한 돈은 딸이 알려준 계좌로 바로 보내 주세요.', highlighted: true, alert: { type: 'risk_signal', severity: 'critical', message: '제3자가 알려준 계좌로의 이체 요청입니다. 사용 목적과 수취인 관계를 확인해 주세요.', intervention: { kind: 'risk', label: '위험 신호', title: '이체 정보를 한 번 더 확인해 주세요', body: '고객 발화에서 제3자 계좌로 보내 달라는 요청이 감지되었습니다. 후속 조치는 은행 절차에 따라 진행합니다.', quote: '“딸이 알려준 계좌로 바로 보내 주세요.”', source: '금융위 보이스피싱 대책 p.18', evidenceCode: 'depositLoan', severity: 'critical' } } },
    ],
  },
  mortgage: {
    label: '주택담보대출', customer: '가상 고객 B', productCode: 'MTG-DEMO-HOME', packVersion: 'MTG-2026.08-v1', packStatus: 'demo', document: '가계대출 상품설명서', totalSeconds: 240,
    briefing: { recentChange: '2026.08 데모 팩 · 내부 결재 전 금리·한도와 필요 서류 항목을 준비', mustSay: ['LTV·담보인정비율', '확정 전 안내', '중도상환수수료', '금리인하요구권', '필요 서류'], mustNotSay: ['심사·결재 전 금리나 한도를 확정이라고 단정하기', '지역·조건에 따라 달라지는 수치를 일반값처럼 안내하기'], documents: ['가계대출 상품설명서', '금융소비자보호법', '은행법'] },
    checklist: [
      { code: 'MTG-LTV-001', label: 'LTV·담보인정비율', status: 'unmet', source: '상품설명서 p.12', plainLanguage: '담보가치와 지역·조건에 따라 대출 가능 범위가 달라질 수 있습니다.', evidenceCode: 'mortgageRate', required: true },
      { code: 'MTG-BAN-001', label: '확정 전 안내', status: 'unmet', source: '상품설명서 p.12', plainLanguage: '금리와 한도는 심사와 결재가 끝난 뒤 확정됩니다.', evidenceCode: 'mortgageRate', required: true },
      { code: 'MTG-FEE-001', label: '중도상환수수료', status: 'unmet', source: '상품설명서 p.2', plainLanguage: '중도에 갚을 때 수수료와 면제 조건을 함께 확인합니다.', evidenceCode: 'mortgageFee', required: true },
      { code: 'MTG-RATE-001', label: '금리인하요구권', status: 'unmet', source: '상품설명서 p.14', plainLanguage: '신용상태가 좋아지면 금리인하를 요구할 수 있습니다.', evidenceCode: 'mortgageRateCut', required: true },
      { code: 'MTG-DOC-001', label: '필요 서류', status: 'unmet', source: '상품설명서 p.3', plainLanguage: '등기부등본과 소득 증빙 등 필요한 서류를 준비합니다.', evidenceCode: 'mortgageDocuments', required: true },
    ],
    evidence: { mortgageRate: evidence.mortgageRate, mortgageFee: evidence.mortgageFee, mortgageLand: evidence.mortgageLand, mortgageRateCut: evidence.mortgageRateCut, mortgageDocuments: evidence.mortgageDocuments },
    queryAnswers: [
      { matches: ['근저당', '담보'], answer: evidence.mortgageLand.quote, evidenceCode: 'mortgageLand' },
      { matches: ['금리', '한도'], answer: evidence.mortgageRate.quote, evidenceCode: 'mortgageRate' },
    ],
    events: [
      { id: 'MTG-DEMO-EV-0001', at: 5, speaker: 'customer', text: '가능한 금리와 한도가 어떻게 되나요?' },
      { id: 'MTG-DEMO-EV-0003', at: 30, speaker: 'teller', text: 'LTV와 소득을 확인해서 예상 금리와 한도를 안내드릴게요.', status: { code: 'MTG-LTV-001', value: 'met' } },
      { id: 'MTG-DEMO-EV-0005', at: 60, speaker: 'teller', text: '이 금리로 확정이라고 보시면 돼요.', highlighted: true, status: { code: 'MTG-BAN-001', value: 'partial' }, alert: { type: 'forbidden_phrase', severity: 'warning', message: '내부 결재 전에는 금리나 한도를 확정된 것처럼 안내하지 않습니다.', intervention: { kind: 'forbidden', label: '금지 발언', title: '확정 전 안내임을 함께 표시해 주세요', body: '내부 결재 전 상담에서는 금리나 한도를 확정된 것처럼 안내하면 안 됩니다.', quote: '“이 금리로 확정이라고 보시면 돼요.”', spoken: '확정', reference: '심사·결재 후 확정', caption: '상담 단계 기준', source: '가계대출 상품설명서 p.12 · 금리 안내', evidenceCode: 'mortgageRate', severity: 'warning' } } },
      { id: 'MTG-DEMO-EV-0010', at: 100, speaker: 'teller', text: '중도상환수수료는 0.5% 정도로 보시면 됩니다.', highlighted: true, status: { code: 'MTG-FEE-001', value: 'partial' }, alert: { type: 'number_mismatch', severity: 'warning', message: '중도상환수수료는 조건과 시점별 기준을 함께 확인해 주세요.', intervention: { kind: 'number', label: '숫자 오류', title: '수수료 기준을 다시 확인해 주세요', body: '중도상환수수료는 상품 조건과 시점에 따라 달라질 수 있습니다.', quote: '“중도상환수수료는 0.5% 정도로 보시면 됩니다.”', spoken: '0.5%', reference: '조건·시점별 기준', caption: '상품설명서 기준', source: '가계대출 상품설명서 p.2 · 중도상환수수료', evidenceCode: 'mortgageFee', severity: 'warning' } } },
      { id: 'MTG-DEMO-EV-0014', at: 140, speaker: 'customer', text: '근저당 설정이 뭐예요?', assist: { kind: 'rephrase', label: '재진술', title: '고객이 용어를 다시 물었어요', body: '근거가 확인된 쉬운 설명을 참고할 수 있습니다.', quote: evidence.mortgageLand.quote, source: '가계대출 상품설명서 p.13 · 근저당권', evidenceCode: 'mortgageLand' } },
      { id: 'MTG-DEMO-EV-0020', at: 210, assist: { kind: 'documents', label: '서류 안내', title: '필요 서류를 안내해 보세요', body: '상담 마무리 전에 준비할 서류를 알려 주세요.', quote: evidence.mortgageDocuments.quote, source: '가계대출 상품설명서 p.3 · 필요 서류', evidenceCode: 'mortgageDocuments' }, status: { code: 'MTG-DOC-001', value: 'met' } },
    ],
  },
};

const modeLabels: Record<Mode, string> = { replay: 'REPLAY', live: 'LIVE', trace: 'TRACE', text: 'TEXT' };
const modeDescriptions: Record<Mode, string> = { replay: '녹취 재생 · 기본', live: '실시간 녹음', trace: '저장 이벤트 재생', text: '음성 없이 검토' };
const navItems: Array<{ key: NavItem; number: string; icon: string }> = [{ key: '상담', number: '01', icon: '⌁' }, { key: '리포트', number: '02', icon: '▥' }, { key: '규정 팩', number: '03', icon: '◈' }, { key: '문서', number: '04', icon: '▤' }, { key: '이력', number: '05', icon: '↺' }];

const tutorialSteps: TutorialStep[] = [
  { screen: 'dashboard', target: 'dashboard-header', label: '01 · 실시간 상태', title: '상담의 전체 상태를 한 화면에서 확인해요.', body: '상단에서 연결 상태, 실행 모드, 현재 시간과 상담 종료 버튼을 확인합니다.', button: '다음으로', spotlight: { padding: 6, radius: '16px' } },
  { screen: 'dashboard', target: 'dashboard-recording', label: '02 · 녹음·분석', title: '녹음이 전사의 시작점입니다.', body: '오디오·전사·판정·근거 순서와 현재 진행 위치를 한 줄에서 확인합니다.', button: '다음으로', spotlight: { padding: 4, radius: '16px' } },
  { screen: 'dashboard', target: 'dashboard-overview', label: '03 · 한눈에 보는 요약', title: '지금 어떤 상담인지 한 줄로 고정해둡니다.', body: '상품, 고객 라벨, 문서와 함께 고지 수·개입 필요·상담 상태를 봅니다.', button: '다음으로', spotlight: { padding: 4, radius: '16px' } },
  { screen: 'dashboard', target: 'dashboard-attention', label: '04 · 핵심 개입', title: '놓치면 안 되는 순간은 가장 크게 알려줘요.', body: '현재 발화와 설명서 기준을 비교하고, 확인하거나 근거 원문을 엽니다.', button: '다음으로', spotlight: { padding: 4, radius: '16px' } },
  { screen: 'dashboard', target: 'dashboard-transcript', label: '05 · 실시간 전사', title: '상담의 맥락은 전사 흐름으로 남습니다.', body: '은행원과 고객의 발화를 시간 순서로 보고 감지된 문장을 다시 찾습니다.', button: '다음으로', spotlight: { padding: 4, radius: '16px' } },
  { screen: 'dashboard', target: 'dashboard-query', label: '06 · 규정 질의', title: '규정을 직접 물어볼 수도 있어요.', body: '근거가 있는 질문에는 답변과 원문을 함께 보여주고, 근거가 없으면 답하지 않습니다.', button: '다음으로', spotlight: { padding: 4, radius: '14px' } },
  { screen: 'dashboard', target: 'dashboard-checklist', label: '07 · 필수 안내', title: '필수 안내가 어디까지 진행됐는지 보여줘요.', body: '항목을 선택해 근거를 확인하고, 음성이 어려울 때는 사람이 직접 고지 완료나 제외 사유를 기록합니다.', button: '다음으로', spotlight: { padding: 4, radius: '16px' } },
  { screen: 'dashboard', target: 'dashboard-evidence', label: '08 · 근거 확인', title: '모든 안내는 문서 근거로 확인합니다.', body: '선택한 항목의 실제 페이지·인용 span·출처를 확인한 뒤 상담으로 돌아갑니다.', button: '튜토리얼 끝내기', spotlight: { padding: 4, radius: '16px' } },
];

function formatTime(seconds: number) { return `${Math.floor(seconds / 60).toString().padStart(2, '0')}:${Math.floor(seconds % 60).toString().padStart(2, '0')}`; }

function microphoneErrorMessage(error: unknown) {
  const code = error instanceof MicrophoneCaptureError
    ? error.code
    : error instanceof DOMException
      ? error.name
      : error instanceof Error
        ? error.name
        : '';

  switch (code) {
    case 'unsupported':
    case 'TypeError':
      return '이 브라우저에서는 마이크 녹음을 사용할 수 없습니다. Chrome 또는 Edge에서 다시 시도해 주세요.';
    case 'NotAllowedError':
    case 'SecurityError':
      return '브라우저의 사이트 설정에서 이 페이지의 마이크 권한을 허용해 주세요.';
    case 'NotFoundError':
      return '연결된 마이크를 찾지 못했습니다. 입력 장치를 연결한 뒤 다시 시도해 주세요.';
    case 'NotReadableError':
      return '마이크가 다른 프로그램에서 사용 중입니다. 다른 음성 앱을 닫고 다시 시도해 주세요.';
    case 'OverconstrainedError':
      return '현재 입력 장치가 녹음 조건을 지원하지 않습니다. 다른 마이크로 다시 시도해 주세요.';
    case 'AbortError':
      return '마이크 연결이 중단되었습니다. 잠시 후 다시 시도해 주세요.';
    default:
      return '마이크를 시작하지 못했습니다. 입력 장치와 브라우저 설정을 확인해 주세요.';
  }
}
function speakerLabel(speaker: Speaker) { return speaker === 'teller' ? '은행원' : speaker === 'customer' ? '고객' : '시스템'; }
function statusLabel(status: ChecklistStatus) { return status === 'met' ? '고지' : status === 'partial' ? '부분' : status === 'waived' ? '제외' : '미고지'; }
function statusClass(status: ChecklistStatus) { return status === 'met' ? 'met' : status === 'partial' ? 'partial' : status === 'waived' ? 'waived' : 'unmet'; }
function connectionLabel(state: ConnectionState) { return state === 'connected' ? '서버 연결됨' : state === 'connecting' ? '서버 연결 중' : state === 'error' ? '연결 오류' : state === 'fallback' ? '로컬 폴백' : '로컬 데모'; }

function createSession(product: ProductKey, mode: Mode, customerLabel: string, sessionId?: string, customerType: CustomerType = 'general'): SessionState {
  const config = productConfigs[product];
  return { sessionId: sessionId ?? `LOCAL-${product === 'deposit' ? 'DEP' : 'MTG'}-${Math.floor(Math.random() * 900 + 100)}`, product, mode, customerLabel: customerLabel || config.customer, customerType, currentSeconds: 0, eventCursor: 0, transcript: [], checklist: config.checklist.map((item) => ({ ...item, status: 'unmet' })), activeIntervention: null, alertCount: 0, violationCount: 0, assistAdopted: 0, acknowledgedCount: 0, queryResult: null, eventLog: ['session_started'], ended: false, connectionState: 'local', serverSeq: 0, evidenceRefsByCode: {}, verdictVersions: {}, remoteEvidence: {}, serverEventCount: 0, localReplay: false };
}

function interventionFromSeed(seed: InterventionSeed, event: DemoEvent): Intervention { return { ...seed, id: `${event.id}-assist`, time: event.at, sourceEventId: event.id }; }

function applyDemoEvent(session: SessionState, event: DemoEvent): SessionState {
  const next: SessionState = { ...session, eventCursor: session.eventCursor + 1, currentSeconds: event.at, transcript: [...session.transcript], checklist: session.checklist.map((item) => ({ ...item })), eventLog: [...session.eventLog, event.id] };
  if (event.text && event.speaker) next.transcript.push({ id: event.id, speaker: event.speaker, text: event.text, time: event.at, highlighted: event.highlighted });
  if (event.status) next.checklist = next.checklist.map((item) => item.code === event.status?.code ? { ...item, status: event.status.value } : item);
  if (event.alert) { next.alertCount += 1; if (event.alert.type === 'forbidden_phrase') next.violationCount += 1; next.activeIntervention = interventionFromSeed(event.alert.intervention, event); }
  if (event.assist) next.activeIntervention = interventionFromSeed(event.assist, event);
  return next;
}

function localQueryResult(config: ProductConfig, question: string): QueryResult {
  const matched = config.queryAnswers.find((item) => item.matches.some((word) => question.includes(word)));
  return matched ? { question, answer: matched.answer, evidenceCode: matched.evidenceCode } : { question, answer: null };
}

function checklistStatusFromServer(state: unknown): ChecklistStatus | null {
  if (state === 'met' || state === 'partial' || state === 'unmet' || state === 'waived') return state;
  return null;
}

function evidenceFromApi(value: ApiEvidence, ref: string): Evidence {
  return {
    ref,
    doc: value.doc_title || value.doc_id,
    page: value.page,
    span: value.span,
    quote: value.context || value.span,
    legalBasis: value.legal_basis,
    pageImageUrl: value.page_image_url ? apiUrl(value.page_image_url) : undefined,
    bbox: value.bbox,
    pageSize: value.page_size,
    context: value.context,
  };
}

function serverMessageFromStoredEvent(event: ApiEvent): ServerMessage | null {
  const body = event.kind && typeof event[event.kind] === 'object' && event[event.kind] ? event[event.kind] as Record<string, unknown> : {};
  const seq = typeof event.seq_in_session === 'number' ? event.seq_in_session : undefined;
  const eventId = typeof event.event_id === 'string' ? event.event_id : undefined;
  if (event.kind === 'utterance') return { t: 'utterance', ...(seq === undefined ? {} : { seq }), ...(eventId ? { event_id: eventId } : {}), ...body } as ServerMessage;
  if (event.kind === 'verdict') return { t: 'verdict', ...(seq === undefined ? {} : { seq }), ...(eventId ? { event_id: eventId } : {}), ...body, ver: typeof body.ver === 'number' ? body.ver : 1, ...(body.evidence ? { evidence_ref: eventId } : {}) } as ServerMessage;
  if (event.kind === 'alert') return { t: 'alert', ...(seq === undefined ? {} : { seq }), ...(eventId ? { event_id: eventId } : {}), ...body, ...(body.evidence ? { evidence_ref: eventId } : {}) } as ServerMessage;
  if (event.kind === 'assist') return { t: 'assist', ...(seq === undefined ? {} : { seq }), ...(eventId ? { event_id: eventId } : {}), ...body, ver: typeof body.ver === 'number' ? body.ver : 1, ...(body.evidence ? { evidence_ref: eventId } : {}) } as ServerMessage;
  if (event.kind === 'session_ended') return { t: 'ended', ...(seq === undefined ? {} : { seq }), ...(event.session_id ? { session_id: String(event.session_id) } : {}), summary: body.summary ?? {} } as ServerMessage;
  return null;
}

function interventionKindForAlert(type: unknown): InterventionKind {
  if (type === 'number_mismatch') return 'number';
  if (type === 'risk_signal') return 'risk';
  if (type === 'forbidden_phrase') return 'forbidden';
  return 'nudge';
}

function interventionLabelForKind(kind: InterventionKind) {
  return kind === 'number' ? '숫자 오류' : kind === 'forbidden' ? '금지 발언' : kind === 'risk' ? '위험 신호' : kind === 'rephrase' ? '재진술' : kind === 'answer' ? '역질문' : kind === 'documents' ? '서류 안내' : kind === 'briefing' ? '브리핑' : '누락 넛지';
}

function BrandMark({ dark = false }: { dark?: boolean }) { return <div className={`brand-mark${dark ? ' brand-mark-dark' : ''}`}><img className="brand-logo" src="/assets/malteum-logo.png" alt="말틈" /></div>; }
function Mascot() { return <img className="mascot" src="/assets/malteum-mascot.png" alt="바름이 캐릭터" />; }
function StatusMark({ status }: { status: ChecklistStatus }) { return <span className={`status-mark status-${status}`} aria-hidden="true">{status === 'met' ? '✓' : status === 'partial' ? '◐' : status === 'waived' ? '−' : ''}</span>; }

function TutorialOverlay({ stepIndex, onNext, onPrevious, onSkip }: { stepIndex: number; onNext: () => void; onPrevious: () => void; onSkip: () => void }) {
  const step = tutorialSteps[stepIndex];
  const [targetRect, setTargetRect] = useState<{ top: number; left: number; right: number; bottom: number; borderRadius: string } | null>(null);
  const [dialogPlacement, setDialogPlacement] = useState<'bottom' | 'top'>('bottom');
  useEffect(() => {
    let frame = 0; let settleFrame = 0;
    setTargetRect(null);
    function measureTarget() { const target = document.querySelector(`[data-tutorial="${step.target}"]`); if (!target) { setTargetRect(null); return; } const rect = target.getBoundingClientRect(); const dialog = document.querySelector('.tutorial-dialog'); const dialogHeight = dialog?.getBoundingClientRect().height ?? 160; const compact = window.matchMedia('(max-width: 680px)').matches; const fitsBottom = rect.bottom <= window.innerHeight - dialogHeight - (compact ? 30 : 50); const fitsTop = rect.top >= dialogHeight + 30; setDialogPlacement(!fitsBottom && fitsTop ? 'top' : 'bottom'); setTargetRect({ top: rect.top, left: rect.left, right: rect.right, bottom: rect.bottom, borderRadius: getComputedStyle(target).borderRadius }); }
    const target = document.querySelector(`[data-tutorial="${step.target}"]`); if (target && step.screen !== 'landing') window.scrollTo({ top: 0, behavior: 'auto' });
    frame = window.requestAnimationFrame(() => { measureTarget(); settleFrame = window.requestAnimationFrame(measureTarget); }); window.addEventListener('resize', measureTarget); window.addEventListener('scroll', measureTarget, { passive: true });
    return () => { window.cancelAnimationFrame(frame); window.cancelAnimationFrame(settleFrame); window.removeEventListener('resize', measureTarget); window.removeEventListener('scroll', measureTarget); };
  }, [step.screen, step.target]);
  if (!step) return null;
  const padding = step.spotlight?.padding ?? 0;
  const focus = targetRect ? { top: Math.max(8, targetRect.top - padding), left: Math.max(8, targetRect.left - padding), right: Math.min(window.innerWidth - 8, targetRect.right + padding), bottom: Math.min(window.innerHeight - 8, targetRect.bottom + padding) } : null;
  const focusRadius = step.spotlight?.radius ?? targetRect?.borderRadius ?? '0px';
  return <>{focus ? <><div className="tutorial-shade tutorial-shade-top tutorial-shade-hit-area" style={{ height: `${focus.top}px` }} /><div className="tutorial-shade tutorial-shade-left tutorial-shade-hit-area" style={{ top: `${focus.top}px`, width: `${focus.left}px`, height: `${focus.bottom - focus.top}px` }} /><div className="tutorial-shade tutorial-shade-right tutorial-shade-hit-area" style={{ top: `${focus.top}px`, left: `${focus.right}px`, height: `${focus.bottom - focus.top}px` }} /><div className="tutorial-shade tutorial-shade-bottom tutorial-shade-hit-area" style={{ top: `${focus.bottom}px` }} /><div className="tutorial-focus-frame" aria-hidden="true" style={{ top: `${focus.top}px`, left: `${focus.left}px`, width: `${focus.right - focus.left}px`, height: `${focus.bottom - focus.top}px`, borderRadius: focusRadius }} /></> : <div className="tutorial-shade tutorial-shade-full" />}<section className={`tutorial-dialog${dialogPlacement === 'top' ? ' tutorial-dialog-above' : ''}`} role="dialog" aria-labelledby="tutorial-title" aria-describedby="tutorial-body"><div className="tutorial-mascot-wrap"><Mascot /></div><div className="tutorial-dialog-content"><div className="tutorial-dialog-topline"><span>{step.label}</span><button className="tutorial-skip" type="button" onClick={onSkip}>건너뛰기</button></div><h2 id="tutorial-title">{step.title}</h2><p id="tutorial-body">{step.body}</p><div className="tutorial-dialog-actions"><button className="tutorial-previous" type="button" onClick={onPrevious} disabled={stepIndex === 0}>이전</button><span className="tutorial-progress">{String(stepIndex + 1).padStart(2, '0')} / {String(tutorialSteps.length).padStart(2, '0')}</span><button className="dark-button tutorial-next" type="button" onClick={onNext}>{step.button} <span aria-hidden="true">↗</span></button></div></div></section></>;
}

function Landing({ product, mode, customerLabel, customerType, tutorialTarget, onProductChange, onModeChange, onCustomerChange, onCustomerTypeChange, onStart, onNavigate }: { product: ProductKey; mode: Mode; customerLabel: string; customerType: CustomerType; tutorialTarget: string; onProductChange: (value: ProductKey) => void; onModeChange: (value: Mode) => void; onCustomerChange: (value: string) => void; onCustomerTypeChange: (value: CustomerType) => void; onStart: () => void | Promise<void>; onNavigate: (value: NavItem) => void }) {
  const current = productConfigs[product];
  function handleSubmit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); void onStart(); }
  return <main className="landing-page"><header className="landing-topbar"><BrandMark /><nav className="landing-nav" aria-label="보조 메뉴"><button type="button" className="landing-nav-link" onClick={() => onNavigate('규정 팩')}>규정 팩</button><button type="button" className="landing-nav-link" onClick={() => onNavigate('문서')}>문서 추출</button><button type="button" className="landing-nav-link" onClick={() => onNavigate('이력')}>세션 이력</button></nav></header><div className="landing-grid"><section className="landing-story" aria-labelledby="landing-title"><div className={`landing-hero-copy${tutorialTarget === 'landing-hero' ? ' tutorial-focus' : ''}`} data-tutorial="landing-hero"><div className="eyebrow eyebrow-cyan">실시간 금융 상담 컴플라이언스</div><h1 id="landing-title">외우지 않아도,<br /><span>빠뜨리지 않습니다</span></h1><p className="landing-description">규정과 상품설명서에서 뽑은 항목을 녹음·전사 흐름에서 하나씩 확인하고,<br className="desktop-break" /> 설명했다는 근거를 남깁니다.</p></div><div className="verification-stage" aria-label="말틈이 확인하는 상담 흐름"><div className="landing-recording-badge" aria-hidden="true"><span className="landing-recording-dot" /><span className="landing-recording-bars"><i /><i /><i /><i /><i /></span><span>녹음 대기 중</span></div><div className="verification-signal signal-one" aria-hidden="true" /><div className="verification-signal signal-two" aria-hidden="true" /><div className="verification-note"><span className="note-label">말틈이 지키는 흐름</span><strong>녹음 → 전사 → 판정 → 근거<br />필요한 순간에 먼저 보여요.</strong></div><div className="verification-floor" aria-hidden="true" /><div className="verification-stack" aria-hidden="true"><div className="verification-sheet verification-sheet-back" /><div className="verification-sheet verification-sheet-mid" /><div className="verification-sheet verification-sheet-front"><div className="verification-sheet-header"><span>상담 기준</span><span>p.3</span></div><div className="verification-sheet-row"><span className="verification-sheet-dot" /><span /><span /></div><div className="verification-sheet-row"><span className="verification-sheet-dot verification-sheet-dot-cyan" /><span /><span /></div><div className="verification-sheet-status"><span>근거 확인</span><strong>✓</strong></div></div></div></div></section><form className="session-card" onSubmit={handleSubmit}><div className="card-kicker"><span className="kicker-line" aria-hidden="true" />상담 세션 시작</div><h2>녹음으로 시작하세요.</h2><p className="card-intro">기준 브리핑을 확인하면 대시보드에서 녹음이 자동 시작되고, 전사와 판정으로 이어집니다.</p><button className={`record-button${tutorialTarget === 'landing-start' ? ' tutorial-focus' : ''}`} data-tutorial="landing-start" type="submit"><span className="record-button-visual" aria-hidden="true"><span className="record-button-ring" /><span className="record-button-mic">●</span></span><span className="record-button-copy"><strong>{mode === 'live' ? '브리핑 확인 후 녹음 시작' : '녹음으로 시작하기'}</strong><small>{mode === 'live' ? '브리핑 다음 대시보드에서 마이크 자동 연결' : mode === 'text' ? '음성 없이 텍스트로 검토' : mode === 'trace' ? '저장 이벤트를 순서대로 재생' : '준비된 녹취를 재생하며 자동 체크'}</small></span><span className="record-button-arrow" aria-hidden="true">↗</span></button><div className={`recording-helper recording-helper-${mode}`}><span className="recording-pulse" /><span><strong>{mode === 'live' ? '대시보드 녹음 자동 시작' : mode === 'text' ? '텍스트 검토 준비' : mode === 'trace' ? '이벤트 재생 준비' : '녹취 자동 체크 준비'}</strong><small>{current.label} · {current.customer}</small></span><span className="recording-duration">{formatTime(current.totalSeconds)}</span></div><details className="landing-settings"><summary><span className="settings-summary-label">세션 설정</span><span className="settings-summary-value">{current.label} · {modeLabels[mode]} · {customerType === 'professional' ? '전문금융소비자' : '일반금융소비자'}</span><span className="settings-summary-arrow" aria-hidden="true">⌄</span></summary><div className="settings-panel"><fieldset className="choice-fieldset"><legend>상담 유형</legend><div className="product-options">{(Object.keys(productConfigs) as ProductKey[]).map((key) => { const item = productConfigs[key]; const selected = key === product; return <button className={`product-option${selected ? ' is-selected' : ''}`} key={key} type="button" aria-pressed={selected} onClick={() => onProductChange(key)}><span className="option-radio" aria-hidden="true">{selected ? <span /> : null}</span><span><strong>{item.label}</strong><small>{formatTime(item.totalSeconds)} 시연</small></span><span className="option-arrow" aria-hidden="true">↗</span></button>; })}</div></fieldset><fieldset className="choice-fieldset mode-fieldset"><legend>실행 모드</legend><div className="mode-options">{(Object.keys(modeLabels) as Mode[]).map((key) => <button className={`mode-option${key === mode ? ' is-selected' : ''}`} key={key} type="button" aria-pressed={key === mode} onClick={() => onModeChange(key)}>{modeLabels[key]}<small>{modeDescriptions[key]}</small></button>)}</div></fieldset><label className="text-field"><span>가상 고객 라벨 <em>선택</em></span><input value={customerLabel} onChange={(event) => onCustomerChange(event.target.value)} placeholder={current.customer} aria-label="가상 고객 라벨" /></label><label className="text-field"><span>고객 유형</span><select value={customerType} onChange={(event) => onCustomerTypeChange(event.target.value as CustomerType)} aria-label="고객 유형"><option value="general">일반금융소비자</option><option value="professional">전문금융소비자</option></select></label></div></details><p className="privacy-note"><span className="tiny-lock" aria-hidden="true">□</span>실제 개인정보는 입력하지 않습니다.</p><div className="session-card-footer"><span>브리핑</span><span>전사</span><span>판정</span><span>근거</span><span className="footer-dot" aria-hidden="true" /><span>브리핑 → 녹음 → 전사 → 판정 → 근거</span></div></form></div><footer className="landing-footer"><span>말틈 · 금융 상담을 위한 근거 기반 가이드</span><span className="footer-status"><span aria-hidden="true" /> 시스템 준비됨</span></footer></main>;
}

function Sidebar({ product, sessionId, activeNav, hasReport, onNavChange, onNewSession }: { product: ProductKey; sessionId: string; activeNav: NavItem; hasReport: boolean; onNavChange: (value: NavItem) => void; onNewSession: () => void }) { return <aside className="sidebar"><div className="sidebar-top"><BrandMark dark /><span className="workspace-label">상담 지원 워크스페이스</span></div><div className="sidebar-session"><span>현재 세션</span><strong>{productConfigs[product].label}</strong><span className="sidebar-session-id">{sessionId || '세션 준비 전'}</span></div><nav className="sidebar-nav" aria-label="주 메뉴">{navItems.map((item) => <button className={`nav-item${activeNav === item.key ? ' is-active' : ''}`} key={item.key} type="button" onClick={() => onNavChange(item.key)}><span className="nav-number" aria-hidden="true">{item.number}</span><span className="nav-icon" aria-hidden="true">{item.icon}</span><span>{item.key}</span>{item.key === '리포트' && hasReport ? <span className="nav-count">1</span> : null}</button>)}</nav><div className="sidebar-bottom"><div className="sidebar-helper"><div className="helper-avatar" aria-hidden="true">✓</div><div><strong>기준 가이드</strong><span>근거 기반 안내</span></div></div><button className="sidebar-new" type="button" onClick={onNewSession}><span aria-hidden="true">＋</span> 새 상담</button></div></aside>; }
function WorkspaceShell({ product, sessionId, activeNav, hasReport, onNavChange, onNewSession, children }: { product: ProductKey; sessionId: string; activeNav: NavItem; hasReport: boolean; onNavChange: (value: NavItem) => void; onNewSession: () => void; children: React.ReactNode }) { return <div className="product-app"><Sidebar product={product} sessionId={sessionId} activeNav={activeNav} hasReport={hasReport} onNavChange={onNavChange} onNewSession={onNewSession} />{children}</div>; }
function PageHeading({ eyebrow, title, body, action }: { eyebrow: string; title: string; body: string; action?: React.ReactNode }) { return <header className="workspace-heading"><div><span className="section-eyebrow">{eyebrow}</span><h1>{title}</h1><p>{body}</p></div>{action ? <div className="workspace-heading-action">{action}</div> : null}</header>; }

function BriefingScreen({ product, mode, customerLabel, tutorialTarget, onBack, onStart, onNavigate }: { product: ProductKey; mode: Mode; customerLabel: string; tutorialTarget: string; onBack: () => void; onStart: () => void; onNavigate: (value: NavItem) => void }) { const config = productConfigs[product]; return <WorkspaceShell product={product} sessionId="세션 생성 전" activeNav="상담" hasReport={false} onNavChange={onNavigate} onNewSession={onBack}><main className="workspace-main"><PageHeading eyebrow="상담 브리핑" title="이번 상담의 기준을 먼저 확인하세요." body="상담 중 필요한 항목과 피해야 할 표현을 짧게 확인한 뒤 라이브 화면으로 이동합니다." action={<span className="demo-pill">로컬 데모 · 서버 미연결</span>} /><section className={`briefing-card${tutorialTarget === 'briefing-card' ? ' tutorial-focus' : ''}`} data-tutorial="briefing-card"><div className="briefing-card-header"><div><span className="section-eyebrow">선택한 세션</span><h2>{config.label}</h2><p>{customerLabel || config.customer} · {modeLabels[mode]} · {config.packVersion}</p></div><span className={`pack-status pack-status-${config.packStatus}`}>{config.packStatus === 'published' ? '발행 팩' : '데모 팩'}</span></div><div className="briefing-metrics"><div><strong>{config.briefing.mustSay.length}</strong><span>필수 안내</span></div><div><strong>{config.briefing.mustNotSay.length}</strong><span>주의 표현</span></div><div><strong>{formatTime(config.totalSeconds)}</strong><span>예상 시연</span></div></div><div className="briefing-columns"><div><span className="section-eyebrow">이번 상담에서 꼭 말할 것</span><ul>{config.briefing.mustSay.map((item) => <li key={item}><StatusMark status="met" /><span>{item}</span></li>)}</ul></div><div><span className="section-eyebrow">주의할 안내</span><ul className="briefing-warning-list">{config.briefing.mustNotSay.map((item) => <li key={item}><span className="briefing-warning-mark">!</span><span>{item}</span></li>)}</ul></div></div><div className="briefing-note"><span className="note-dot" aria-hidden="true" /><span><strong>최근 기준</strong>{config.briefing.recentChange}</span></div><div className="briefing-actions"><button type="button" className="text-button" onClick={onBack}>설정으로 돌아가기</button><button type="button" className="dark-button" onClick={onStart}>상담 화면으로 이동 <span aria-hidden="true">↗</span></button></div></section></main></WorkspaceShell>; }

function RecordingInfo({ mode, config, session }: { mode: Mode; config: ProductConfig; session: SessionState }) {
  const recordingEvent = [...session.eventLog].reverse().find((event) => event.startsWith('recording:'));
  const micActive = recordingEvent === 'recording:active' && !session.ended;
  const hasTranscript = session.transcript.length > 0 || Boolean(session.partialText);
  const label = mode === 'live' ? (micActive ? '녹음·분석 중' : session.connectionState === 'connected' ? '녹음 시작 대기' : '녹음 연결 중') : mode === 'text' ? '텍스트 입력 준비' : mode === 'trace' ? '저장 이벤트 재생 중' : '녹취 재생 중';
  const detail = mode === 'live' ? (micActive ? '16kHz PCM16 업링크 · 전사·판정 진행 중' : session.connectionState === 'connected' ? '아래 녹음 시작 버튼을 눌러 입력을 켜세요.' : '서버 연결 후 녹음 버튼을 사용할 수 있습니다.') : mode === 'text' ? '음성 없이 동일 판정 경로' : mode === 'trace' ? 'TRACE · STT·LLM 미호출' : 'REPLAY · 이벤트 자동 체크';
  const serverProgress = session.remoteProgress;
  const progress = serverProgress ? Math.min(100, Math.round(((serverProgress.met + serverProgress.partial) / Math.max(1, serverProgress.itemsTotal)) * 100)) : Math.min(100, Math.round((session.currentSeconds / config.totalSeconds) * 100));
  const recordingClass = mode === 'live' && !micActive ? 'is-current' : 'is-complete';
  const transcriptClass = hasTranscript ? 'is-complete' : mode === 'live' && micActive ? 'is-current' : '';
  const verdictClass = session.activeIntervention || serverProgress ? 'is-current' : '';
  const evidenceClass = session.activeIntervention?.evidenceCode || session.remoteProgress ? 'is-current' : '';
  return <section className={`recording-strip recording-strip-${mode}${session.eventCursor > 0 || serverProgress || micActive ? ' is-active' : ''}`} data-tutorial="dashboard-recording" aria-label="녹음과 분석 진행 상태"><div className="recording-strip-main"><div className="recording-strip-label"><span className="recording-wave-icon" aria-hidden="true"><i /><i /><i /><i /><i /></span><span><strong>{label}</strong><small>{detail}</small></span></div><span className="recording-time">{formatTime(session.currentSeconds)} <b>/</b> {formatTime(config.totalSeconds)}</span></div><div className="recording-progress" aria-hidden="true"><span style={{ width: `${progress}%` }} /></div><div className="recording-flow" aria-label="녹음에서 근거 확인까지의 처리 흐름"><span className={recordingClass}><b>01</b> 녹음</span><b aria-hidden="true">→</b><span className={transcriptClass}><b>02</b> 전사</span><b aria-hidden="true">→</b><span className={verdictClass}><b>03</b> 판정</span><b aria-hidden="true">→</b><span className={evidenceClass}><b>04</b> 근거</span></div></section>;
}

function AttentionCard({ intervention, onOpenEvidence, onResolve, onAcknowledge }: { intervention: Intervention | null; onOpenEvidence: (code: string) => void; onResolve: () => void; onAcknowledge: () => void }) { if (!intervention) return <article className="attention-card attention-card-empty" data-tutorial="dashboard-attention"><div className="attention-empty-mark" aria-hidden="true">✓</div><div><span className="section-eyebrow">03 · 판정·개입</span><h2>지금은 확인이 필요한 개입이 없습니다.</h2><p>새 발화가 들어오면 가장 중요한 한 가지를 이 자리에 보여줍니다.</p></div></article>; const isComparison = intervention.kind === 'number' || intervention.kind === 'forbidden'; return <article className={`attention-card attention-card-${intervention.kind}`} data-tutorial="dashboard-attention"><div className="attention-header"><span className="flow-stage-label">03 · 판정·개입</span><span className="attention-pill">{intervention.label}</span><span className="attention-time">{formatTime(intervention.time)}</span></div><div className="attention-title-row"><div><h2>{intervention.title}</h2><p>{intervention.body}</p></div><span className={`severity-mark severity-${intervention.severity ?? 'info'}`}>{intervention.severity === 'critical' ? '즉시 확인' : '기준 확인'}</span></div>{intervention.quote ? <div className="quote-line">{intervention.quote}</div> : null}{isComparison ? <div className="comparison-grid"><div className="comparison-cell spoken-cell"><span>말씀</span><strong>{intervention.spoken}</strong><small>현재 발화</small></div><div className="comparison-operator" aria-hidden="true">≠</div><div className="comparison-cell reference-cell"><span>설명서 기준</span><strong>{intervention.reference}</strong><small>{intervention.caption}</small></div></div> : <div className="intervention-support"><span className="support-line"><strong>다음 행동</strong><span>고객이 보는 화면에서도 차분하게 확인할 수 있는 안내입니다.</span></span></div>}<div className="attention-footer"><span className="source-caption"><span className="source-mark" aria-hidden="true" />{intervention.source ?? '연결된 근거를 준비 중'}</span><div className="attention-actions">{intervention.evidenceCode ? <button className="text-button" type="button" onClick={() => onOpenEvidence(intervention.evidenceCode as string)}>근거 원문 보기 <span aria-hidden="true">↗</span></button> : null}<button className="dark-button" type="button" onClick={intervention.kind === 'risk' ? onAcknowledge : onResolve}>{intervention.kind === 'risk' ? '확인 기록' : '확인했어요'}</button></div></div></article>; }

function ChecklistCard({ items, selectedCode, onSelect, onMarkMet, onOpenWaive }: { items: ChecklistItem[]; selectedCode: string; onSelect: (code: string) => void; onMarkMet: (code: string) => void; onOpenWaive: () => void }) { const selected = items.find((item) => item.code === selectedCode) ?? items[0]; const metCount = items.filter((item) => item.status === 'met').length; return <article className="checklist-card"><div className="checklist-header"><div><span className="section-eyebrow">04 · 수동 보완</span><h2>진행 상태</h2></div><strong>{metCount} <small>/ {items.length}</small></strong></div><div className="progress-track"><span style={{ width: `${(metCount / items.length) * 100}%` }} /></div><div className="checklist-items" data-tutorial="dashboard-checklist">{items.map((item) => <button className={`checklist-item${selectedCode === item.code ? ' is-selected' : ''}`} key={item.code} type="button" onClick={() => onSelect(item.code)}><StatusMark status={item.status} /><span className="checklist-copy"><strong>{item.label}</strong><small>{statusLabel(item.status)} · {item.source}</small></span><span className="checklist-chevron" aria-hidden="true">›</span></button>)}</div><div className="manual-actions"><span>사람이 보완할 수 있어요</span>{selected.status === 'unmet' || selected.status === 'partial' ? <><button type="button" onClick={() => onMarkMet(selected.code)}>고지 완료 기록</button><button type="button" onClick={onOpenWaive}>범위에서 제외</button></> : <span className="manual-state">{selected.status === 'met' ? '자동 또는 사람 기록 완료' : '제외 사유 기록됨'}</span>}</div><div className="density-row"><span>전문용어 밀도</span><strong>보통</strong></div></article>; }

function EvidenceCard({ item, evidenceItem, onOpenEvidence }: { item: ChecklistItem; evidenceItem: Evidence; onOpenEvidence: (code: string) => void }) { return <article className="evidence-card"><div className="evidence-heading"><div><span className="section-eyebrow">05 · 근거 확인</span><h2>{item.label}</h2></div><span className="evidence-page">p.{evidenceItem.page}</span></div><div className="evidence-content" data-tutorial="dashboard-evidence"><div className="document-preview"><div className="document-topline"><span>{evidenceItem.doc}</span><span>p.{evidenceItem.page}</span></div><div className="document-copy"><p>{evidenceItem.span}</p></div></div><div className="evidence-meta"><span>{evidenceItem.legalBasis}</span><span>ref · {evidenceItem.ref}</span></div><button className="evidence-link" type="button" onClick={() => onOpenEvidence(item.evidenceCode)}>원문 전체 보기 <span aria-hidden="true">↗</span></button></div></article>; }

function Dashboard({ session, health, healthError, onAdvance, onEnd, onNewSession, onNavigate, onOpenEvidence, onResolveIntervention, onAcknowledge, onAsk, onTextUtterance, onMarkMet, onMarkWaive, onRetryConnection, onFallbackToText, onStartMic, onStopMic, micActive, micError, onAssistRequest }: { session: SessionState; health: ApiHealth | null; healthError?: string; onAdvance: () => void; onEnd: () => void; onNewSession: () => void; onNavigate: (value: NavItem) => void; onOpenEvidence: (code: string) => void; onResolveIntervention: () => void; onAcknowledge: () => void; onAsk: (question: string) => void; onTextUtterance: (text: string, speaker: Speaker) => void; onMarkMet: (code: string) => void; onMarkWaive: (code: string, reason: string) => void; onRetryConnection: () => void; onFallbackToText: () => void; onStartMic: () => void; onStopMic: () => void; micActive: boolean; micError?: string; onAssistRequest: (type: 'rephrase' | 'documents' | 'briefing') => void }) {
  const config = productConfigs[session.product];
  const [selectedCode, setSelectedCode] = useState(session.checklist[1]?.code ?? session.checklist[0]?.code ?? '');
  const [query, setQuery] = useState(''); const [text, setText] = useState(''); const [speaker, setSpeaker] = useState<Speaker>('teller'); const [waiveOpen, setWaiveOpen] = useState(false); const [waiveReason, setWaiveReason] = useState('');
  const selectedItem = session.checklist.find((item) => item.code === selectedCode) ?? session.checklist[0]; const selectedEvidenceRef = selectedItem ? session.evidenceRefsByCode[selectedItem.evidenceCode] : undefined; const selectedEvidence = selectedItem ? session.remoteEvidence[selectedEvidenceRef ?? ''] ?? config.evidence[selectedItem.evidenceCode] ?? { ref: selectedEvidenceRef ?? selectedItem.evidenceCode, doc: config.document, page: 1, span: selectedItem.plainLanguage, quote: selectedItem.plainLanguage, legalBasis: '서버 기준 항목' } : null; const completedCount = session.remoteProgress?.met ?? session.checklist.filter((item) => item.status === 'met').length;
  const connectionStatus = connectionLabel(session.connectionState);
  useEffect(() => { setSelectedCode(session.checklist[1]?.code ?? session.checklist[0]?.code ?? ''); }, [session.sessionId]);
  useEffect(() => { const localReplayReady = session.connectionState !== 'connected' || session.localReplay || session.serverEventCount === 0; if ((session.mode === 'replay' || session.mode === 'trace') && localReplayReady && !session.ended && session.eventCursor < config.events.length) { const timer = window.setTimeout(onAdvance, 1550); return () => window.clearTimeout(timer); } return undefined; }, [config.events.length, onAdvance, session.connectionState, session.ended, session.eventCursor, session.localReplay, session.mode, session.serverEventCount]);
  function handleQuery(event: FormEvent<HTMLFormElement>) { event.preventDefault(); if (query.trim()) { onAsk(query.trim()); setQuery(''); } }
  function handleText(event: FormEvent<HTMLFormElement>) { event.preventDefault(); if (text.trim()) { onTextUtterance(text.trim(), speaker); setText(''); } }
  function handleWaive(event: FormEvent<HTMLFormElement>) { event.preventDefault(); if (selectedItem && waiveReason.trim()) { onMarkWaive(selectedItem.code, waiveReason.trim()); setWaiveReason(''); setWaiveOpen(false); } }
  const recordingClass = session.mode === 'live' ? 'live' : session.mode === 'text' ? 'text' : session.mode === 'trace' ? 'trace' : 'replay';
  return <div className="product-app dashboard-relaunch-shell"><Sidebar product={session.product} sessionId={session.sessionId} activeNav="상담" hasReport={session.ended} onNavChange={onNavigate} onNewSession={onNewSession} /><main className="dashboard-main"><header className="dashboard-header" data-tutorial="dashboard-header"><div><span className="breadcrumb">상담 <span>/</span> {config.label}</span><h1>상담 라이브</h1></div><div className="dashboard-actions"><span className="connection-status connection-demo"><span aria-hidden="true" /> {connectionStatus}</span><span className={`recording-badge recording-badge-${recordingClass}`}><span aria-hidden="true" /> {modeLabels[session.mode]}</span><span className="mode-badge">{session.mode === 'trace' ? '저장 이벤트' : '시연 모드'}</span><span className="elapsed-time">{formatTime(session.currentSeconds)}</span><button className="header-new header-end" type="button" onClick={onEnd} disabled={session.ended}>상담 종료</button><button className="header-new" type="button" onClick={onNewSession}>새 상담</button></div></header><RecordingInfo mode={session.mode} config={config} session={session} /><RuntimeBanner session={session} health={health} healthError={healthError} micActive={micActive} micError={micError} onRetry={onRetryConnection} onFallbackToText={onFallbackToText} onStartMic={onStartMic} onStopMic={onStopMic} onAssistRequest={onAssistRequest} />{session.mode === 'live' ? <div className="mode-notice"><strong>{session.connectionState === 'connected' ? 'LIVE 입력 연결됨' : 'LIVE 입력 준비'}</strong><span>{session.connectionState === 'connected' ? '마이크를 연결하면 16kHz PCM16 오디오 프레임을 서버로 전송합니다.' : '서버가 연결되지 않으면 TEXT 폴백 또는 이벤트 한 건씩 보기로 흐름을 확인할 수 있습니다.'}</span>{session.connectionState !== 'connected' ? <button type="button" onClick={onAdvance}>다음 데모 이벤트</button> : null}</div> : null}{session.mode === 'text' ? <form className="text-utterance-composer" onSubmit={handleText}><span className="section-eyebrow">TEXT 입력</span><select value={speaker} onChange={(event) => setSpeaker(event.target.value as Speaker)} aria-label="화자 선택"><option value="teller">은행원</option><option value="customer">고객</option></select><input value={text} onChange={(event) => setText(event.target.value)} placeholder="발화를 입력해 동일 판정 경로로 보냅니다" /><button type="submit" className="dark-button">발화 보내기 <span aria-hidden="true">↗</span></button></form> : null}<section className="session-overview" data-tutorial="dashboard-overview"><div className="overview-product"><span className="overview-label">현재 상담</span><strong>{config.label}</strong><span>{session.customerLabel || config.customer} · {config.document}</span></div><div className="overview-metrics"><div><span className="metric-icon metric-icon-check" aria-hidden="true">✓</span><div className="metric-copy"><span>필수 안내</span><strong>{completedCount}<small> / {session.checklist.length}</small></strong></div></div><div><span className="metric-icon metric-icon-alert" aria-hidden="true">!</span><div className="metric-copy"><span>개입 필요</span><strong className={session.activeIntervention ? 'metric-warn' : ''}>{session.activeIntervention ? '1' : '0'}</strong></div></div><div><span className="metric-icon metric-icon-live" aria-hidden="true">●</span><div className="metric-copy"><span>상담 상태</span><strong className="metric-live">{session.ended ? '종료됨' : '진행 중'}</strong></div></div></div></section><div className="dashboard-layout"><section className="primary-column"><AttentionCard intervention={session.activeIntervention} onOpenEvidence={onOpenEvidence} onResolve={onResolveIntervention} onAcknowledge={onAcknowledge} /><article className="transcript-card"><div className="section-heading"><div><span className="section-eyebrow">실시간 전사</span><h2>상담 흐름</h2></div><span className="live-indicator"><span aria-hidden="true" /> {session.mode === 'trace' ? 'TRACE' : 'LIVE'}</span></div><div className="transcript-list" data-tutorial="dashboard-transcript">{session.transcript.length ? session.transcript.map((row) => <div className={`transcript-row${row.highlighted ? ' is-highlighted' : ''}`} key={row.id}><span className={`speaker speaker-${row.speaker}`}>{speakerLabel(row.speaker)}</span><p>{row.text}</p><time>{formatTime(row.time)}</time></div>) : <div className="transcript-empty"><span aria-hidden="true">…</span>첫 발화를 기다리는 중입니다.</div>}</div><form className="query-bar" data-tutorial="dashboard-query" onSubmit={handleQuery}><span className="query-icon" aria-hidden="true">?</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="규정을 직접 물어보세요" aria-label="규정 질의" /><button type="submit" aria-label="질의 보내기">↗</button></form>{session.queryResult ? <div className={`query-answer${session.queryResult.answer ? '' : ' query-answer-empty'}`}><div className="query-answer-label">기준 가이드의 답변</div><p>{session.queryResult.answer ?? '근거를 찾지 못했습니다. 담당 부서 확인이 필요합니다.'}</p>{session.queryResult.evidenceCode ? <button className="text-button" type="button" onClick={() => onOpenEvidence(session.queryResult?.evidenceCode as string)}>근거 원문 보기 <span aria-hidden="true">↗</span></button> : <span className="query-fallback-note">근거 없는 답변은 만들지 않습니다.</span>}</div> : null}</article></section><aside className="secondary-column">{selectedItem && selectedEvidence ? <><ChecklistCard items={session.checklist} selectedCode={selectedCode} onSelect={setSelectedCode} onMarkMet={onMarkMet} onOpenWaive={() => setWaiveOpen(true)} />{waiveOpen ? <form className="waive-form" onSubmit={handleWaive}><label><span>제외 사유</span><input autoFocus value={waiveReason} onChange={(event) => setWaiveReason(event.target.value)} placeholder="예: 고객이 해당 대안을 원하지 않음" /></label><div><button type="button" className="text-button" onClick={() => setWaiveOpen(false)}>취소</button><button type="submit" className="dark-button">제외 기록</button></div></form> : null}<EvidenceCard item={selectedItem} evidenceItem={selectedEvidence} onOpenEvidence={onOpenEvidence} /></> : null}</aside></div><footer className="dashboard-footer"><span>{session.connectionState === 'connected' && !session.localReplay ? '서버 이벤트 · append-only' : '로컬 이벤트 기록 · 폴백 시연'}</span><span>계약 팩 {config.packVersion} {config.packStatus === 'demo' ? '· 데모' : ''}</span><span>{session.eventCursor >= config.events.length ? '시연 이벤트 완료' : `다음 이벤트 ${formatTime(config.events[session.eventCursor]?.at ?? config.totalSeconds)}`}</span></footer></main></div>;
}

function EvidenceModal({ evidenceItem, packVersion, onClose }: { evidenceItem: Evidence; packVersion: string; onClose: () => void }) {
  const bboxStyle = evidenceItem.bbox && evidenceItem.pageSize ? {
    left: `${(evidenceItem.bbox[0] / evidenceItem.pageSize[0]) * 100}%`,
    top: `${((evidenceItem.pageSize[1] - evidenceItem.bbox[3]) / evidenceItem.pageSize[1]) * 100}%`,
    width: `${((evidenceItem.bbox[2] - evidenceItem.bbox[0]) / evidenceItem.pageSize[0]) * 100}%`,
    height: `${((evidenceItem.bbox[3] - evidenceItem.bbox[1]) / evidenceItem.pageSize[1]) * 100}%`,
  } : undefined;
  return <div className="evidence-overlay" role="presentation" onClick={onClose}><section className="evidence-modal" role="dialog" aria-modal="true" aria-labelledby="evidence-title" onClick={(event) => event.stopPropagation()}><div className="modal-header"><div><span className="section-eyebrow">근거 원문</span><h2 id="evidence-title">{evidenceItem.legalBasis ?? evidenceItem.doc}</h2></div><button className="modal-close" type="button" onClick={onClose} aria-label="근거 원문 닫기">×</button></div><div className="modal-meta"><span>{evidenceItem.doc}</span><span>p.{evidenceItem.page}</span><span>pack_version · {packVersion}</span><span>evidence_ref · {evidenceItem.ref}</span></div>{evidenceItem.pageImageUrl ? <div className="modal-page-image-wrap"><img className="modal-page-image" src={evidenceItem.pageImageUrl} alt={`${evidenceItem.doc} ${evidenceItem.page}페이지`} />{bboxStyle ? <span className="modal-bbox" style={bboxStyle} aria-label="근거 위치" /> : null}</div> : <div className="modal-document"><div className="modal-page-number">{evidenceItem.page}</div><div className="modal-document-text"><span className="document-line short" /><span className="document-line" /><span className="document-line medium" /><span className="document-line" /><span className="document-line highlighted" /><span className="document-line highlighted short" /><span className="document-line" /><span className="document-line medium" /></div><div className="modal-quote">“{evidenceItem.quote}”</div></div>}<div className="evidence-span-block"><span className="section-eyebrow">원문 span</span><p>{evidenceItem.span}</p></div><div className="modal-footer"><span>{evidenceItem.pageImageUrl ? '서버 페이지 이미지 · bbox 위치 표시' : '로컬 프리뷰 · 서버 evidence API 연결 시 페이지 이미지를 표시합니다.'}</span><button className="dark-button" type="button" onClick={onClose}>닫기</button></div></section></div>;
}

function ReportScreen({ session, onNewSession, onOpenEvidence, onNavigate, onPrint }: { session: SessionState | null; onNewSession: () => void; onOpenEvidence: (code: string) => void; onNavigate: (value: NavItem) => void; onPrint: () => void }) { if (!session || !session.ended) return <WorkspaceShell product={session?.product ?? 'deposit'} sessionId={session?.sessionId ?? '세션 없음'} activeNav="리포트" hasReport={false} onNavChange={onNavigate} onNewSession={onNewSession}><main className="workspace-main"><PageHeading eyebrow="종료 리포트" title="상담을 종료하면 증빙이 나타납니다." body="세션 종료 후 항목별 상태와 근거를 확인할 수 있습니다." /><div className="empty-state"><div className="empty-state-mark">02</div><h2>아직 종료된 상담이 없습니다.</h2><p>상담을 시작하고 이벤트를 확인한 뒤 종료하면 이곳에서 JSON 요약과 PDF 저장 경로를 볼 수 있습니다.</p><button className="dark-button" type="button" onClick={() => onNavigate('상담')}>상담으로 돌아가기 <span aria-hidden="true">↗</span></button></div></main></WorkspaceShell>; const config = productConfigs[session.product]; const met = session.checklist.filter((item) => item.status === 'met').length; const partial = session.checklist.filter((item) => item.status === 'partial').length; const unmet = session.checklist.filter((item) => item.status === 'unmet').length; return <WorkspaceShell product={session.product} sessionId={session.sessionId} activeNav="리포트" hasReport onNavChange={onNavigate} onNewSession={onNewSession}><main className="workspace-main report-page"><PageHeading eyebrow="S2 · 종료 리포트" title="상담 증빙을 확인하세요." body={`${config.label} · ${session.customerLabel} · ${session.report?.pack_version ?? config.packVersion}`} action={<><button className="outline-button" type="button" onClick={onPrint}>PDF로 저장</button><button className="dark-button" type="button" onClick={onNewSession}>새 상담</button></>} /><div className="report-status-line"><span className="report-complete-dot" /> {session.report ? '서버 리포트 수신' : '로컬 요약'} · {session.eventLog.length}개 이벤트 기록 · 근거 연결 가능</div><section className="report-summary-grid"><div className="report-summary-card"><span>고지</span><strong>{met}</strong><small>/ {session.checklist.length}</small></div><div className="report-summary-card"><span>부분 고지</span><strong>{partial}</strong><small>항목</small></div><div className="report-summary-card"><span>미고지</span><strong>{unmet}</strong><small>항목</small></div><div className="report-summary-card report-summary-risk"><span>경보·위반</span><strong>{session.alertCount}</strong><small>경보 · 위반 {session.violationCount}</small></div></section><section className="report-card"><div className="report-card-heading"><div><span className="section-eyebrow">항목별 증빙</span><h2>설명 이행 상태</h2></div><span className="report-meta">{formatTime(session.currentSeconds)} 상담</span></div><div className="report-table"><div className="report-table-head"><span>항목</span><span>상태</span><span>근거</span><span>행동</span></div>{session.checklist.map((item) => { const itemRef = session.evidenceRefsByCode[item.code]; const itemEvidence = session.remoteEvidence[itemRef ?? ''] ?? config.evidence[item.evidenceCode]; const transcript = session.transcript.find((row) => row.text.includes(item.label.split(' ')[0])); return <div className="report-table-row" key={item.code}><div><strong>{item.label}</strong><small>{item.code}</small></div><span className={`report-state report-state-${statusClass(item.status)}`}>{statusLabel(item.status)}</span><span>p.{itemEvidence.page} · {itemEvidence.ref}</span><button className="text-button" type="button" onClick={() => onOpenEvidence(item.code)}>원문 보기 ↗</button>{transcript ? <small className="report-time">발화 {formatTime(transcript.time)}</small> : null}</div>; })}</div></section><section className="report-followup"><div><span className="section-eyebrow">후속 확인</span><h2>리포트는 사실을 나눠서 남깁니다.</h2><p>고지 상태, 금지·숫자 경보, 위험 신호, assist 채택 결과를 한 값으로 합치지 않고 각각 기록합니다.</p></div><div className="followup-list"><span><b>{session.assistAdopted}</b> assist 채택</span><span><b>{session.acknowledgedCount}</b> 경보 확인</span><span><b>{session.report?.pack_version ?? config.packVersion}</b> 기준 팩</span></div></section></main></WorkspaceShell>; }

function PackScreen({ product, onNavigate, onNewSession }: { product: ProductKey; onNavigate: (value: NavItem) => void; onNewSession: () => void }) {
  const config = productConfigs[product];
  const [remotePacks, setRemotePacks] = useState<ApiPackSummary[]>([]);
  const [apiState, setApiState] = useState<'loading' | 'ready' | 'fallback'>('loading');
  useEffect(() => { let active = true; malteumApi.packs(config.productCode).then((result) => { if (active) { setRemotePacks(result.packs ?? []); setApiState('ready'); } }).catch(() => { if (active) setApiState('fallback'); }); return () => { active = false; }; }, [config.productCode]);
  return <WorkspaceShell product={product} sessionId="운영 화면" activeNav="규정 팩" hasReport={false} onNavChange={onNavigate} onNewSession={onNewSession}><main className="workspace-main utility-page"><PageHeading eyebrow="S3 · 규정 팩" title="상담 기준을 버전으로 관리합니다." body="팩은 문서에서 추출하고 사람의 승인 후 발행되는 불변 기준입니다." action={<span className="demo-pill">{apiState === 'ready' ? '팩 API 연결됨' : apiState === 'loading' ? '팩 목록 확인 중' : '프론트 기준 팩'}</span>} /><section className="pack-hero"><div><span className="section-eyebrow">현재 선택된 팩</span><h2>{config.packVersion}</h2><p>{config.productCode} · {config.label} · {config.packStatus === 'published' ? '발행 완료' : '주담대 데모 팩'}</p></div><span className={`pack-status pack-status-${config.packStatus}`}>{config.packStatus === 'published' ? 'PUBLISHED' : 'DEMO'}</span></section>{remotePacks.length ? <section className="remote-pack-list"><div className="utility-card-heading"><div><span className="section-eyebrow">서버 팩 목록</span><h2>현재 API에 등록된 기준</h2></div><span>{remotePacks.length}개</span></div>{remotePacks.map((pack) => <div className="remote-pack-row" key={pack.pack_version}><strong>{pack.pack_version}</strong><span>{pack.product?.name ?? pack.product?.code ?? '상품 정보 없음'}</span><span>{pack.item_count ?? 0}개 항목</span></div>)}</section> : null}<div className="pack-grid"><section className="utility-card"><div className="utility-card-heading"><span className="section-eyebrow">항목 구성</span><strong>{config.checklist.length} required</strong></div>{config.checklist.map((item) => <div className="pack-item-row" key={item.code}><span className="pack-item-code">{item.code}</span><strong>{item.label}</strong><span>p.{config.evidence[item.evidenceCode].page}</span></div>)}<div className="pack-item-row pack-item-muted"><span>금지</span><strong>{config.briefing.mustNotSay.length}개 주의 표현</strong><span>검수 필요</span></div></section><section className="utility-card"><span className="section-eyebrow">팩 연결 흐름</span><div className="pack-flow"><span className="is-done">문서</span><b>→</b><span className="is-done">추출</span><b>→</b><span className="is-current">근거 검증</span><b>→</b><span>승인</span><b>→</b><span>발행</span></div><p className="utility-note">최근 기준: {config.briefing.recentChange}</p><button className="outline-button full-button" type="button" onClick={() => onNavigate('문서')}>문서 검수 열기 <span aria-hidden="true">↗</span></button></section></div></main></WorkspaceShell>;
}

function DocumentsScreen({ product, onNavigate, onNewSession }: { product: ProductKey; onNavigate: (value: NavItem) => void; onNewSession: () => void }) {
  const config = productConfigs[product];
  const [approved, setApproved] = useState<string[]>([]);
  const [documents, setDocuments] = useState<ApiDocument[]>([]);
  const [remoteCandidates, setRemoteCandidates] = useState<ApiCandidate[]>([]);
  const [activeDocId, setActiveDocId] = useState('');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadState, setUploadState] = useState<'loading' | 'ready' | 'uploading' | 'extracting' | 'fallback'>('loading');
  const [uploadMessage, setUploadMessage] = useState('');
  const [approving, setApproving] = useState('');
  useEffect(() => { let active = true; malteumApi.documents().then((result) => { if (active) { setDocuments(result.documents ?? []); setUploadState('ready'); } }).catch(() => { if (active) setUploadState('fallback'); }); return () => { active = false; }; }, []);
  useEffect(() => { if (!activeDocId) return undefined; let active = true; const load = () => { malteumApi.candidates(activeDocId).then((result) => { if (active) { setRemoteCandidates(result.candidates ?? []); setUploadState('ready'); } }).catch(() => undefined); }; load(); const timer = window.setInterval(load, 4000); return () => { active = false; window.clearInterval(timer); }; }, [activeDocId]);
  async function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setSelectedFile(file); setUploadState('uploading'); setUploadMessage('문서를 서버에 업로드하는 중입니다.');
    const docId = `WEB-${Date.now()}`;
    try {
      const result = await malteumApi.uploadDocument(file, { docId, title: file.name, publisher: '금융보안원 대회 검수팀', snapshotDate: new Date().toISOString().slice(0, 10) });
      setActiveDocId(result.doc_id); setUploadState('extracting'); setUploadMessage('업로드 완료 · 구조 추출과 후보 생성을 기다리는 중입니다.');
      const nextDocuments = await malteumApi.documents().catch(() => ({ documents: [] as ApiDocument[] }));
      setDocuments(nextDocuments.documents ?? []);
    } catch (error: unknown) {
      setUploadState('fallback'); setUploadMessage(error instanceof ApiError ? `서버 업로드를 사용할 수 없어 로컬 검수로 계속합니다: ${error.message}` : '서버 업로드를 사용할 수 없어 로컬 검수로 계속합니다.');
    }
  }
  async function approveCandidate(candidate: ApiCandidate | null, localCode: string) {
    const key = candidate?.candidate_id ?? localCode;
    if (!candidate || !activeDocId) { setApproved((current) => current.includes(key) ? current : [...current, key]); return; }
    setApproving(key);
    try { await malteumApi.approveCandidate(activeDocId, candidate.candidate_id, 'front-reviewer'); setApproved((current) => current.includes(key) ? current : [...current, key]); setRemoteCandidates((current) => current.map((item) => item.candidate_id === key ? { ...item, status: 'approved' } : item)); } catch (error: unknown) { setUploadMessage(error instanceof ApiError ? `승인에 실패했습니다: ${error.message}` : '승인에 실패했습니다.'); } finally { setApproving(''); }
  }
  const rows = remoteCandidates.length ? remoteCandidates.map((candidate) => ({ id: candidate.candidate_id, code: candidate.suggested_code ?? candidate.candidate_id, label: candidate.name, meta: `후보 ${candidate.candidate_id} · p.${candidate.evidence?.page ?? '-'}`, verified: candidate.span_verified === true, candidate })) : config.checklist.slice(0, 5).map((item, index) => ({ id: item.code, code: item.code, label: item.label, meta: `${item.code} · p.${config.evidence[item.evidenceCode].page}`, verified: index !== 2, candidate: null as ApiCandidate | null }));
  const stateLabel = uploadState === 'uploading' ? '업로드 중' : uploadState === 'extracting' ? '추출 중' : uploadState === 'fallback' ? '로컬 검수' : '검수 가능';
  return <WorkspaceShell product={product} sessionId="운영 화면" activeNav="문서" hasReport={false} onNavChange={onNavigate} onNewSession={onNewSession}><main className="workspace-main utility-page"><PageHeading eyebrow="S4 · 문서 추출·검수" title="근거가 확인된 항목만 팩에 넣습니다." body="추출 결과와 원문 span을 확인하고, 검증된 후보만 승인할 수 있습니다." action={<span className="demo-pill">{uploadState === 'ready' ? '문서 API 연결됨' : stateLabel}</span>} /><section className="upload-card"><div className="upload-icon" aria-hidden="true">＋</div><div><h2>{selectedFile ? selectedFile.name : '문서 업로드 영역'}</h2><p>{uploadMessage || 'PDF를 올리면 구조 추출 → span 검증 → 후보 검수 순서로 진행됩니다.'}</p></div><label htmlFor="document-file" className="outline-button">PDF 선택</label><input id="document-file" className="file-input-hidden" type="file" accept=".pdf,application/pdf" onChange={handleFileChange} /></section>{documents.length ? <section className="remote-document-list"><div className="utility-card-heading"><div><span className="section-eyebrow">서버 문서</span><h2>업로드·추출 상태</h2></div><span>{documents.length}개</span></div>{documents.map((document) => <button type="button" className={`remote-document-row${activeDocId === document.doc_id ? ' is-selected' : ''}`} key={document.doc_id} onClick={() => { setActiveDocId(document.doc_id); setRemoteCandidates([]); }}><span><strong>{document.title}</strong><small>{document.doc_id} · {document.publisher}</small></span><span className={`document-state document-state-${document.status}`}>{document.status === 'ready' ? '추출 완료' : document.status === 'extracting' ? '추출 중' : '실패'}</span></button>)}</section> : null}<section className="utility-card candidate-card"><div className="utility-card-heading"><div><span className="section-eyebrow">{remoteCandidates.length ? `서버 추출 결과 · ${activeDocId}` : `로컬 추출 결과 · ${config.document}`}</span><h2>후보 항목 검수</h2></div><span className="extraction-status">{stateLabel}</span></div>{rows.map((row) => { const isApproved = approved.includes(row.id) || row.candidate?.status === 'approved'; return <div className="candidate-row" key={row.id}><div><strong>{row.label}</strong><small>{row.meta}</small></div><span className={row.verified ? 'span-verified' : 'span-unverified'}>{row.verified ? 'span verified' : 'span 확인 필요'}</span>{isApproved ? <span className="candidate-approved">승인됨</span> : <button className="text-button" type="button" disabled={!row.verified || approving === row.id} onClick={() => void approveCandidate(row.candidate, row.code)}>{!row.verified ? '승인 잠김' : approving === row.id ? '승인 중' : '승인'}</button>}</div>; })}<div className="candidate-footer"><span>검증되지 않은 후보는 승인하지 않습니다.</span><button className="dark-button" type="button" onClick={() => onNavigate('규정 팩')}>{approved.length ? `${approved.length}개 승인 · 팩 미리보기` : '팩 발행 준비'}</button></div></section></main></WorkspaceShell>;
}

function HistoryScreen({ records, onOpenReport, onOpenRemoteReport, onTrace, onNavigate, onNewSession }: { records: SessionState[]; onOpenReport: (record: SessionState) => void; onOpenRemoteReport: (record: ApiSessionSummary) => void; onTrace: (record: SessionState) => void; onNavigate: (value: NavItem) => void; onNewSession: () => void }) {
  const [remoteSessions, setRemoteSessions] = useState<ApiSessionSummary[]>([]);
  const [remoteState, setRemoteState] = useState<'loading' | 'ready' | 'fallback'>('loading');
  useEffect(() => { let active = true; malteumApi.sessions().then((result) => { if (active) { setRemoteSessions(result.sessions ?? []); setRemoteState('ready'); } }).catch(() => { if (active) setRemoteState('fallback'); }); return () => { active = false; }; }, []);
  const remoteOnly = remoteSessions.filter((remote) => !records.some((record) => record.sessionId === remote.session_id));
  const hasRecords = records.length > 0 || remoteOnly.length > 0;
  return <WorkspaceShell product={records[0]?.product ?? 'deposit'} sessionId="세션 이력" activeNav="이력" hasReport={hasRecords} onNavChange={onNavigate} onNewSession={onNewSession}><main className="workspace-main utility-page"><PageHeading eyebrow="S5 · 세션 이력" title="지난 상담을 다시 확인합니다." body="날짜·상품·모드·결과로 세션을 찾고, trace로 같은 이벤트를 재생합니다." action={<span className="demo-pill">{remoteState === 'ready' ? '세션 API 연결됨' : remoteState === 'loading' ? '이력 확인 중' : '브라우저 로컬 보관'}</span>} />{hasRecords ? <section className="history-list">{records.map((record) => { const config = productConfigs[record.product]; const met = record.checklist.filter((item) => item.status === 'met').length; return <article className="history-row" key={record.sessionId}><div className="history-date"><span>로컬 저장</span><strong>{record.sessionId}</strong></div><div className="history-main"><strong>{config.label}</strong><span>{record.customerLabel} · {modeLabels[record.mode]} · {formatTime(record.currentSeconds)}</span></div><div className="history-result"><span>{met}/{record.checklist.length} 고지</span><span>{record.alertCount} 경보</span></div><div className="history-actions"><button className="text-button" type="button" onClick={() => onOpenReport(record)}>리포트</button><button className="outline-button" type="button" onClick={() => onTrace(record)}>TRACE 재생</button></div></article>; })}{remoteOnly.map((record) => { const productKey: ProductKey = record.pack_version.startsWith('MTG') || record.product_name?.includes('대출') ? 'mortgage' : 'deposit'; const config = productConfigs[productKey]; return <article className="history-row history-row-remote" key={record.session_id}><div className="history-date"><span>{record.ended_at ? new Date(record.ended_at).toLocaleDateString('ko-KR') : '진행 중'}</span><strong>{record.session_id}</strong></div><div className="history-main"><strong>{record.product_name ?? config.label}</strong><span>서버 세션 · {modeLabels[record.mode]} · {record.pack_version}</span></div><div className="history-result"><span>{record.met ?? 0}/{record.items_total ?? config.checklist.length} 고지</span><span>{record.violations ?? 0} 위반</span></div><div className="history-actions"><button className="text-button" type="button" onClick={() => onOpenRemoteReport(record)}>서버 리포트</button><span className="remote-session-status">{record.status}</span></div></article>; })}</section> : <div className="empty-state"><div className="empty-state-mark">05</div><h2>아직 저장된 세션이 없습니다.</h2><p>상담을 종료하면 이곳에 세션 요약과 trace 재생 버튼이 생깁니다.</p><button className="dark-button" type="button" onClick={() => onNavigate('상담')}>첫 상담 시작 <span aria-hidden="true">↗</span></button></div>}</main></WorkspaceShell>;
}

function RuntimeBanner({ session, health, healthError, micActive, micError, onRetry, onFallbackToText, onStartMic, onStopMic, onAssistRequest }: { session: SessionState; health: ApiHealth | null; healthError?: string; micActive: boolean; micError?: string; onRetry: () => void; onFallbackToText: () => void; onStartMic: () => void; onStopMic: () => void; onAssistRequest: (type: 'rephrase' | 'documents' | 'briefing') => void }) {
  const connectionCopy = connectionLabel(session.connectionState);
  const healthCopy = health?.status === 'ok' ? 'API 정상 · 버튼으로 녹음 시작/중지' : health?.status === 'degraded' ? 'API 부분 장애' : '서버 미확인';
  return <aside className={`runtime-banner runtime-banner-${session.connectionState}`} aria-live="polite"><div className="runtime-banner-status"><span className="runtime-status-dot" aria-hidden="true" /><strong>{connectionCopy}</strong><span>{healthCopy}</span>{session.partialText ? <span className="runtime-partial">듣는 중 · {session.partialText}</span> : null}</div><div className="runtime-banner-actions">{session.connectionState === 'error' || session.connectionState === 'fallback' ? <button className="runtime-button" type="button" onClick={onRetry}>다시 연결</button> : null}{session.lastError?.includes('stt') || session.lastError?.includes('음성') || micError?.includes('STT') ? <button className="runtime-button runtime-button-primary" type="button" onClick={onFallbackToText}>TEXT로 계속</button> : null}{session.mode === 'live' ? <button className={`runtime-button runtime-button-primary${micActive ? ' runtime-button-active' : ''}`} type="button" onClick={micActive ? onStopMic : onStartMic} aria-pressed={micActive}>{micActive ? '녹음 중지' : '녹음 시작'}</button> : null}<details className="runtime-assist"><summary>수동 도움</summary><div><button type="button" onClick={() => onAssistRequest('rephrase')}>쉬운 말</button><button type="button" onClick={() => onAssistRequest('documents')}>서류 안내</button><button type="button" onClick={() => onAssistRequest('briefing')}>기준 보기</button></div></details></div>{healthError && !health ? <p className="runtime-error">{healthError} · 서버가 없으면 로컬 데모로 계속합니다.</p> : null}{micError ? <p className="runtime-error">{micError}</p> : null}{session.lastError && !micError ? <p className="runtime-error">{session.lastError}</p> : null}</aside>;
}

export default function Home() {
  const [screen, setScreen] = useState<AppScreen>('landing'); const [product, setProduct] = useState<ProductKey>('deposit'); const [mode, setMode] = useState<Mode>('live'); const [customerLabel, setCustomerLabel] = useState('가상 고객 A'); const [customerType, setCustomerType] = useState<CustomerType>('general'); const [session, setSession] = useState<SessionState | null>(null); const [history, setHistory] = useState<SessionState[]>([]); const [activeNav, setActiveNav] = useState<NavItem>('상담'); const [tutorialStep, setTutorialStep] = useState(0); const [tutorialOpen, setTutorialOpen] = useState(false); const [evidenceCode, setEvidenceCode] = useState<string | null>(null);
  const [health, setHealth] = useState<ApiHealth | null>(null); const [healthError, setHealthError] = useState(''); const [micActive, setMicActive] = useState(false); const [micError, setMicError] = useState('');
  const socketRef = useRef<WebSocket | null>(null); const audioRef = useRef<Pcm16Capture | null>(null);
  useEffect(() => {
    const saved = window.localStorage.getItem('malteum.session-history');
    if (!saved) return;
    try {
      const parsed = JSON.parse(saved) as SessionState[];
      if (Array.isArray(parsed)) setHistory(parsed.map((record) => ({ ...record, checklist: record.checklist.filter((item) => item.required !== false), customerType: record.customerType ?? 'general', connectionState: record.connectionState ?? 'fallback', serverSeq: record.serverSeq ?? 0, evidenceRefsByCode: record.evidenceRefsByCode ?? {}, verdictVersions: record.verdictVersions ?? {}, remoteEvidence: record.remoteEvidence ?? {}, serverEventCount: record.serverEventCount ?? 0, localReplay: record.localReplay ?? true })));
    } catch {
      window.localStorage.removeItem('malteum.session-history');
    }
  }, []);
  useEffect(() => {
    window.localStorage.setItem('malteum.session-history', JSON.stringify(history));
  }, [history]);
  useEffect(() => { let cancelled = false; malteumApi.health().then((value) => { if (!cancelled) { setHealth(value); setHealthError(''); } }).catch((error: unknown) => { if (!cancelled) { setHealth(null); setHealthError(error instanceof ApiError ? error.message : '서버 상태를 확인할 수 없습니다.'); } }); return () => { cancelled = true; }; }, []);
  useEffect(() => () => { socketRef.current?.close(); audioRef.current?.stop(); }, []);
  function sendSocket(message: Record<string, unknown> | ArrayBuffer) { const socket = socketRef.current; if (!socket || socket.readyState !== WebSocket.OPEN) return false; socket.send(message instanceof ArrayBuffer ? message : JSON.stringify(message)); return true; }
  function applyServerMessage(current: SessionState, message: ServerMessage): SessionState {
    if (typeof message.seq === 'number' && current.serverSeq > 0 && message.seq <= current.serverSeq) return current;
    const streamedMessage = ['partial', 'utterance', 'verdict', 'alert', 'assist', 'progress'].includes(message.t);
    const next: SessionState = { ...current, serverSeq: Math.max(current.serverSeq, message.seq ?? current.serverSeq), connectionState: 'connected', lastError: undefined, eventLog: [...current.eventLog, `ws:${message.t}`], checklist: current.checklist.map((item) => ({ ...item })), transcript: [...current.transcript], evidenceRefsByCode: { ...current.evidenceRefsByCode }, verdictVersions: { ...current.verdictVersions }, remoteEvidence: { ...current.remoteEvidence }, serverEventCount: current.serverEventCount + (streamedMessage ? 1 : 0), localReplay: streamedMessage ? false : current.localReplay };
    if (message.t === 'ready') {
      const items = Array.isArray(message.items) ? message.items as Array<Record<string, unknown>> : [];
      next.serverPackVersion = typeof message.pack_version === 'string' ? message.pack_version : undefined;
      const expectedPack = productConfigs[current.product].packVersion;
      const requiredItems = items.filter((remote) => remote.required !== false);
      if (requiredItems.length && (!next.serverPackVersion || next.serverPackVersion === expectedPack)) next.checklist = requiredItems.map((remote, index) => { const code = String(remote.item_code ?? `SERVER-ITEM-${index + 1}`); const existing = next.checklist.find((item) => item.code === code); const state = checklistStatusFromServer(remote.state) ?? existing?.status ?? 'unmet'; const plainLanguage = Array.isArray(remote.plain_language) ? String(remote.plain_language[0] ?? existing?.plainLanguage ?? remote.name ?? code) : typeof remote.plain_language === 'string' ? remote.plain_language : existing?.plainLanguage ?? String(remote.name ?? code); return { code, label: typeof remote.name === 'string' ? remote.name : existing?.label ?? code, status: state, source: existing?.source ?? `서버 ready · ${String(remote.axis ?? 'omission')}`, plainLanguage, evidenceCode: existing?.evidenceCode ?? code, required: true }; });
    }
    if (message.t === 'partial') next.partialText = typeof message.text === 'string' ? message.text : '';
    if (message.t === 'utterance') { const at = typeof message.t_ms === 'number' ? Math.round(message.t_ms / 1000) : next.currentSeconds; next.currentSeconds = at; next.partialText = ''; next.transcript.push({ id: String(message.event_id ?? `server-${next.serverSeq}`), speaker: message.speaker === 'customer' ? 'customer' : message.speaker === 'system' ? 'system' : 'teller', text: String(message.text ?? ''), time: at }); }
    if (message.t === 'verdict') { const itemCode = typeof message.item_code === 'string' ? message.item_code : ''; const axis = typeof message.axis === 'string' ? message.axis : 'omission'; const version = typeof message.ver === 'number' ? message.ver : 0; const versionKey = `${itemCode}:${axis}`; const previousVersion = next.verdictVersions[versionKey] ?? -1; const state = checklistStatusFromServer(message.state); const ref = typeof message.evidence_ref === 'string' ? message.evidence_ref : ''; if (itemCode && version >= previousVersion) { next.verdictVersions[versionKey] = version; if (state) next.checklist = next.checklist.map((item) => item.code === itemCode ? { ...item, status: state } : item); if (ref) next.evidenceRefsByCode[itemCode] = ref; } }
    if (message.t === 'alert') { const itemCode = typeof message.item_code === 'string' ? message.item_code : ''; const ref = typeof message.evidence_ref === 'string' ? message.evidence_ref : ''; const kind = interventionKindForAlert(message.alert_type); const fallback = productConfigs[current.product].events.find((event) => event.alert?.type === message.alert_type)?.alert?.intervention; const comparison = typeof message.comparison === 'object' && message.comparison ? message.comparison as Record<string, unknown> : {}; const severity: Severity = message.severity === 'critical' || message.severity === 'info' ? message.severity : 'warning'; const eventId = String(message.event_id ?? `server-alert-${next.serverSeq}`); next.alertCount += 1; if (message.alert_type === 'forbidden_phrase') next.violationCount += 1; if (itemCode && ref) next.evidenceRefsByCode[itemCode] = ref; next.activeIntervention = { ...(fallback ?? {}), kind, label: fallback?.label ?? interventionLabelForKind(kind), title: fallback?.title ?? '설명서 기준을 확인해 주세요', body: String(message.message ?? fallback?.body ?? ''), spoken: typeof comparison.said === 'string' ? comparison.said : fallback?.spoken, reference: typeof comparison.reference === 'string' ? comparison.reference : fallback?.reference, caption: typeof comparison.condition === 'string' ? comparison.condition : fallback?.caption, source: ref ? `evidence_ref · ${ref}` : fallback?.source, evidenceCode: ref || fallback?.evidenceCode, severity, id: eventId, time: typeof message.t_ms === 'number' ? Math.round(message.t_ms / 1000) : next.currentSeconds, sourceEventId: eventId }; }
    if (message.t === 'assist') { const type = message.assist_type === 'rephrase' || message.assist_type === 'documents' || message.assist_type === 'briefing' || message.assist_type === 'answer' ? message.assist_type : 'nudge'; const ref = typeof message.evidence_ref === 'string' ? message.evidence_ref : ''; const itemCode = typeof message.item_code === 'string' ? message.item_code : ''; const text = String(message.text ?? ''); if (itemCode && ref) next.evidenceRefsByCode[itemCode] = ref; next.activeIntervention = { kind: type, label: interventionLabelForKind(type), title: type === 'answer' ? '근거 있는 답변을 준비했어요' : '필요한 안내를 준비했어요', body: text, quote: text, source: ref ? `evidence_ref · ${ref}` : '서버 assist', evidenceCode: ref || undefined, severity: 'info', id: String(message.event_id ?? `server-assist-${next.serverSeq}`), time: next.currentSeconds, sourceEventId: String(message.event_id ?? `server-assist-${next.serverSeq}`) }; if (type === 'answer') next.queryResult = { question: next.queryResult?.question ?? '', answer: text, evidenceCode: ref || undefined }; }
    if (message.t === 'progress') { next.remoteProgress = { met: Number(message.met ?? 0), partial: Number(message.partial ?? 0), itemsTotal: Number(message.items_total ?? next.checklist.length), remaining: Array.isArray(message.remaining) ? message.remaining.map(String) : [], termDensity: typeof message.term_density === 'string' ? message.term_density : undefined }; }
    if (message.t === 'ended') { next.ended = true; next.currentSeconds = Math.max(next.currentSeconds, productConfigs[next.product].totalSeconds); next.reportUrl = typeof message.report_url === 'string' ? apiUrl(message.report_url) : undefined; }
    if (message.t === 'error') { next.connectionState = 'error'; const code = typeof message.code === 'string' ? `${message.code}: ` : ''; next.lastError = `${code}${String(message.message ?? '서버 오류가 발생했습니다.')}`; }
    return next;
  }
  function connectServer(active: SessionState) {
    const url = wsUrl(active.wsUrl);
    if (!url) return;
    socketRef.current?.close();
    setSession((current) => current && (active.sessionId.startsWith('LOCAL-') || current.sessionId === active.sessionId) ? { ...current, connectionState: 'connecting', wsUrl: url, lastError: undefined } : current);
    const socket = new WebSocket(url);
    socketRef.current = socket;
    const isCurrentSocket = () => socketRef.current === socket;
    const timeout = window.setTimeout(() => {
      if (!isCurrentSocket()) return;
      if (socket.readyState === WebSocket.CONNECTING || socket.readyState === WebSocket.OPEN) {
        socket.close();
        setSession((current) => current && !current.ended ? { ...current, connectionState: 'fallback', lastError: '서버 응답이 없어 로컬 데모로 전환했습니다.' } : current);
      }
    }, 4500);
    socket.onopen = () => {
      const resumable = !active.sessionId.startsWith('LOCAL-') && active.serverSeq > 0;
      const message = resumable ? { t: 'resume', session_id: active.sessionId, from_seq: active.serverSeq } : { t: 'hello', mode: active.mode, product_code: productConfigs[active.product].productCode, customer_profile: { type: active.customerType, tags: [] }, ...(active.sessionId.startsWith('LOCAL-') ? {} : { session_id: active.sessionId }) };
      socket.send(JSON.stringify(message));
    };
    socket.onmessage = (event) => {
      const consume = (raw: string) => {
        try {
          const message = JSON.parse(raw) as ServerMessage;
          if (message.t === 'ready') window.clearTimeout(timeout);
          if (message.t === 'ping') { if (isCurrentSocket()) socket.send(JSON.stringify({ t: 'pong' })); return; }
          setSession((current) => {
            if (!current || !isCurrentSocket() || (!active.sessionId.startsWith('LOCAL-') && current.sessionId !== active.sessionId)) return current;
            const next = applyServerMessage(current, message);
            if (message.t === 'ready' && typeof message.session_id === 'string') next.sessionId = message.session_id;
            if (message.t === 'ended') {
              setHistory((records) => [next, ...records.filter((record) => record.sessionId !== next.sessionId)]);
              setActiveNav('리포트');
              setScreen('report');
              void malteumApi.report(next.sessionId).then((report) => setSession((latest) => latest ? { ...latest, report, reportUrl: latest.reportUrl ?? malteumApi.reportPdfUrl(latest.sessionId) } : latest)).catch(() => undefined);
            }
            return next;
          });
        } catch {
          setSession((current) => current ? { ...current, connectionState: 'error', lastError: '서버 메시지를 읽지 못했습니다.' } : current);
        }
      };
      if (typeof event.data === 'string') consume(event.data);
      else if (event.data instanceof Blob) void event.data.text().then(consume);
    };
    socket.onerror = () => {
      if (!isCurrentSocket()) return;
      setSession((current) => current && !current.ended ? { ...current, connectionState: current.serverSeq ? 'error' : 'fallback', lastError: '서버 연결에 실패해 로컬 데모로 전환했습니다.' } : current);
    };
    socket.onclose = () => {
      window.clearTimeout(timeout);
      if (!isCurrentSocket()) return;
      setSession((current) => current && !current.ended && (current.connectionState === 'connecting' || current.connectionState === 'connected') ? { ...current, connectionState: 'fallback', lastError: '서버 연결이 닫혀 로컬 데모로 전환했습니다.' } : current);
    };
  }
  const prepareSession = () => { if (!session || session.ended || session.product !== product || session.mode !== mode) setSession(createSession(product, mode, customerLabel, undefined, customerType)); };
  function navigate(value: NavItem) { setTutorialOpen(false); setActiveNav(value); window.scrollTo({ top: 0, behavior: 'auto' }); if (value === '상담') setScreen(session && !session.ended ? 'dashboard' : 'landing'); if (value === '리포트') setScreen('report'); if (value === '규정 팩') setScreen('packs'); if (value === '문서') setScreen('documents'); if (value === '이력') setScreen('history'); }
  function moveTutorial(nextStep: number) { const next = tutorialSteps[nextStep]; if (!next) { setTutorialOpen(false); return; } if (next.screen === 'briefing' || next.screen === 'dashboard') prepareSession(); if (next.screen !== screen) { setScreen(next.screen); setActiveNav('상담'); window.scrollTo({ top: 0, behavior: 'auto' }); } setTutorialStep(nextStep); }
  function handleTutorialNext() { if (tutorialStep === tutorialSteps.length - 1) setTutorialOpen(false); else moveTutorial(tutorialStep + 1); }
  function handleTutorialPrevious() { if (tutorialStep > 0) moveTutorial(tutorialStep - 1); }
  function startSession() { setMicError(''); setSession(createSession(product, mode, customerLabel, undefined, customerType)); setActiveNav('상담'); setScreen('briefing'); setTutorialOpen(false); window.scrollTo({ top: 0, behavior: 'auto' }); }
  async function beginLiveSession() {
    let active = session ?? createSession(product, mode, customerLabel, undefined, customerType);
    setMicError('');
    setSession(active);
    setActiveNav('상담');
    setScreen('dashboard');
    setTutorialStep(0);
    setTutorialOpen(true);
    window.scrollTo({ top: 0, behavior: 'auto' });
    try {
      const created = await malteumApi.createSession({ mode: active.mode, product_code: productConfigs[active.product].productCode, pack_version: productConfigs[active.product].packVersion, customer_profile: { type: active.customerType, tags: [] } });
      active = { ...active, sessionId: created.session_id, wsUrl: created.ws_url, connectionState: 'checking', serverSeq: 0, serverEventCount: 0, localReplay: false };
      setSession(active);
      connectServer(active);
    } catch {
      connectServer(active);
    }
  }
  function newSession() { socketRef.current?.close(); audioRef.current?.stop(); setMicActive(false); setMicError(''); setSession(null); setScreen('landing'); setActiveNav('상담'); setCustomerLabel(productConfigs[product].customer); setCustomerType('general'); setTutorialStep(0); setTutorialOpen(false); }
  function retryConnection() { if (session) connectServer(session); }
  function fallbackToText() { audioRef.current?.stop(); audioRef.current = null; setMicActive(false); setMicError(''); setSession((current) => current ? { ...current, mode: 'text', connectionState: current.connectionState === 'connected' ? 'connected' : 'fallback', lastError: undefined, eventLog: [...current.eventLog, 'recording:fallback:text'] } : current); setMode('text'); }
  async function startMic() { try { const capture = new Pcm16Capture(); audioRef.current = capture; await capture.start((frame) => { if (health?.checks?.stt === 'ok' && !sendSocket(frame)) setSession((current) => current ? { ...current, currentSeconds: Math.min(productConfigs[current.product].totalSeconds, current.currentSeconds + 0.1) } : current); else if (health?.checks?.stt !== 'ok') setSession((current) => current ? { ...current, currentSeconds: Math.min(productConfigs[current.product].totalSeconds, current.currentSeconds + 0.1) } : current); }); setMicActive(true); setMicError(health?.checks?.stt === 'ok' ? '' : '녹음 중입니다. 현재 백엔드 STT가 준비되지 않아 전사·판정은 기록되지 않습니다.'); setSession((current) => current ? { ...current, lastError: undefined, eventLog: [...current.eventLog, 'recording:start', 'recording:active'] } : current); } catch (error: unknown) { audioRef.current?.stop(); audioRef.current = null; setMicActive(false); const message = microphoneErrorMessage(error); setMicError(message); setSession((current) => current ? { ...current, lastError: message } : current); } }
  function stopMic() { audioRef.current?.stop(); audioRef.current = null; setMicActive(false); setMicError(''); setSession((current) => current ? { ...current, eventLog: [...current.eventLog, 'recording:stop'] } : current); }
  function requestAssist(type: 'rephrase' | 'documents' | 'briefing') { const currentItem = session?.checklist[1] ?? session?.checklist[0]; if (session?.connectionState === 'connected') sendSocket({ t: 'assist_request', assist_type: type, ...(currentItem ? { item_code: currentItem.code } : {}) }); setSession((current) => { if (!current) return current; const config = productConfigs[current.product]; const seed: InterventionSeed = type === 'rephrase' ? { kind: 'rephrase', label: '재진술', title: '쉬운 말로 다시 안내해 보세요', body: '승인된 쉬운 말로 고객에게 다시 설명할 수 있습니다.', quote: currentItem?.plainLanguage?.[0], source: currentItem?.source ?? '승인된 쉬운 말 사전', evidenceCode: currentItem?.evidenceCode, severity: 'info' } : type === 'documents' ? { kind: 'documents', label: '서류 안내', title: '필요 서류를 안내해 보세요', body: '상담 마무리 전에 준비할 서류를 확인합니다.', quote: config.briefing.documents.join(' · '), source: '상담 브리핑', severity: 'info' } : { kind: 'briefing', label: '브리핑', title: '이번 상담의 기준을 다시 확인해 보세요', body: config.briefing.mustSay.join(' · '), source: `${config.packVersion} · 최근 기준`, severity: 'info' }; const event: DemoEvent = { id: `LOCAL-ASSIST-${current.eventLog.length}`, at: current.currentSeconds }; return { ...current, activeIntervention: interventionFromSeed(seed, event), eventLog: [...current.eventLog, `assist_request:${type}`] }; }); }
  function advanceSession() { setSession((current) => { if (!current || current.ended) return current; const event = productConfigs[current.product].events[current.eventCursor]; return event ? { ...applyDemoEvent(current, event), localReplay: true } : current; }); }
  function askQuestion(question: string) { if (!question) return; const fallback = localQueryResult(productConfigs[session?.product ?? product], question); if (session?.connectionState === 'connected' && sendSocket({ t: 'ask', question })) { setSession((current) => current ? { ...current, queryResult: fallback, eventLog: [...current.eventLog, 'ask:server-pending'] } : current); return; } setSession((current) => current ? { ...current, queryResult: localQueryResult(productConfigs[current.product], question), eventLog: [...current.eventLog, `ask:${question}`] } : current); }
  function appendTextUtterance(text: string, speaker: Speaker) {
    setMicError('');
    if (session?.connectionState === 'connected' && sendSocket({ t: 'text_utterance', text, speaker: speaker === 'customer' ? 'customer' : 'teller' })) { setSession((current) => current ? { ...current, eventLog: [...current.eventLog, 'text_utterance:server'] } : current); return; }
    setSession((current) => {
      if (!current) return current;
      const config = productConfigs[current.product];
      const at = Math.min(config.totalSeconds, current.currentSeconds + 5);
      const id = `TEXT-${current.eventLog.length}`;
      const matched = config.events.find((event) => {
        if (!event.text || event.speaker !== speaker) return false;
        const checklistLabel = event.status ? config.checklist.find((item) => item.code === event.status?.code)?.label.split(' ')[0] : '';
        const markers = [checklistLabel, event.alert?.intervention.spoken, event.alert?.type === 'risk_signal' ? '계좌' : '', event.assist?.kind === 'answer' ? '만기' : '', event.assist?.kind === 'rephrase' ? (current.product === 'mortgage' ? '근저당' : '중간') : '', event.assist?.kind === 'documents' ? '서류' : '', event.assist?.kind === 'nudge' ? '대안' : ''].filter(Boolean);
        return markers.some((marker) => text.includes(marker as string));
      });
      const next: SessionState = { ...current, currentSeconds: at, transcript: [...current.transcript, { id, speaker, text, time: at, highlighted: Boolean(matched?.alert) }], eventLog: [...current.eventLog, `text_utterance:${speaker}`], checklist: current.checklist.map((item) => ({ ...item })) };
      if (matched?.status) next.checklist = next.checklist.map((item) => item.code === matched.status?.code ? { ...item, status: matched.status.value } : item);
      if (matched?.alert) { next.alertCount += 1; if (matched.alert.type === 'forbidden_phrase') next.violationCount += 1; next.activeIntervention = interventionFromSeed(matched.alert.intervention, { ...matched, id, at, text }); }
      if (matched?.assist) next.activeIntervention = interventionFromSeed(matched.assist, { ...matched, id, at, text });
      return next;
    });
  }
  function markMet(code: string) { if (session?.connectionState === 'connected') sendSocket({ t: 'mark_met', item_code: code }); setSession((current) => current ? { ...current, checklist: current.checklist.map((item) => item.code === code ? { ...item, status: 'met' } : item), eventLog: [...current.eventLog, `mark_met:${code}`] } : current); }
  function markWaive(code: string, reason: string) { if (session?.connectionState === 'connected') sendSocket({ t: 'mark_waived', item_code: code, reason }); setSession((current) => current ? { ...current, checklist: current.checklist.map((item) => item.code === code ? { ...item, status: 'waived' } : item), eventLog: [...current.eventLog, `mark_waived:${code}:${reason}`] } : current); }
  function resolveIntervention() { setSession((current) => current ? { ...current, activeIntervention: null, assistAdopted: current.activeIntervention && ['rephrase', 'answer', 'nudge', 'documents', 'briefing'].includes(current.activeIntervention.kind) ? current.assistAdopted + 1 : current.assistAdopted, eventLog: [...current.eventLog, 'intervention_resolved'] } : current); }
  function acknowledge() { if (session?.connectionState === 'connected' && session.activeIntervention) sendSocket({ t: 'acknowledge', alert_ref: session.activeIntervention.sourceEventId }); setSession((current) => current ? { ...current, activeIntervention: null, acknowledgedCount: current.acknowledgedCount + 1, eventLog: [...current.eventLog, 'acknowledge'] } : current); }
  async function openEvidence(codeOrRef: string) {
    const current = session;
    if (!current) return;
    const ref = current.evidenceRefsByCode[codeOrRef] ?? codeOrRef;
    setEvidenceCode(ref);
    if (current.remoteEvidence[ref] || current.connectionState !== 'connected' || !current.evidenceRefsByCode[codeOrRef]) return;
    try {
      const remote = await malteumApi.evidence(ref);
      const item = evidenceFromApi(remote, ref);
      setSession((latest) => latest ? { ...latest, remoteEvidence: { ...latest.remoteEvidence, [ref]: item }, lastError: undefined } : latest);
    } catch (error: unknown) {
      setSession((latest) => latest ? { ...latest, lastError: error instanceof ApiError ? `근거 원문을 불러오지 못했습니다: ${error.message}` : '근거 원문을 불러오지 못했습니다.' } : latest);
    }
  }
  function endSession() { if (!session) return; if (session.connectionState === 'connected') sendSocket({ t: 'end' }); stopMic(); const ended = { ...session, checklist: session.checklist.filter((item) => item.required !== false), ended: true, currentSeconds: Math.max(session.currentSeconds, productConfigs[session.product].totalSeconds), reportUrl: session.reportUrl ?? (session.connectionState === 'connected' ? malteumApi.reportPdfUrl(session.sessionId) : undefined) }; setSession(ended); setHistory((current) => [ended, ...current.filter((item) => item.sessionId !== ended.sessionId)]); setActiveNav('리포트'); setScreen('report'); setTutorialOpen(false); window.scrollTo({ top: 0, behavior: 'auto' }); if (session.connectionState === 'connected') void malteumApi.report(session.sessionId).then((report) => setSession((latest) => latest ? { ...latest, report, reportUrl: latest.reportUrl ?? malteumApi.reportPdfUrl(latest.sessionId) } : latest)).catch(() => undefined); }
  function playTrace(record: SessionState) { const trace = createSession(record.product, 'trace', record.customerLabel, record.sessionId); setSession(trace); setMode('trace'); setProduct(record.product); setActiveNav('상담'); setScreen('dashboard'); setTutorialOpen(false); }
  async function openRemoteReport(record: ApiSessionSummary) {
    const remoteProduct: ProductKey = record.pack_version.startsWith('MTG') || record.product_name?.includes('대출') ? 'mortgage' : 'deposit';
    let loaded = createSession(remoteProduct, record.mode, productConfigs[remoteProduct].customer, record.session_id);
    loaded = { ...loaded, ended: record.status !== 'running', connectionState: 'connected', currentSeconds: record.status === 'running' ? 0 : productConfigs[remoteProduct].totalSeconds, reportUrl: malteumApi.reportPdfUrl(record.session_id) };
    try {
      const [eventResult, report] = await Promise.all([malteumApi.events(record.session_id), malteumApi.report(record.session_id)]);
      loaded = eventResult.events.reduce<SessionState>((state, event) => { const message = serverMessageFromStoredEvent(event); return message ? applyServerMessage(state, message) : state; }, loaded);
      loaded = { ...loaded, ended: true, report, reportUrl: malteumApi.reportPdfUrl(record.session_id) };
    } catch (error: unknown) {
      loaded = { ...loaded, lastError: error instanceof ApiError ? `서버 세션 일부를 불러오지 못했습니다: ${error.message}` : '서버 세션 일부를 불러오지 못했습니다.' };
    }
    setSession(loaded); setProduct(remoteProduct); setMode(record.mode); setActiveNav('리포트'); setScreen('report'); setTutorialOpen(false);
  }
  const evidenceItem = useMemo(() => { if (!evidenceCode || !session) return null; const local = productConfigs[session.product].evidence[evidenceCode] ?? Object.values(productConfigs[session.product].evidence).find((item) => item.ref === evidenceCode); return session.remoteEvidence[evidenceCode] ?? Object.values(session.remoteEvidence).find((item) => item.ref === evidenceCode) ?? local ?? null; }, [evidenceCode, session]);
  let page: React.ReactNode;
  if (screen === 'landing') page = <MarketingLanding product={product} mode={mode} customerLabel={customerLabel} customerType={customerType} tutorialTarget="" configs={productConfigs} onProductChange={(value) => { setProduct(value); setCustomerLabel(productConfigs[value].customer); }} onModeChange={setMode} onCustomerChange={setCustomerLabel} onCustomerTypeChange={setCustomerType} onStart={startSession} onNavigate={navigate} />;
  else if (screen === 'briefing') page = <ConnectedBriefingScreen product={product} mode={mode} customerLabel={customerLabel} customerType={customerType} config={productConfigs[product]} micActive={micActive} micError={micError} onBack={() => { setScreen('landing'); setActiveNav('상담'); window.scrollTo({ top: 0, behavior: 'auto' }); }} onStart={beginLiveSession} onNavigate={navigate} />;
  else if (screen === 'dashboard' && session) page = <Dashboard session={session} health={health} healthError={healthError} onAdvance={advanceSession} onEnd={endSession} onNewSession={newSession} onNavigate={navigate} onOpenEvidence={openEvidence} onResolveIntervention={resolveIntervention} onAcknowledge={acknowledge} onAsk={askQuestion} onTextUtterance={appendTextUtterance} onMarkMet={markMet} onMarkWaive={markWaive} onRetryConnection={retryConnection} onFallbackToText={fallbackToText} onStartMic={startMic} onStopMic={stopMic} micActive={micActive} micError={micError} onAssistRequest={requestAssist} />;
  else if (screen === 'report') page = <ReportScreen session={session} onNewSession={newSession} onOpenEvidence={openEvidence} onNavigate={navigate} onPrint={() => { if (session?.reportUrl) window.open(session.reportUrl, '_blank', 'noopener,noreferrer'); else window.print(); }} />;
  else if (screen === 'packs') page = <PackScreen product={product} onNavigate={navigate} onNewSession={newSession} />;
  else if (screen === 'documents') page = <DocumentsScreen product={product} onNavigate={navigate} onNewSession={newSession} />;
  else page = <HistoryScreen records={history} onOpenReport={(record) => { setSession(record); setProduct(record.product); setMode(record.mode); setActiveNav('리포트'); setScreen('report'); }} onOpenRemoteReport={openRemoteReport} onTrace={playTrace} onNavigate={navigate} onNewSession={newSession} />;
  return <>{page}{tutorialOpen && screen === 'dashboard' ? <TutorialOverlay stepIndex={tutorialStep} onNext={handleTutorialNext} onPrevious={handleTutorialPrevious} onSkip={() => setTutorialOpen(false)} /> : null}{evidenceItem && session ? <EvidenceModal evidenceItem={evidenceItem} packVersion={session.report?.pack_version ?? productConfigs[session.product].packVersion} onClose={() => setEvidenceCode(null)} /> : null}</>;
}
