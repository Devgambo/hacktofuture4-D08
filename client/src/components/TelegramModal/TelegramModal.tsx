import React from 'react';
import './TelegramModal.css';

interface TelegramModalProps {
  onSkip: () => void;
}

const TelegramModal: React.FC<TelegramModalProps> = ({ onSkip }) => {
  return (
    <div className="tg-modal-backdrop" aria-modal="true" role="dialog">
      <div className="tg-modal">
        <div className="flex justify-between items-start mb-10">
          <div className="flex flex-col gap-2">
            <h2 className="text-4xl font-black text-[var(--color-on-surface)] tracking-tighter decoration-none">LINK TELEGRAM</h2>
            <p className="text-xs font-bold tracking-[0.2em] text-[var(--color-primary)] uppercase">Deployment Notification Node</p>
          </div>
          <button
            onClick={onSkip}
            className="w-12 h-12 flex items-center justify-center rounded-full bg-[var(--color-surface-container-high)] text-[var(--color-on-surface-variant)] cursor-pointer transition-all hover:bg-[var(--color-error-container)] hover:text-[var(--color-error)] border-none"
            title="Skip integration"
          >
            <span className="material-symbols-outlined">close</span>
          </button>
        </div>

        <div className="flex flex-col gap-6 mb-10">
          <div className="tg-modal__step">
            <div className="w-14 h-14 shrink-0 rounded-2xl bg-[#0088cc] flex items-center justify-center text-white shadow-lg">
              <span className="material-symbols-outlined text-3xl">send</span>
            </div>
            <div className="flex flex-col gap-1">
              <p className="text-[0.65rem] font-black text-[var(--color-primary)] uppercase tracking-widest">STEP_01</p>
              <p className="text-lg font-bold text-[var(--color-on-surface)] leading-tight">Search for <span className="text-[#0088cc]">@easyops_devops_bot</span></p>
            </div>
          </div>

          <div className="tg-modal__step">
            <div className="w-14 h-14 shrink-0 rounded-2xl bg-[var(--color-tertiary)] flex items-center justify-center text-[var(--color-on-tertiary)] shadow-lg">
              <span className="material-symbols-outlined text-3xl">terminal</span>
            </div>
            <div className="flex flex-col gap-1">
              <p className="text-[0.65rem] font-black text-[var(--color-primary)] uppercase tracking-widest">STEP_02</p>
              <p className="text-lg font-bold text-[var(--color-on-surface)] leading-tight">Send <code className="bg-[var(--color-surface-container-highest)] px-2 py-0.5 rounded border border-[var(--color-outline-variant)] text-[var(--color-primary)] text-sm">/link &lt;username&gt;</code></p>
            </div>
          </div>
        </div>

        <div className="flex flex-col gap-4">
          <a
            href="https://t.me/easyops_devops_bot"
            target="_blank"
            rel="noreferrer"
            className="flex items-center justify-center gap-3 w-full py-4 bg-[#0088cc] text-white rounded-xl no-underline font-black text-lg tracking-tight shadow-xl transition-all hover:scale-[1.02] hover:shadow-[#0088cc]/30"
          >
            OPEN IN TELEGRAM
            <span className="material-symbols-outlined">open_in_new</span>
          </a>
          <button
            onClick={onSkip}
            className="w-full py-4 bg-transparent text-[var(--color-on-surface-variant)] border border-[var(--color-outline-variant)] rounded-xl font-bold text-sm tracking-widest uppercase cursor-pointer transition-colors hover:bg-[var(--color-surface-container-high)]"
          >
            SKIP_FOR_NOW
          </button>
        </div>
      </div>
    </div>
  );
};

export default TelegramModal;
