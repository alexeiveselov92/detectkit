// `dtk ui` project-level monitoring cockpit renderer.
//
// Self-contained like report.ts: no ESM exports from the bundle, assigns
// `window.__DTK_UI__ = { render }`. Boot payload is the static metric list
// baked by detectkit/ui/html.py; everything else (overview stats, jobs) is
// fetched live from the localhost server (detectkit/ui/server.py) — see
// payload.ts for the wire contracts.
//
// Structure mirrors report.ts's "small render functions rebuild the DOM from
// state" style rather than a diffing framework: state lives in one `State`
// object here, and each section (tiles/tags/table/drawers) is a pure-ish
// builder in its own module that this file wires up and re-invokes on change.

import { esc } from './format';
import {
  fetchJobDetail,
  fetchJobs,
  fetchOverview,
  postAutotune,
  postRun,
  postStopJob,
  postTune,
  postUnlock,
} from './api';
import { ROOT_CLASS, injectStyle } from './style';
import { toast } from './toast';
import { buildTiles } from './tiles';
import { UNTAGGED, buildTags } from './tags';
import { DEFAULT_SORT_DIR, buildMetricsTable } from './table';
import type { SortKey, SortState } from './table';
import { openDetailOverlay } from './detail';
import type { DetailHandle } from './detail';
import { buildRunPanel } from './run-panel';
import type { RunPanelHandle, RunRequestDraft } from './run-panel';
import { buildJobsDrawer } from './jobs-drawer';
import type { JobsDrawerHandle } from './jobs-drawer';
import type {
  BootMetric,
  BootPayload,
  DtkUiGlobal,
  JobKind,
  JobSnapshot,
  OverviewPayload,
} from './payload';

const WINDOW_PRESETS: Array<{ value: string; label: string }> = [
  { value: '24h', label: '24h' },
  { value: '7d', label: '7d' },
  { value: '30d', label: '30d' },
  { value: '90d', label: '90d' },
  { value: 'all', label: 'All' },
];

interface State {
  windowPreset: string;
  overview: OverviewPayload | null;
  overviewError: string | null;
  jobs: JobSnapshot[];
  followedJobId: string | null;
  followOffset: number;
  tagFilter: string | null;
  sort: SortState;
}

