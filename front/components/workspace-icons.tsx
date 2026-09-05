// Same rounded, 1.7px line language as the existing landing icons.
export type WorkspaceIconName = 'conversation' | 'document' | 'history' | 'book' | 'mic' | 'check' | 'folder' | 'arrow' | 'stop';
export function WorkspaceIcon({ name, size = 22 }: { name: WorkspaceIconName; size?: number }) {
  const paths = {
    conversation: <><path d="M5 4h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2h-8l-5 3v-3H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z" /><path d="M7 9h10M7 13h6" /></>,
    document: <><path d="M7 3.8h7l3 3V20H7V3.8Z" /><path d="M14 3.8v3h3M9.5 11h5M9.5 14h5M9.5 17h3" /></>,
    history: <><path d="M4.8 8.2A8 8 0 1 1 4 13" /><path d="M4.8 4.8v3.5H8.3M12 8v4l2.8 1.7" /></>,
    book: <><path d="M5 4.5h10.8A2.2 2.2 0 0 1 18 6.7v12.8H7.2A2.2 2.2 0 0 1 5 17.3V4.5Z" /><path d="M5 17.2c0-1.2 1-2.2 2.2-2.2H18M9 8h5M9 11h4" /></>,
    mic: <><rect x="9" y="3" width="6" height="12" rx="3" /><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M8.5 21h7" /></>,
    check: <><rect x="4" y="3" width="16" height="18" rx="3" /><path d="m8 9 1.5 1.5L12 8M14 9h2M8 15h8" /></>,
    folder: <><path d="M3 7V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v11H3V7Z" /><path d="M3 10h18M8 14h8" /></>,
    arrow: <path d="m9 5 7 7-7 7" />,
    stop: <rect x="6" y="6" width="12" height="12" rx="2" />,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}
