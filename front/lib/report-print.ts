import { ApiReport, malteumApi } from './api';
import { displayField, displayValue } from './workspace-model';

const escapeHtml = (value: unknown) => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!));
const sectionNames = { omission: '설명 이행', commission: '금지·숫자', comprehension: '이해 지원', risk_signals: '위험 신호', timeline: '타임라인' };

// Print the complete server report, independently of the selected tab/pagination.
// No client-generated judgements or summaries are added to the export.
export function reportHtml(report: ApiReport) {
  const sections = report.sections ?? {};
  const record = (row: Record<string, unknown>) => `<dl>${Object.entries(row).filter(([, value]) => value != null).map(([key, value]) => `<dt>${escapeHtml(displayField(key))}</dt><dd>${escapeHtml(displayValue(value, key))}</dd>`).join('')}</dl>`;
  return `<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>말틈 상담 리포트</title><style>
    @page{size:A4;margin:16mm}*{box-sizing:border-box}body{font:13px/1.65 'Malgun Gothic',sans-serif;color:#173942;margin:28px}h1{font-size:26px}h2{font-size:18px;margin-top:28px;border-bottom:1px solid #b8cbcf;padding-bottom:8px}p,dd{white-space:pre-wrap;overflow-wrap:anywhere}dl{display:grid;grid-template-columns:110px minmax(0,1fr);gap:4px 12px;border-bottom:1px solid #e1e8e9;padding:12px 0;margin:0}dt{color:#59747d}dd{margin:0}button{padding:10px 18px;background:#173942;color:white;border:0;border-radius:6px;cursor:pointer}.report-download{display:inline-block;margin-left:16px;color:#087e9f}@media print{body{margin:0}button,.report-download,.report-export-status{display:none}h2{break-after:avoid}dl{break-inside:avoid}}
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

// Reserve the window inside the click event so async PDF retrieval is not blocked.
export async function exportReport(report: ApiReport): Promise<string> {
  const preview = window.open('', '_blank');
  if (!preview) throw new Error('미리보기 창이 차단됐습니다. 이 사이트의 팝업을 허용하고 다시 시도해 주세요.');
  preview.opener = null;
  preview.document.write('<!doctype html><html lang="ko"><meta charset="utf-8"><title>리포트 준비</title><body><p role="status">서버 PDF를 준비하고 있습니다.</p></body></html>');
  preview.document.close();
  try {
    const response = await fetch(malteumApi.reportPdfUrl(report.session_id), { signal: AbortSignal.timeout(15000), cache: 'no-store' });
    if (!response.ok || !response.headers.get('content-type')?.includes('application/pdf')) throw new Error('PDF unavailable');
    const blob = await response.blob();
    if (!(await blob.slice(0, 5).text()).startsWith('%PDF-')) throw new Error('Invalid PDF');
    if (preview.closed) return '미리보기 창이 닫혔습니다. 다시 요청할 수 있습니다.';
    // The server PDF is preserved as an original download. Use the same readable
    // metadata as the screen for the user-facing print/PDF, without changing facts.
    const url = URL.createObjectURL(blob);
    const link = `<a class="report-download" href="${escapeHtml(url)}" download="${escapeHtml(report.session_id)}-server.pdf">서버 원본 PDF 다운로드</a>`;
    preview.document.open(); preview.document.write(reportHtml(report).replace('</button>', `</button>${link}`)); preview.document.close();
    const cleanup = window.setInterval(() => { if (preview.closed) { URL.revokeObjectURL(url); window.clearInterval(cleanup); } }, 2000);
    return '전체 리포트를 열었습니다. 인쇄에서 PDF로 저장하거나 서버 원본을 다운로드하세요.';
  } catch {
    if (preview.closed) return '미리보기 창이 닫혔습니다. 다시 요청할 수 있습니다.';
    const note = '서버 PDF를 가져오지 못해 전체 보고서의 인쇄 미리보기를 열었습니다. 인쇄에서 PDF로 저장할 수 있습니다.';
    preview.document.open(); preview.document.write(reportHtml(report).replace('<h1>', `<p class="report-export-status" role="status">${note}</p><h1>`)); preview.document.close();
    return note;
  }
}
