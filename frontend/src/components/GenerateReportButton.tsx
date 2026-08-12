import { useRef, useState, type RefObject } from 'react';
import { generateReport, type GenerateReportInput } from '../services/reportGenerator';
import './GenerateReportButton.css';

type ButtonState = 'idle' | 'loading' | 'success' | 'error';

interface GenerateReportButtonProps {
  data: GenerateReportInput | null;
  disabled?: boolean;
  /** Allows App.tsx to trigger the report via the R keyboard shortcut. */
  buttonRef?: RefObject<HTMLButtonElement | null>;
}

/**
 * Not a plain <button onClick={...}>. A report generator that takes a
 * beat to run deserves to say so — an instant-return button on a task
 * that visibly takes work reads as broken, not fast. The button shrinks
 * to an icon-only spinner while working (no layout shift, since the
 * panel around it never reflows), flashes a state color on completion,
 * and settles back to idle rather than staying in a terminal state.
 */
export default function GenerateReportButton({ data, disabled, buttonRef }: GenerateReportButtonProps) {
  const [state, setState] = useState<ButtonState>('idle');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  function clearTimers() {
    timersRef.current.forEach(clearTimeout);
    timersRef.current = [];
  }

  function handleClick() {
    if (!data || state === 'loading' || disabled) return;
    clearTimers();
    setState('loading');
    setErrorMsg(null);

    // A synchronous jsPDF build can finish in a few milliseconds for a
    // short report — too fast for the loading state to register as
    // intentional rather than a flicker. Holding a floor here (not a
    // fake total duration; real generation still happens inline) keeps
    // the state machine legible even on a fast machine.
    const floor = new Promise((resolve) => {
      const t = setTimeout(resolve, 550);
      timersRef.current.push(t);
    });

    Promise.all([
      floor,
      new Promise<void>((resolve, reject) => {
        try {
          generateReport(data);
          resolve();
        } catch (err) {
          reject(err);
        }
      }),
    ])
      .then(() => {
        setState('success');
        const t = setTimeout(() => setState('idle'), 800);
        timersRef.current.push(t);
      })
      .catch((err) => {
        setErrorMsg(err instanceof Error ? err.message : 'Report generation failed.');
        setState('error');
        const t = setTimeout(() => setState('idle'), 1600);
        timersRef.current.push(t);
      });
  }

  return (
    <div className="generate-report">
      <button
        ref={buttonRef}
        type="button"
        className={`generate-report__btn generate-report__btn--${state}`}
        onClick={handleClick}
        disabled={!data || disabled || state === 'loading'}
        aria-busy={state === 'loading'}
        title="Generate report (R)"
      >
        {state === 'loading' ? (
          <SpinnerIcon />
        ) : state === 'success' ? (
          <>
            <CheckIcon />
            <span>Report ready</span>
          </>
        ) : state === 'error' ? (
          <>
            <AlertIcon />
            <span>Failed</span>
          </>
        ) : (
          <>
            <DocIcon />
            <span>Generate report</span>
          </>
        )}
      </button>

      <div className={`generate-report__toast ${state === 'error' ? 'generate-report__toast--visible' : ''}`}>
        {errorMsg}
      </div>
    </div>
  );
}

function DocIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M7 3h7l5 5v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z" />
      <path d="M14 3v5h5" />
      <path d="M9 13h6M9 17h6" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4.5 12.5 9.5 17.5 19.5 6.5" />
    </svg>
  );
}

function AlertIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3 2 20h20L12 3Z" />
      <path d="M12 10v4.5M12 17v.01" />
    </svg>
  );
}

function SpinnerIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" className="generate-report__spinner">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2" opacity="0.2" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}
