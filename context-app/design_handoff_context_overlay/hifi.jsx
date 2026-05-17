// Hi-fi pass — Hybrid A (Always-on Ask bar)
// macOS vibrancy · subtle grays · traffic lights + pencil only · 5 states.

const HFCSS = `
  .hf, .hf * {
    font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'SF Pro Display', system-ui, sans-serif;
    -webkit-font-smoothing: antialiased;
  }
  .hf-mono { font-family: 'SF Mono', ui-monospace, Menlo, Consolas, monospace; }

  /* a soft warm wallpaper so vibrancy is visible */
  .hf-wall {
    position: absolute; inset: 0;
    background:
      radial-gradient(60% 80% at 15% 20%, #f0c9a4 0%, transparent 60%),
      radial-gradient(50% 70% at 90% 30%, #d8a890 0%, transparent 60%),
      radial-gradient(80% 80% at 40% 90%, #a48aa8 0%, transparent 70%),
      linear-gradient(180deg, #c79b7d 0%, #8a6a78 100%);
  }
  .hf-wall::after{
    content: ''; position: absolute; inset: 0;
    background-image:
      radial-gradient(circle at 20% 30%, rgba(255,255,255,.18), transparent 25%),
      radial-gradient(circle at 80% 70%, rgba(0,0,0,.12), transparent 28%);
  }

  /* the overlay card — vibrancy */
  .hf-card {
    position: relative;
    background: rgba(248, 246, 244, 0.62);
    backdrop-filter: blur(24px) saturate(180%);
    -webkit-backdrop-filter: blur(24px) saturate(180%);
    border-radius: 14px;
    box-shadow:
      inset 0 0.5px 0 rgba(255,255,255,0.7),
      inset 0 0 0 0.5px rgba(0,0,0,0.10),
      0 1px 2px rgba(0,0,0,0.12),
      0 12px 40px rgba(0,0,0,0.22),
      0 24px 80px rgba(0,0,0,0.18);
    color: #1a1a1c;
    overflow: hidden;
  }

  /* chrome bar */
  .hf-chrome {
    display: flex; align-items: center; justify-content: space-between;
    height: 36px; padding: 0 12px;
    -webkit-app-region: drag;
  }
  .hf-lights { display: flex; gap: 6px; align-items: center; }
  .hf-light { width: 12px; height: 12px; border-radius: 50%; box-shadow: inset 0 0 0 0.5px rgba(0,0,0,0.2); }
  .hf-light.close{ background: #fb6058; }
  .hf-light.min  { background: #fdbe40; }
  .hf-light.max  { background: #2dc940; }

  .hf-iconbtn {
    width: 24px; height: 24px; border-radius: 6px;
    border: none; background: transparent; cursor: pointer;
    color: rgba(0,0,0,0.55);
    display: inline-flex; align-items: center; justify-content: center;
    transition: background .12s;
  }
  .hf-iconbtn:hover { background: rgba(0,0,0,0.06); color: rgba(0,0,0,0.8); }

  /* meta row */
  .hf-meta {
    padding: 2px 16px 10px;
    display: flex; align-items: baseline; justify-content: space-between;
    color: rgba(0,0,0,0.5); font-size: 11px; letter-spacing: 0.04em;
    text-transform: uppercase;
  }
  .hf-progress {
    height: 2px; background: rgba(0,0,0,0.07);
    margin: 0 14px; border-radius: 1px; overflow: hidden;
  }
  .hf-progress > span { display: block; height: 100%; background: rgba(0,0,0,0.55); border-radius: 1px; }

  /* steps */
  .hf-steps { padding: 12px 10px 8px; }
  .hf-step {
    display: flex; align-items: center; gap: 12px;
    padding: 7px 10px; border-radius: 9px;
    font-size: 13px; line-height: 1.35;
  }
  .hf-step.done { color: rgba(0,0,0,0.42); }
  .hf-step.done .hf-step-text { text-decoration: line-through; text-decoration-color: rgba(0,0,0,0.25); }
  .hf-step.now  {
    background: rgba(0,0,0,0.05);
    box-shadow: inset 0 0 0 0.5px rgba(0,0,0,0.08);
    font-weight: 600; font-size: 14px; color: #0a0a0c;
  }
  .hf-step.next { color: rgba(0,0,0,0.4); }
  .hf-step-marker {
    width: 18px; height: 18px; border-radius: 50%;
    display: inline-flex; align-items: center; justify-content: center;
    font-size: 10px;
    flex: 0 0 auto;
  }
  .hf-step.done .hf-step-marker { color: rgba(0,0,0,0.4); }
  .hf-step.now  .hf-step-marker { background: #1a1a1c; color: #f8f6f4; box-shadow: 0 0 0 3px rgba(0,0,0,0.06); }
  .hf-step.next .hf-step-marker { color: rgba(0,0,0,0.35); border: 1px dashed rgba(0,0,0,0.25); }

  /* ask bar */
  .hf-ask {
    border-top: 0.5px solid rgba(0,0,0,0.08);
    padding: 9px 12px;
    display: flex; align-items: center; gap: 10px;
    background: rgba(255,255,255,0.32);
  }
  .hf-ask .hf-spark { color: rgba(0,0,0,0.45); display: inline-flex; }
  .hf-ask-placeholder { font-size: 13px; color: rgba(0,0,0,0.42); flex: 1; }
  .hf-ask-text { font-size: 13px; color: #0a0a0c; flex: 1; display: flex; align-items: center; }
  .hf-cursor { display: inline-block; width: 1.2px; height: 14px; background: #0a0a0c; margin-left: 1px; animation: hfblink 1s steps(2) infinite; vertical-align: middle; }
  @keyframes hfblink { 50% { opacity: 0; } }
  .hf-kbd {
    font-family: 'SF Mono', ui-monospace, Menlo, monospace;
    font-size: 10.5px; color: rgba(0,0,0,0.4);
    padding: 2px 6px; border-radius: 4px;
    background: rgba(0,0,0,0.04);
    box-shadow: inset 0 0 0 0.5px rgba(0,0,0,0.08);
  }
  .hf-send {
    width: 22px; height: 22px; border-radius: 6px; border: none;
    background: rgba(0,0,0,0.85); color: #f8f6f4; cursor: pointer;
    display: inline-flex; align-items: center; justify-content: center;
  }

  /* answer card */
  .hf-answer {
    margin: 10px 12px 4px;
    padding: 12px 14px;
    border-radius: 10px;
    background: rgba(255,255,255,0.55);
    box-shadow: inset 0 0 0 0.5px rgba(0,0,0,0.08);
  }
  .hf-answer-meta {
    display: flex; align-items: center; gap: 6px;
    font-size: 10.5px; letter-spacing: 0.04em; text-transform: uppercase;
    color: rgba(0,0,0,0.45); margin-bottom: 6px;
  }
  .hf-answer-q { font-size: 12px; color: rgba(0,0,0,0.55); margin-bottom: 6px; font-style: italic; }
  .hf-answer-body { font-size: 13.5px; line-height: 1.45; color: #0a0a0c; }
  .hf-answer-actions { margin-top: 10px; display: flex; gap: 6px; align-items: center; }
  .hf-btn {
    font-size: 12px; padding: 5px 11px;
    border-radius: 7px; border: none; cursor: pointer;
    background: rgba(0,0,0,0.06);
    color: #0a0a0c;
    transition: background .12s;
  }
  .hf-btn:hover { background: rgba(0,0,0,0.1); }
  .hf-btn.primary { background: #1a1a1c; color: #f8f6f4; }
  .hf-btn.primary:hover { background: #000; }
  .hf-btn.ghost { background: transparent; color: rgba(0,0,0,0.55); }

  /* steps faded behind answer */
  .hf-steps.faded { opacity: 0.35; pointer-events: none; }

  /* finished state */
  .hf-finished { padding: 28px 24px 24px; text-align: center; }
  .hf-finished-check {
    width: 44px; height: 44px; border-radius: 50%;
    background: #1a1a1c; color: #f8f6f4;
    display: inline-flex; align-items: center; justify-content: center;
    margin-bottom: 14px;
  }
  .hf-finished-title { font-size: 18px; font-weight: 600; letter-spacing: -0.01em; }
  .hf-finished-sub { font-size: 12px; color: rgba(0,0,0,0.5); margin-top: 4px; letter-spacing: 0.04em; text-transform: uppercase; }
  .hf-finished-actions { margin-top: 18px; display: flex; gap: 8px; justify-content: center; }

  /* typing dots */
  .hf-dots { display: inline-flex; gap: 4px; align-items: center; }
  .hf-dots span { width: 5px; height: 5px; border-radius: 50%; background: #0a0a0c; opacity: 0.3; animation: hfbounce 1.2s infinite ease-in-out; }
  .hf-dots span:nth-child(2){ animation-delay: 0.15s; }
  .hf-dots span:nth-child(3){ animation-delay: 0.3s; }
  @keyframes hfbounce { 0%,80%,100%{ opacity:.2; transform:translateY(0); } 40%{ opacity:.7; transform:translateY(-1px); } }

  /* caret cursor on screen */
  .hf-cursor-graphic {
    position: absolute; right: 80px; top: 60px; width: 14px; height: 18px;
    background: #fff; clip-path: polygon(0 0, 100% 60%, 50% 65%, 70% 100%, 50% 100%, 35% 70%, 0 85%);
    filter: drop-shadow(0 1px 2px rgba(0,0,0,0.4));
  }
  /* artboard label hint */
  .hf-state-label {
    position: absolute; bottom: 16px; left: 18px;
    font-family: 'SF Mono', ui-monospace, monospace;
    font-size: 10.5px; letter-spacing: 0.06em; text-transform: uppercase;
    color: rgba(255,255,255,0.7);
    padding: 4px 8px; border-radius: 5px;
    background: rgba(0,0,0,0.18);
    backdrop-filter: blur(6px);
  }
`;

