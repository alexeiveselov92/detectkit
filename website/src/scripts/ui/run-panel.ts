// Run panel: the right-side drawer that drives `dtk run` / `dtk autotune` /
// `dtk unlock` as spawned subprocesses. Built once and toggled open/closed so
// form state + the log terminal survive being opened from different rows.

import { esc } from './format';
import type { PipelineStep } from './payload';

const DATE_RE = /^\d{4}-\d{2}-\d{2}( \d{2}:\d{2}:\d{2})?$/;
const DATALIST_ID = 'dtk-ui-run-select-options';

export interface RunRequestDraft {
  select: string;
  steps: PipelineStep[];
  from: string | null;
  to: string | null;
  full_refresh: boolean;
  force: boolean;
}

export interface RunPanelCallbacks {
  submitRun(req: RunRequestDraft): void;
  submitAutotune(req: { select: string; from: string | null; to: string | null }): void;
  submitUnlock(req: { select: string }): void;
  getSelectOptions(): string[];
  /** Whether a run/autotune/unlock job is currently in flight, and why to show if so. */
  isPipelineBusy(): { busy: boolean; reason: string };
}

export interface RunPanelHandle {
  el: HTMLElement;
  open(prefillSelect?: string): void;
  close(): void;
  isOpen(): boolean;
  /** Re-read getSelectOptions() into the datalist (call once overview data arrives). */
  refreshOptions(): void;
  /** Re-evaluate isPipelineBusy() and update button disabled state + reason text. */
  refreshBusyState(): void;
  /** Clear the log terminal for a freshly-spawned job. */
  resetLog(): void;
  /** Append new lines (already offset-paginated by the caller). */
  appendLog(lines: string[]): void;
  setLogStatus(status: 'running' | 'done' | 'failed' | 'stopped', returncode: number | null): void;
}

