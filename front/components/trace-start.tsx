'use client';

import { LiveSession } from '../lib/workspace-model';
import { Panel } from './workspace';

export function TraceStart({ session, onEnd, onRetry, onHistory }: { session: LiveSession; onEnd: () => void; onRetry: () => void; onHistory: () => void }) {
  const failed = session.status === 'disconnected' || Boolean(session.error);
  const loading = session.ending || !failed;
  const title = session.ending ? '재생 중지를 확인하고 있습니다' : failed ? '재생 연결을 확인해 주세요' : session.status === 'connecting' ? '저장된 상담에 연결하고 있습니다' : '첫 발화를 불러오고 있습니다';
  return <Panel className="wb-trace-start"><div className="wb-trace-start-content" data-trace-start data-state={session.ending ? 'ending' : failed ? 'error' : 'loading'}>
    {loading ? <span className="wb-trace-spinner" aria-hidden="true" /> : <span className="wb-trace-error-icon" aria-hidden="true">!</span>}
    <div role="status" aria-live="polite" aria-atomic="true"><h2>{title}</h2><p>{session.ending ? '서버에서 종료를 확인하면 이동합니다.' : failed ? session.error || '서버 연결이 끊겼습니다. 다시 연결해 주세요.' : '원본 기록의 시간 간격에 따라 재생합니다.\n첫 발화가 도착하면 상담 화면이 자동으로 열립니다.'}</p></div>
    <div className="wb-actions">{failed && !session.ending && <button className="wb-primary" onClick={onRetry}>다시 연결</button>}<button onClick={onEnd} disabled={session.status !== 'connected' || session.ending}>{session.ending ? '중지 확인 중…' : '재생 중지'}</button><button onClick={onHistory}>이력 보기</button></div>
  </div></Panel>;
}