if (typeof document !== 'undefined' && !document.getElementById('hf-css')) {
  const s = document.createElement('style'); s.id = 'hf-css'; s.textContent = HFCSS;
  document.head.appendChild(s);
}

const HFIcon = {
  Pencil: (p) => (
    <svg viewBox="0 0 16 16" width={p.size||14} height={p.size||14} fill="none" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 14l3.5-.7L13.3 5.5a1.5 1.5 0 000-2.1l-.7-.7a1.5 1.5 0 00-2.1 0L2.7 10.5 2 14z"/>
      <path d="M9.5 4.2l2.3 2.3"/>
    </svg>
  ),
  Spark: (p) => (
    <svg viewBox="0 0 16 16" width={p.size||13} height={p.size||13} fill="currentColor">
      <path d="M8 1.5l1.2 3.7 3.7 1.2-3.7 1.2L8 11.3 6.8 7.6 3.1 6.4l3.7-1.2z"/>
    </svg>
  ),
  Send: (p) => (
    <svg viewBox="0 0 16 16" width={p.size||12} height={p.size||12} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M8 13V3M4 7l4-4 4 4"/>
    </svg>
  ),
  Check: (p) => (
    <svg viewBox="0 0 16 16" width={p.size||20} height={p.size||20} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 8.5l3.5 3.5L13 5"/>
    </svg>
  ),
  CheckSmall: (p) => (
    <svg viewBox="0 0 16 16" width={p.size||10} height={p.size||10} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 8.5l3 3 7-7"/>
    </svg>
  ),
};

