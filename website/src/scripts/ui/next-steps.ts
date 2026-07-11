// Post-create "next steps" strip: the guided tail of the metric-creation flow.
//
// Creating a metric writes only YAML — the useful loop closes by loading real
// data and then tuning the detector on it (`dtk run --steps load,detect`, then
// the tune cockpit). This strip renders that path right after a create so the
// user doesn't have to reconstruct it from the run panel: one button spawns
// the load+detect job (deliberately NO alert step — an untuned config must
// never spam a real channel), and Open tune unlocks once that job succeeds
// (the tune cockpit needs persisted datapoints to show anything).
//
// Stateless render-into-box like table.ts/tiles.ts: ui.ts owns the state
// (including the spawned job id, matched against the polled job list) and
// re-renders on every jobs tick.

export type NextStepsPhase = 'idle' | 'running' | 'done' | 'failed';

export interface NextStepsState {
  metric: string;
  /** The spawned load+detect job, once started — matched against /api/jobs polls. */
  jobId: string | null;
  phase: NextStepsPhase;
}

export interface NextStepsCallbacks {
  onLoad(metric: string): void;
  onTune(metric: string): void;
  onFollow(jobId: string): void;
  onDismiss(): void;
}

/** Render the strip for `st` into `box` (empty box when `st` is null). */
export function renderNextSteps(
  box: HTMLElement,
  st: NextStepsState | null,
  cb: NextStepsCallbacks,
): void {
  box.innerHTML = '';
  if (!st) return;

  const strip = document.createElement('div');
  strip.className = 'dtk-ui-nextsteps' + (st.phase === 'failed' ? ' failed' : '');

  const text = document.createElement('span');
  text.className = 'dtk-ui-nextsteps-text';
  const name = document.createElement('b');
  name.textContent = st.metric;
  if (st.phase === 'done') {
    text.append('Data loaded for ', name, ' — tune the detector on the real series.');
  } else if (st.phase === 'running') {
    text.append('Loading data for ', name, '… ');
    const follow = document.createElement('a');
    follow.href = '#';
    follow.className = 'dtk-ui-nextsteps-link';
    follow.textContent = 'view log';
    follow.onclick = (e: MouseEvent): void => {
      e.preventDefault();
      if (st.jobId) cb.onFollow(st.jobId);
    };
    text.appendChild(follow);
  } else if (st.phase === 'failed') {
    text.append('Loading data for ', name, ' failed — check the log, then retry.');
  } else {
    text.append('Metric ', name, ' created. Next: load data, then tune the detector on it.');
  }
  strip.appendChild(text);

  const actions = document.createElement('div');
  actions.className = 'dtk-ui-nextsteps-actions';

  const loadBtn = document.createElement('button');
  loadBtn.type = 'button';
  loadBtn.className = 'dtk-ui-btn' + (st.phase === 'idle' || st.phase === 'failed' ? ' primary' : '');
  loadBtn.textContent = st.phase === 'failed' ? 'Retry load' : 'Load & detect';
  loadBtn.disabled = st.phase === 'running';
  loadBtn.title = 'Runs `dtk run --steps load,detect` for this metric (no alerts sent)';
  loadBtn.onclick = (): void => cb.onLoad(st.metric);
  actions.appendChild(loadBtn);

  if (st.phase === 'running') {
    const spin = document.createElement('span');
    spin.className = 'dtk-ui-nextsteps-spin';
    actions.appendChild(spin);
  }

  const tuneBtn = document.createElement('button');
  tuneBtn.type = 'button';
  tuneBtn.className = 'dtk-ui-btn' + (st.phase === 'done' ? ' primary' : '');
  tuneBtn.textContent = 'Open tune';
  tuneBtn.disabled = st.phase !== 'done';
  tuneBtn.title =
    st.phase === 'done'
      ? 'Open the tune cockpit on the loaded series'
      : 'Load data first — the tune cockpit works on persisted datapoints';
  tuneBtn.onclick = (): void => cb.onTune(st.metric);
  actions.appendChild(tuneBtn);

  const dismiss = document.createElement('button');
  dismiss.type = 'button';
  dismiss.className = 'dtk-ui-nextsteps-close';
  dismiss.textContent = '✕';
  dismiss.title = 'Dismiss';
  dismiss.onclick = (): void => cb.onDismiss();
  actions.appendChild(dismiss);

  strip.appendChild(actions);
  box.appendChild(strip);
}
