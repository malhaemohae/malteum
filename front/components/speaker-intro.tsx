import { Modal } from './workspace';
import { WorkspaceIcon } from './workspace-icons';

// Flow preview only. No capture, enrollment, transcript, or server state lives here.
export function SpeakerIntroModal({ onClose, onContinue }: { onClose: () => void; onContinue: () => void }) {
  return <Modal title="녹음 전 안내" className="wb-speaker-intro" trapFocus onClose={onClose} actions={<>
    <button type="button" onClick={onClose}>취소</button>
    <button type="button" className="wb-primary" onClick={onContinue}>이어서 녹음 시작</button>
  </>}>
    <span className="wb-speaker-preview-label">흐름 미리보기</span>
    <div className="wb-speaker-mic" aria-hidden="true"><WorkspaceIcon name="mic" size={36} /></div>
    <div className="wb-speaker-caption">
      <h3>상담원부터 말씀해 주세요</h3>
      <p>녹음이 시작되면 아래 문장을 먼저 읽어주세요.</p>
    </div>
    <blockquote className="wb-speaker-script" aria-label="상담원 시작 문장 예시">
      <p>안녕하세요. 오늘 상담을 도와드릴 상담원입니다.</p>
      <p>지금부터 상담을 시작하겠습니다.</p>
    </blockquote>
    <p className="wb-speaker-preview-note">화자 등록이 연결되지 않은 미리보기입니다.<br />이 화면에서는 녹음하지 않습니다.</p>
  </Modal>;
}