function HFChrome() {
  return (
    <div className="hf-chrome">
      <div className="hf-lights">
        <span className="hf-light close"/>
        <span className="hf-light min"/>
        <span className="hf-light max"/>
      </div>
      <button className="hf-iconbtn" title="New chat"><HFIcon.Pencil/></button>
    </div>
  );
}

function HFMeta({ step, total, label = 'Runpod Setup', right }) {
  return (
    <>
      <div className="hf-meta">
        <span>{label}</span>
        <span className="hf-mono" style={{ textTransform: 'none', letterSpacing: 0 }}>{right ?? `${step} of ${total}`}</span>
      </div>
      <div className="hf-progress"><span style={{ width: `${(step/total)*100}%` }}/></div>
    </>
  );
}

function HFSteps({ faded, current = 3, total = 12 }) {
  return (
    <div className={'hf-steps' + (faded ? ' faded' : '')}>
      <div className="hf-step done">
        <span className="hf-step-marker"><HFIcon.CheckSmall/></span>
        <span className="hf-step-text">Open the address bar</span>
      </div>
      <div className="hf-step now">
        <span className="hf-step-marker">●</span>
        <span className="hf-step-text">Type the Runpod URL into the address bar</span>
      </div>
      <div className="hf-step next">
        <span className="hf-step-marker">→</span>
        <span className="hf-step-text">Click Sign In in the top-right corner</span>
      </div>
    </div>
  );
}