function render(boot: BootPayload, mount: HTMLElement): void {
  injectStyle();
  mount.classList.add(ROOT_CLASS);
  mount.innerHTML = '';

  const root = document.createElement('div');
  root.className = `${ROOT_CLASS}-root`;
  mount.appendChild(root);

  const state: State = {
    windowPreset: boot.initial_window || '30d',
    overview: null,
    overviewError: null,
    jobs: [],
    followedJobId: null,
    followOffset: 0,
    tagFilter: null,
    sort: { key: 'alerts', dir: DEFAULT_SORT_DIR.alerts },
  };

  let detailHandle: DetailHandle | null = null;
  let jobsPollHandle: number | undefined;
  let jobDetailHandle: number | undefined;

  // ---- select-field options (metric names + tag:x), from boot + overview --
  function selectOptions(): string[] {
    const names = new Set<string>();
    const tags = new Set<string>();
    const collect = (list: Array<BootMetric | { name: string; tags: string[] }>): void => {
      for (const m of list) {
        names.add(m.name);
        for (const t of m.tags) tags.add(t);
      }
    };
    collect(boot.metrics);
    if (state.overview) collect(state.overview.metrics);
    return [...names, ...[...tags].map((t) => `tag:${t}`)];
  }

  function pipelineBusy(): { busy: boolean; reason: string } {
    const running = state.jobs.find((j) => j.status === 'running' && j.kind !== 'tune');
    if (running) return { busy: true, reason: `a pipeline job is already running (${running.label})` };
    return { busy: false, reason: '' };
  }

  // ---- header ---------------------------------------------------------------
  const header = document.createElement('div');
  header.className = 'dtk-ui-header';
  root.appendChild(header);

  const brand = document.createElement('div');
  brand.className = 'dtk-ui-brand';
  brand.innerHTML =
    `<span class="dtk-ui-brand-dot"></span>` +
    `<span class="dtk-ui-brand-name">detectkit · <b>${esc(boot.project)}</b></span>`;
  header.appendChild(brand);

  const headerRight = document.createElement('div');
  headerRight.className = 'dtk-ui-header-right';
  header.appendChild(headerRight);

  const seg = document.createElement('div');
  seg.className = 'dtk-ui-seg';
  for (const preset of WINDOW_PRESETS) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'dtk-ui-seg-btn' + (state.windowPreset === preset.value ? ' on' : '');
    btn.textContent = preset.label;
    btn.onclick = (): void => {
      if (state.windowPreset === preset.value) return;
      state.windowPreset = preset.value;
      seg.querySelectorAll('.dtk-ui-seg-btn').forEach((b) => b.classList.remove('on'));
      btn.classList.add('on');
      if (detailHandle) detailHandle.setWindow(preset.value);
      void refreshOverview();
    };
    seg.appendChild(btn);
  }
  headerRight.appendChild(seg);

  const refreshBtn = document.createElement('button');
  refreshBtn.type = 'button';
  refreshBtn.className = 'dtk-ui-iconbtn';
  refreshBtn.title = 'Refresh overview';
  refreshBtn.textContent = '⟳';
  refreshBtn.onclick = (): void => void refreshOverview();
  headerRight.appendChild(refreshBtn);

  const runPipelineBtn = document.createElement('button');
  runPipelineBtn.type = 'button';
  runPipelineBtn.className = 'dtk-ui-runbtn';
  runPipelineBtn.textContent = 'Run pipeline';
  runPipelineBtn.onclick = (): void => openRunPanel();
  headerRight.appendChild(runPipelineBtn);

  const jobsChip = document.createElement('button');
  jobsChip.type = 'button';
  jobsChip.className = 'dtk-ui-jobschip';
  jobsChip.innerHTML = '<span class="dtk-ui-jobschip-dot"></span><span>idle</span>';
  jobsChip.onclick = (): void => {
    if (jobsDrawer.isOpen()) jobsDrawer.close();
    else openJobsDrawer();
  };
  headerRight.appendChild(jobsChip);

  function updateJobsChip(): void {
    const running = state.jobs.find((j) => j.status === 'running');
    jobsChip.classList.toggle('running', !!running);
    const label = running ? `${running.kind} ${running.label}` : 'idle';
    const span = jobsChip.querySelector('span:last-child');
    if (span) span.textContent = label;
    jobsChip.title = running ? `Started ${new Date(running.started_at).toLocaleString()}` : 'No jobs running';
  }

  // ---- content (tiles / tags / table), rebuilt on every state change --------
  const content = document.createElement('div');
  content.className = 'dtk-ui-content';
  root.appendChild(content);

  function renderContent(): void {
    content.innerHTML = '';

    if (state.overviewError) {
      const banner = document.createElement('div');
      banner.className = 'dtk-ui-banner';
      banner.innerHTML = `<span>Failed to load overview: ${esc(state.overviewError)}</span>`;
      const retry = document.createElement('button');
      retry.type = 'button';
      retry.className = 'dtk-ui-banner-retry';
      retry.textContent = 'Retry';
      retry.onclick = (): void => void refreshOverview();
      banner.appendChild(retry);
      content.appendChild(banner);
    }

    if (!state.overview) {
      if (!state.overviewError) {
        const loading = document.createElement('div');
        loading.className = 'dtk-ui-empty';
        loading.textContent = 'Loading overview…';
        content.appendChild(loading);
      }
      return;
    }

    const ov = state.overview;
    if (ov.metrics.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'dtk-ui-empty';
      empty.textContent = boot.metrics.length === 0
        ? 'No metrics found for this project/selector.'
        : 'No metrics in this window.';
      content.appendChild(empty);
      return;
    }

    content.appendChild(buildTiles(ov));
    content.appendChild(
      buildTags(ov.metrics, state.tagFilter, (tag) => {
        state.tagFilter = tag;
        renderContent();
      }),
    );

    const filtered =
      state.tagFilter === null
        ? ov.metrics
        : ov.metrics.filter((m) =>
            state.tagFilter === UNTAGGED ? m.tags.length === 0 : m.tags.includes(state.tagFilter as string),
          );

    const tableResult = buildMetricsTable(filtered, state.sort, ov.now, {
      onOpen: openDetail,
      onTune: (name) => void submitTune(name),
      onRun: (name) => openRunPanel(name),
      onSortChange: (key: SortKey) => {
        state.sort =
          state.sort.key === key
            ? { key, dir: state.sort.dir === 'asc' ? 'desc' : 'asc' }
            : { key, dir: DEFAULT_SORT_DIR[key] };
        renderContent();
      },
    });
    content.appendChild(tableResult.el);
    tableResult.paint();
  }

  // ---- detail overlay ---------------------------------------------------------
  function openDetail(name: string): void {
    if (detailHandle) detailHandle.close();
    detailHandle = openDetailOverlay(root, name, state.windowPreset, {
      onTune: (n) => void submitTune(n),
      onClose: () => {
        detailHandle = null;
      },
    });
  }

  // ---- run panel + jobs drawer -----------------------------------------------
  const runPanel: RunPanelHandle = buildRunPanel(root, {
    submitRun: (req: RunRequestDraft) => void submitRun(req),
    submitAutotune: (req) => void submitAutotune(req),
    submitUnlock: (req) => void submitUnlock(req),
    getSelectOptions: selectOptions,
    isPipelineBusy: pipelineBusy,
  });

  const jobsDrawer: JobsDrawerHandle = buildJobsDrawer(root, {
    onFollow: (jobId: string) => followJob(jobId),
    onStop: (jobId: string) => void stopJob(jobId),
  });

  function openRunPanel(prefillSelect?: string): void {
    jobsDrawer.close();
    runPanel.refreshOptions();
    runPanel.refreshBusyState();
    runPanel.open(prefillSelect);
  }

  function openJobsDrawer(): void {
    runPanel.close();
    jobsDrawer.render(state.jobs, Date.now(), state.followedJobId);
    jobsDrawer.open();
    ensureJobsPolling();
  }

  // ---- job spawning + tracking ------------------------------------------------
  function trackSpawnedJob(kind: JobKind, label: string, jobId: string, url: string | null): void {
    const placeholder: JobSnapshot = {
      id: jobId,
      kind,
      label,
      status: 'running',
      returncode: null,
      url,
      started_at: Date.now(),
      finished_at: null,
    };
    state.jobs = [placeholder, ...state.jobs.filter((j) => j.id !== jobId)];
    renderJobsUi();
    ensureJobsPolling();
    void refreshJobs();
  }

  // In-flight guards: a double-click (or a click in each of two open panels)
  // must not fire a second POST while the first is still in flight. The server
  // enforces this too (atomic pipeline gate, per-metric tune dedup) — these
  // guards just keep the honest path quiet instead of surfacing a 400 toast.
  let pipelineSubmitPending = false;
  const pendingTunes = new Set<string>();

  async function submitRun(req: RunRequestDraft): Promise<void> {
    if (pipelineSubmitPending) return;
    pipelineSubmitPending = true;
    try {
      const res = await postRun(req);
      trackSpawnedJob('run', `run --select ${req.select}`, res.job_id, null);
      followJob(res.job_id);
    } catch (e) {
      toast(root, 'error', (e as Error).message);
    } finally {
      pipelineSubmitPending = false;
    }
  }

  async function submitAutotune(req: { select: string; from: string | null; to: string | null }): Promise<void> {
    if (pipelineSubmitPending) return;
    pipelineSubmitPending = true;
    try {
      const res = await postAutotune(req);
      trackSpawnedJob('autotune', `autotune --select ${req.select}`, res.job_id, null);
      followJob(res.job_id);
    } catch (e) {
      toast(root, 'error', (e as Error).message);
    } finally {
      pipelineSubmitPending = false;
    }
  }

  async function submitUnlock(req: { select: string }): Promise<void> {
    if (pipelineSubmitPending) return;
    pipelineSubmitPending = true;
    try {
      const res = await postUnlock(req);
      trackSpawnedJob('unlock', `unlock --select ${req.select}`, res.job_id, null);
      followJob(res.job_id);
    } catch (e) {
      toast(root, 'error', (e as Error).message);
    } finally {
      pipelineSubmitPending = false;
    }
  }

  async function submitTune(metric: string): Promise<void> {
    if (pendingTunes.has(metric)) return;
    pendingTunes.add(metric);
    toast(root, 'info', `Opening tuner for ${metric}…`);
    try {
      const res = await postTune({ metric });
      trackSpawnedJob('tune', `tune --select ${metric}`, res.job_id, res.url);
      window.open(res.url, '_blank');
    } catch (e) {
      toast(root, 'error', (e as Error).message);
    } finally {
      pendingTunes.delete(metric);
    }
  }

  async function stopJob(jobId: string): Promise<void> {
    try {
      await postStopJob(jobId);
      toast(root, 'info', 'Stop requested.');
      void refreshJobs();
    } catch (e) {
      toast(root, 'error', (e as Error).message);
    }
  }

  function followJob(jobId: string): void {
    state.followedJobId = jobId;
    state.followOffset = 0;
    openRunPanel();
    runPanel.resetLog();
    startJobDetailPoll(jobId);
  }

  // ---- polling: /api/jobs every 2s while the drawer is open or a job runs ---
  function renderJobsUi(): void {
    updateJobsChip();
    jobsDrawer.render(state.jobs, Date.now(), state.followedJobId);
    runPanel.refreshBusyState();
  }

  async function refreshJobs(): Promise<void> {
    try {
      const data = await fetchJobs();
      state.jobs = data.jobs;
    } catch {
      // transient — the next tick (or the next spawn) will retry
    }
    renderJobsUi();
  }

  function ensureJobsPolling(): void {
    if (jobsPollHandle !== undefined) return;
    const tick = (): void => {
      void refreshJobs().then(() => {
        const keepGoing = jobsDrawer.isOpen() || state.jobs.some((j) => j.status === 'running');
        jobsPollHandle = keepGoing ? window.setTimeout(tick, 2000) : undefined;
      });
    };
    jobsPollHandle = window.setTimeout(tick, 2000);
  }

  // ---- polling: /api/job/<id>?offset= every 1s for the followed job ---------
  function stopJobDetailPoll(): void {
    if (jobDetailHandle !== undefined) {
      window.clearTimeout(jobDetailHandle);
      jobDetailHandle = undefined;
    }
  }

  function startJobDetailPoll(jobId: string): void {
    stopJobDetailPoll();
    const tick = (): void => {
      fetchJobDetail(jobId, state.followOffset)
        .then((detail) => {
          if (state.followedJobId !== jobId) return; // a different job is now followed
          runPanel.appendLog(detail.lines);
          state.followOffset = detail.next_offset;
          if (detail.status !== 'running') {
            runPanel.setLogStatus(detail.status, detail.returncode);
            jobDetailHandle = undefined;
            void refreshJobs();
            return;
          }
          jobDetailHandle = window.setTimeout(tick, 1000);
        })
        .catch((e: Error) => {
          toast(root, 'error', `job ${jobId}: ${e.message}`);
          jobDetailHandle = undefined;
        });
    };
    jobDetailHandle = window.setTimeout(tick, 0);
  }

  // ---- overview fetch ---------------------------------------------------------
  async function refreshOverview(): Promise<void> {
    refreshBtn.classList.add('spinning');
    try {
      state.overview = await fetchOverview(state.windowPreset);
      state.overviewError = null;
    } catch (e) {
      state.overviewError = (e as Error).message;
    } finally {
      refreshBtn.classList.remove('spinning');
      renderContent();
      runPanel.refreshOptions();
    }
  }

  // ---- boot ---------------------------------------------------------------
  renderContent();
  runPanel.refreshOptions();
  void refreshOverview();
  void refreshJobs();
}

(window as unknown as { __DTK_UI__: DtkUiGlobal }).__DTK_UI__ = { render };
