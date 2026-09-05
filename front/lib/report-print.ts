import { ApiReport } from './api';
import { fieldNames, statusNames, textValue } from './workspace-model';

const escapeHtml = (value: unknown) => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!));
const sectionNames = { omission: '설명 이행', commission: '금지·숫자', comprehension: '이해 지원', risk_signals: '위험 신호', timeline: '타임라인' };

// Print the complete server report, independently of the selected tab/pagination.
// No client-generated judgements or summaries are added to the export.
export function reportHtml(report: ApiReport) {
  const sections = report.sections ?? {};
  const record = (row: Record<string, unknown>) => `<dl>${Object.entries(row).filter(([, value]) => value != null).map(([key, value]) => `<dt>${escapeHtml(fieldNames[key] ?? key)}</dt><dd>${escapeHtml(typeof value === 'string' ? statusNames[value] ?? value : textValue(value))}</dd>`).join('')}</dl>`;
  return `<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>말틈 상담 리포트</title><style>
    @page{size:A4;margin:16mm}*{box-sizing:border-box}body{font:13px/1.65 'Malgun Gothic',sans-serif;color:#173942;margin:28px}h1{font-size:26px}h2{font-size:18px;margin-top:28px;border-bottom:1px solid #b8cbcf;padding-bottom:8px}p,dd{white-space:pre-wrap;overflow-wrap:anywhere}dl{display:grid;grid-template-columns:110px minmax(0,1fr);gap:4px 12px;border-bottom:1px solid #e1e8e9;padding:12px 0;margin:0}dt{color:#59747d}dd{margin:0}button{padding:10px 18px;background:#173942;color:white;border:0;border-radius:6px;cursor:pointer}@media print{body{margin:0}button{display:none}h2{break-after:avoid}dl{break-inside:avoid}}
    </style></head><body><button onclick="window.print()">인쇄 / PDF 저장</button><h1>말틈 상담 리포트</h1><p>${escapeHtml(report.session_id)} · ${escapeHtml(report.pack_version)}\n생성 시각: ${escapeHtml(report.generated_at)}</p>
    <h2>상담 요약</h2>${record(sections.summary ?? {})}
    ${Object.entries(sectionNames).map(([key, title]) => `<section><h2>${title}</h2>${(sections[key as keyof typeof sectionNames] ?? []).map(row => record(row as Record<string, unknown>)).join('') || '<p>기록 없음</p>'}</section>`).join('')}
    <h2>출처</h2>${(report.sources ?? []).map(source => record(source)).join('') || '<p>서버에서 제공된 출처 없음</p>'}${report.disclaimer ? `<p>${escapeHtml(report.disclaimer)}</p>` : ''}</body></html>`;
}

export function openReportPrint(report: ApiReport) {
  const preview = window.open('', '_blank');
  if (!preview) return false;
  preview.opener = null;
  preview.document.open(); preview.document.write(reportHtml(report)); preview.document.close();
  return true;
}