function HFAskBar({ mode = 'idle' }) {
  // mode: idle | typing
  if (mode === 'typing') {
    return (
      <div className="hf-ask">
        <span className="hf-spark"><HFIcon.Spark/></span>
        <div className="hf-ask-text">what's a Runpod URL<span className="hf-cursor"/></div>
        <span className="hf-kbd">esc</span>
        <button className="hf-send" title="Send"><HFIcon.Send/></button>
      </div>
    );
  }
  return (
    <div className="hf-ask">
      <span className="hf-spark"><HFIcon.Spark/></span>
      <span className="hf-ask-placeholder">Ask Context anything</span>
      <span className="hf-kbd">⌘K</span>
    </div>
  );
}

// ── 5 STATE COMPOSITIONS ────────────────────────────────────────────────────

function HFIdle() {
  return (
    <div className="hf">
      <div className="hf-card" style={{ width: 340 }}>
        <HFChrome/>
        <HFMeta step={3} total={12}/>
        <HFSteps/>
        <HFAskBar mode="idle"/>
      </div>
    </div>
  );
}

function HFTyping() {
  return (
    <div className="hf">
      <div className="hf-card" style={{ width: 340 }}>
        <HFChrome/>
        <HFMeta step={3} total={12}/>
        <HFSteps/>
        <HFAskBar mode="typing"/>
      </div>
    </div>
  );
}

function HFStreaming() {
  return (
    <div className="hf">
      <div className="hf-card" style={{ width: 340 }}>
        <HFChrome/>
        <HFMeta step={3} total={12} right="paused"/>
        <div className="hf-answer">
          <div className="hf-answer-meta">
            <HFIcon.Spark size={11}/>
            <span>Answer · tutorial paused</span>
          </div>
          <div className="hf-answer-q">"what's a Runpod URL?"</div>
          <div className="hf-answer-body">
            Runpod's dashboard lives at <span className="hf-mono" style={{ fontSize: 12, padding: '1px 5px', background: 'rgba(0,0,0,0.05)', borderRadius: 4 }}>console.runpod.io</span> — it's where you<span className="hf-dots" style={{ marginLeft: 4 }}><span/><span/><span/></span>
          </div>
        </div>
        <HFSteps faded/>
        <HFAskBar mode="idle"/>
      </div>
    </div>
  );
}

function HFAnswered() {
  return (
    <div className="hf">
      <div className="hf-card" style={{ width: 340 }}>
        <HFChrome/>
        <HFMeta step={3} total={12} right="paused"/>
        <div className="hf-answer">
          <div className="hf-answer-meta">
            <HFIcon.Spark size={11}/>
            <span>Answer · tutorial paused</span>
          </div>
          <div className="hf-answer-q">"what's a Runpod URL?"</div>
          <div className="hf-answer-body">
            Runpod's dashboard lives at <span className="hf-mono" style={{ fontSize: 12, padding: '1px 5px', background: 'rgba(0,0,0,0.05)', borderRadius: 4 }}>console.runpod.io</span>. It's the page you'll sign into to spin up GPUs.
          </div>
          <div className="hf-answer-actions">
            <button className="hf-btn primary">↩ Resume tutorial</button>
            <button className="hf-btn ghost">Ask follow-up</button>
          </div>
        </div>
        <HFSteps faded/>
        <HFAskBar mode="idle"/>
      </div>
    </div>
  );
}

function HFFinished() {
  return (
    <div className="hf">
      <div className="hf-card" style={{ width: 340 }}>
        <HFChrome/>
        <div className="hf-finished">
          <div className="hf-finished-check"><HFIcon.Check/></div>
          <div className="hf-finished-title">All done</div>
          <div className="hf-finished-sub">12 steps · Runpod Setup</div>
          <div className="hf-finished-actions">
            <button className="hf-btn primary">Start new tutorial</button>
          </div>
        </div>
        <HFAskBar mode="idle"/>
      </div>
    </div>
  );
}

// stage wrapper that gives us the wallpaper background
function HFStage({ children, label }) {
  return (
    <div style={{ position: 'absolute', inset: 0, overflow: 'hidden' }}>
      <div className="hf-wall"/>
      <div className="hf-cursor-graphic"/>
      <div style={{ position: 'absolute', left: 30, top: 36 }}>
        {children}
      </div>
      <div className="hf-state-label">{label}</div>
    </div>
  );
}

Object.assign(window, { HFIdle, HFTyping, HFStreaming, HFAnswered, HFFinished, HFStage });