export function buildRunPanel(root: HTMLElement, cb: RunPanelCallbacks): RunPanelHandle {
  const backdrop = document.createElement('div');
  backdrop.className = 'dtk-ui-drawer-backdrop';
  const drawer = document.createElement('div');
  drawer.className = 'dtk-ui-drawer';

  const head = document.createElement('div');
  head.className = 'dtk-ui-drawer-head';
  head.innerHTML = '<span class="dtk-ui-drawer-title">Run pipeline</span>';
  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'dtk-ui-drawer-close';
  closeBtn.textContent = '✕';
  head.appendChild(closeBtn);
  drawer.appendChild(head);

  const body = document.createElement('div');
  body.className = 'dtk-ui-drawer-body';
  drawer.appendChild(body);

  // --- select --------------------------------------------------------------
  const selectField = document.createElement('div');
  selectField.className = 'dtk-ui-field';
  const datalist = document.createElement('datalist');
  datalist.id = DATALIST_ID;
  const selectInput = document.createElement('input');
  selectInput.type = 'text';
  selectInput.className = 'dtk-ui-input';
  selectInput.placeholder = 'metric name, tag:x, glob, or *';
  selectInput.value = '*';
  selectInput.setAttribute('list', DATALIST_ID);
  selectField.innerHTML = '<span class="dtk-ui-field-label">Select</span>';
  selectField.append(selectInput, datalist);
  body.appendChild(selectField);

  // --- steps -----------------------------------------------------------------
  const stepsField = document.createElement('div');
  stepsField.className = 'dtk-ui-field';
  stepsField.innerHTML = '<span class="dtk-ui-field-label">Steps</span>';
  const stepsRow = document.createElement('div');
  stepsRow.className = 'dtk-ui-checks';
  const stepBoxes: Record<PipelineStep, HTMLInputElement> = {} as Record<PipelineStep, HTMLInputElement>;
  for (const step of ['load', 'detect', 'alert'] as PipelineStep[]) {
    const label = document.createElement('label');
    label.className = 'dtk-ui-check';
    const box = document.createElement('input');
    box.type = 'checkbox';
    box.checked = true;
    box.onchange = validate;
    label.append(box, document.createTextNode(step));
    stepsRow.appendChild(label);
    stepBoxes[step] = box;
  }
  stepsField.appendChild(stepsRow);
  body.appendChild(stepsField);

  // --- from/to -----------------------------------------------------------------
  const rangeRow = document.createElement('div');
  rangeRow.className = 'dtk-ui-row2';
  const fromField = document.createElement('div');
  fromField.className = 'dtk-ui-field';
  fromField.innerHTML = '<span class="dtk-ui-field-label">From</span>';
  const fromInput = document.createElement('input');
  fromInput.type = 'text';
  fromInput.className = 'dtk-ui-input';
  fromInput.placeholder = 'YYYY-MM-DD [HH:MM:SS]';
  fromInput.oninput = validate;
  fromField.appendChild(fromInput);
  const toField = document.createElement('div');
  toField.className = 'dtk-ui-field';
  toField.innerHTML = '<span class="dtk-ui-field-label">To</span>';
  const toInput = document.createElement('input');
  toInput.type = 'text';
  toInput.className = 'dtk-ui-input';
  toInput.placeholder = 'YYYY-MM-DD [HH:MM:SS]';
  toInput.oninput = validate;
  toField.appendChild(toInput);
  rangeRow.append(fromField, toField);
  body.appendChild(rangeRow);

  // --- flags -----------------------------------------------------------------
  const flagsRow = document.createElement('div');
  flagsRow.className = 'dtk-ui-checks';
  const forceLabel = document.createElement('label');
  forceLabel.className = 'dtk-ui-check';
  const forceBox = document.createElement('input');
  forceBox.type = 'checkbox';
  forceLabel.append(forceBox, document.createTextNode('force (skip lock check)'));
  const fullRefreshLabel = document.createElement('label');
  fullRefreshLabel.className = 'dtk-ui-check';
  const fullRefreshBox = document.createElement('input');
  fullRefreshBox.type = 'checkbox';
  fullRefreshLabel.append(fullRefreshBox, document.createTextNode('full refresh'));
  flagsRow.append(forceLabel, fullRefreshLabel);
  body.appendChild(flagsRow);

  // --- action buttons ----------------------------------------------------------
  const btnRow = document.createElement('div');
  btnRow.className = 'dtk-ui-btnrow';
  const runBtn = document.createElement('button');
  runBtn.type = 'button';
  runBtn.className = 'dtk-ui-btn primary';
  runBtn.textContent = 'Run';
  const autotuneBtn = document.createElement('button');
  autotuneBtn.type = 'button';
  autotuneBtn.className = 'dtk-ui-btn';
  autotuneBtn.textContent = 'Autotune';
  const unlockBtn = document.createElement('button');
  unlockBtn.type = 'button';
  unlockBtn.className = 'dtk-ui-btn danger';
  unlockBtn.textContent = 'Unlock';
  btnRow.append(runBtn, autotuneBtn, unlockBtn);
  body.appendChild(btnRow);

  const reason = document.createElement('div');
  reason.className = 'dtk-ui-reason';
  body.appendChild(reason);

  // --- log terminal --------------------------------------------------------
  const logField = document.createElement('div');
  logField.className = 'dtk-ui-field';
  logField.innerHTML = '<span class="dtk-ui-field-label">Log</span>';
  const logEl = document.createElement('div');
  logEl.className = 'dtk-ui-log';
  const logBody = document.createElement('div');
  logBody.className = 'dtk-ui-log-body';
  const logExit = document.createElement('div');
  logExit.className = 'dtk-ui-log-line';
  logEl.append(logBody, logExit);
  logField.appendChild(logEl);
  body.appendChild(logField);

  let logLines: string[] = [];
  function renderLogBody(): void {
    logBody.innerHTML =
      logLines.length === 0
        ? '<span class="dtk-ui-log-empty">no output yet</span>'
        : logLines.map(esc).join('<br>');
  }
  renderLogBody();

  function userNearBottom(): boolean {
    return logEl.scrollTop + logEl.clientHeight >= logEl.scrollHeight - 24;
  }

  // --- validation / busy state -----------------------------------------------
  function activeSteps(): PipelineStep[] {
    return (Object.keys(stepBoxes) as PipelineStep[]).filter((s) => stepBoxes[s].checked);
  }

  function validate(): void {
    const busy = cb.isPipelineBusy();
    const select = selectInput.value.trim();
    const fromOk = fromInput.value.trim() === '' || DATE_RE.test(fromInput.value.trim());
    const toOk = toInput.value.trim() === '' || DATE_RE.test(toInput.value.trim());
    let msg = '';
    if (busy.busy) msg = busy.reason;
    else if (select === '') msg = 'select is required';
    else if (!fromOk || !toOk) msg = 'from/to must be YYYY-MM-DD or YYYY-MM-DD HH:MM:SS';
    else if (activeSteps().length === 0) msg = 'pick at least one step to run';

    reason.textContent = msg;
    runBtn.disabled = msg !== '';
    // Autotune doesn't use the steps checkboxes, so "pick at least one step"
    // shouldn't block it specifically — re-derive its own condition.
    autotuneBtn.disabled = busy.busy || select === '' || !fromOk || !toOk;
    unlockBtn.disabled = busy.busy || select === '';
  }

  function draft(): RunRequestDraft {
    return {
      select: selectInput.value.trim(),
      steps: activeSteps(),
      from: fromInput.value.trim() || null,
      to: toInput.value.trim() || null,
      full_refresh: fullRefreshBox.checked,
      force: forceBox.checked,
    };
  }

  runBtn.onclick = (): void => cb.submitRun(draft());
  autotuneBtn.onclick = (): void =>
    cb.submitAutotune({
      select: selectInput.value.trim(),
      from: fromInput.value.trim() || null,
      to: toInput.value.trim() || null,
    });
  unlockBtn.onclick = (): void => {
    const select = selectInput.value.trim();
    if (window.confirm(`Unlock the pipeline lock for "${select}"? Only do this if you're sure no dtk process is actually running against it.`)) {
      cb.submitUnlock({ select });
    }
  };

  function close(): void {
    backdrop.classList.remove('open');
    drawer.classList.remove('open');
  }
  closeBtn.onclick = close;
  backdrop.onclick = close;

  root.append(backdrop, drawer);

  return {
    el: drawer,
    open(prefillSelect?: string): void {
      if (prefillSelect) selectInput.value = prefillSelect;
      backdrop.classList.add('open');
      drawer.classList.add('open');
      validate();
    },
    close,
    isOpen(): boolean {
      return drawer.classList.contains('open');
    },
    refreshOptions(): void {
      datalist.innerHTML = ['*', ...cb.getSelectOptions()].map((v) => `<option value="${esc(v)}"></option>`).join('');
    },
    refreshBusyState: validate,
    resetLog(): void {
      logLines = [];
      renderLogBody();
      logExit.textContent = '';
      logExit.className = 'dtk-ui-log-line';
    },
    appendLog(lines: string[]): void {
      if (lines.length === 0) return;
      const stick = userNearBottom();
      logLines.push(...lines);
      renderLogBody();
      if (stick) logEl.scrollTop = logEl.scrollHeight;
    },
    setLogStatus(status: 'running' | 'done' | 'failed' | 'stopped', returncode: number | null): void {
      if (status === 'running') return;
      const cls = status === 'done' && returncode === 0 ? 'exit-ok' : status === 'stopped' ? 'exit-stop' : 'exit-fail';
      logExit.className = `dtk-ui-log-line ${cls}`;
      logExit.textContent = `── ${status} (exit ${returncode ?? '?'}) ──`;
    },
  };
}
