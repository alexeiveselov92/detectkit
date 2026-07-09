// Jobs drawer: list of the last spawned jobs (run/autotune/unlock/tune),
// opened from the header's jobs chip. Clicking a row follows its output in
// the run panel's log terminal; running jobs get a Stop button; tune jobs
// carry an "Open tuner" link once the server has echoed the ready URL.

import { esc, fmtAgo, fmtDuration } from './format';
import type { JobSnapshot } from './payload';

export interface JobsDrawerCallbacks {
  onFollow(jobId: string): void;
  onStop(jobId: string): void;
}

export interface JobsDrawerHandle {
  el: HTMLElement;
  open(): void;
  close(): void;
  isOpen(): boolean;
  render(jobs: JobSnapshot[], now: number, followedId: string | null): void;
}

function statusDotColor(status: JobSnapshot['status']): string {
  if (status === 'done') return 'var(--st-recovery)';
  if (status === 'failed') return 'var(--st-anomaly)';
  if (status === 'running') return 'var(--clay)';
  return 'var(--faint)'; // stopped
}

export function buildJobsDrawer(root: HTMLElement, cb: JobsDrawerCallbacks): JobsDrawerHandle {
  const backdrop = document.createElement('div');
  backdrop.className = 'dtk-ui-drawer-backdrop';
  const drawer = document.createElement('div');
  drawer.className = 'dtk-ui-drawer';

  const head = document.createElement('div');
  head.className = 'dtk-ui-drawer-head';
  head.innerHTML = '<span class="dtk-ui-drawer-title">Jobs</span>';
  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'dtk-ui-drawer-close';
  closeBtn.textContent = '✕';
  head.appendChild(closeBtn);
  drawer.appendChild(head);

  const body = document.createElement('div');
  body.className = 'dtk-ui-drawer-body';
  drawer.appendChild(body);

  const list = document.createElement('div');
  list.className = 'dtk-ui-joblist';
  body.appendChild(list);

  function close(): void {
    backdrop.classList.remove('open');
    drawer.classList.remove('open');
  }
  closeBtn.onclick = close;
  backdrop.onclick = close;

  root.append(backdrop, drawer);

  return {
    el: drawer,
    open(): void {
      backdrop.classList.add('open');
      drawer.classList.add('open');
    },
    close,
    isOpen(): boolean {
      return drawer.classList.contains('open');
    },
    render(jobs: JobSnapshot[], now: number, followedId: string | null): void {
      if (jobs.length === 0) {
        list.innerHTML = '<div class="dtk-ui-empty">No jobs yet.</div>';
        return;
      }
      list.innerHTML = '';
      for (const job of jobs) {
        const row = document.createElement('div');
        row.className = 'dtk-ui-jobrow' + (job.id === followedId ? ' active' : '');
        const dotCls = job.status === 'running' ? ' pulse' : '';
        const dur = fmtDuration(job.started_at, job.finished_at ?? now);
        const top = document.createElement('div');
        top.className = 'dtk-ui-jobrow-top';
        top.innerHTML =
          `<span class="dtk-ui-jobrow-status">` +
          `<span class="dtk-ui-jobrow-dot${dotCls}" style="background:${statusDotColor(job.status)}"></span>` +
          `${esc(job.kind)} · ${esc(job.status)}</span>` +
          `<span class="dtk-ui-jobrow-meta">${esc(fmtAgo(now, job.started_at))} · ${esc(dur)}</span>`;
        row.appendChild(top);

        const label = document.createElement('div');
        label.className = 'dtk-ui-jobrow-label';
        label.textContent = job.label;
        row.appendChild(label);

        const actions = document.createElement('div');
        actions.className = 'dtk-ui-jobrow-actions';
        if (job.status === 'running') {
          const stopBtn = document.createElement('button');
          stopBtn.type = 'button';
          stopBtn.className = 'dtk-ui-actionbtn';
          stopBtn.textContent = 'Stop';
          stopBtn.onclick = (e): void => {
            e.stopPropagation();
            cb.onStop(job.id);
          };
          actions.appendChild(stopBtn);
        }
        if (job.kind === 'tune' && job.url) {
          const link = document.createElement('a');
          link.className = 'dtk-ui-joblink';
          link.href = job.url;
          link.target = '_blank';
          link.rel = 'noopener';
          link.textContent = 'Open tuner';
          link.onclick = (e): void => e.stopPropagation();
          actions.appendChild(link);
        }
        if (actions.childElementCount > 0) row.appendChild(actions);

        row.onclick = (): void => cb.onFollow(job.id);
        list.appendChild(row);
      }
    },
  };
}
