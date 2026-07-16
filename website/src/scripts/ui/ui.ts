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
  fetchCleanPreview,
  fetchJobDetail,
  fetchJobs,
  fetchMetricSource,
  fetchMetricStats,
  postAutotune,
  postClean,
  postRun,
  postStopJob,
  postTune,
  postUnlock,
} from './api';
import { ROOT_CLASS, injectStyle } from './style';
import { toast } from './toast';
import { buildTiles } from './tiles';
import { UNTAGGED, buildTags } from './tags';
import { DEFAULT_SORT_DIR, buildMetricsTable, buildPendingRow } from './table';
import type { SortKey, SortState } from './table';
import { openDetailOverlay } from './detail';
import type { DetailHandle } from './detail';
import { buildRunPanel } from './run-panel';
import type { RunPanelHandle, RunRequestDraft } from './run-panel';
import { buildJobsDrawer } from './jobs-drawer';
import type { JobsDrawerHandle } from './jobs-drawer';
import { NEW_METRIC_TEMPLATE, openMetricEditor } from './metric-editor';
import type { EditorMode, MetricEditorHandle } from './metric-editor';
import { renderNextSteps } from './next-steps';
import type { NextStepsState } from './next-steps';
import type {
  BootMetric,
  BootPayload,
  CleanPreviewResponse,
  DtkUiGlobal,
  FormMeta,
  JobKind,
  JobSnapshot,
  MetricMutationResponse,
  OverviewMetric,
} from './payload';

/** Per-metric stats fetches in flight at once (the server serializes DB access anyway). */
const STATS_CONCURRENCY = 3;

const WINDOW_PRESETS: Array<{ value: string; label: string }> = [
  { value: '24h', label: '24h' },
  { value: '7d', label: '7d' },
  { value: '30d', label: '30d' },
  { value: '90d', label: '90d' },
  { value: 'all', label: 'All' },
];

interface State {
  windowPreset: string;
  /**
   * One row per boot metric, always fully populated (never `null`/empty while
   * loading) — a row not yet fetched carries `pending: true` (see
   * `table.ts`'s `buildPendingRow`). The cockpit fetches stats incrementally,
   * one metric at a time, instead of one monolithic `/api/overview` call (see
   * `loadOverview` below).
   */
  metrics: OverviewMetric[];
  jobs: JobSnapshot[];
  followedJobId: string | null;
  followOffset: number;
  tagFilter: string | null;
  sort: SortState;
  /** Post-create guided flow (load data → tune), one metric at a time. */
  nextSteps: NextStepsState | null;
}

function render(boot: BootPayload, mount: HTMLElement): void {
  injectStyle();
  mount.classList.add(ROOT_CLASS);
  mount.innerHTML = '';

  const root = document.createElement('div');
  root.className = `${ROOT_CLASS}-root`;
  mount.appendChild(root);

  // The session's known metrics, refreshed in place after every create/update/
  // delete (see `applyMetricsList` below) — everything that used to read the
  // static `boot.metrics` now reads this instead.
  let metricsList: BootMetric[] = boot.metrics;

  // Alert-channel/profile names for the metric Builder's pickers (older
  // payloads may omit it — the editor degrades to free-text inputs).
  const formMeta: FormMeta = boot.form_meta ?? { channels: [], profiles: [], default_profile: null };

  const state: State = {
    windowPreset: boot.initial_window || '30d',
    metrics: metricsList.map(buildPendingRow),
    jobs: [],
    followedJobId: null,
    followOffset: 0,
    tagFilter: null,
    sort: { key: 'alerts', dir: DEFAULT_SORT_DIR.alerts },
    nextSteps: null,
  };

  let detailHandle: DetailHandle | null = null;
  // The metric the detail overlay is currently open on — so a clean that
  // finishes after the user closed and re-opened the overlay reloads the LIVE
  // one, not a detached iframe captured when the clean started.
  let detailMetric: string | null = null;
  let editorHandle: MetricEditorHandle | null = null;
  let jobsPollHandle: number | undefined;
  let jobDetailHandle: number | undefined;

  // ---- select-field options (metric names + tag:x), from the known list -----
  // (name/tags are known up front — no need to wait on any per-metric fetch)
  function selectOptions(): string[] {
    const names = new Set<string>();
    const tags = new Set<string>();
    for (const m of metricsList) {
      names.add(m.name);
      for (const t of m.tags) tags.add(t);
    }
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

  // The toolbar is pinned to the top via CSS `position:sticky`; toggle a
  // `.stuck` class so its divider + shadow appear only once it's actually
  // pinned (not at rest at the very top). The document is the scroll container.
  const onScroll = (): void => {
    header.classList.toggle('stuck', window.scrollY > 4);
  };
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();

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
      void loadOverview();
    };
    seg.appendChild(btn);
  }
  headerRight.appendChild(seg);

  const refreshBtn = document.createElement('button');
  refreshBtn.type = 'button';
  refreshBtn.className = 'dtk-ui-iconbtn';
  refreshBtn.title = 'Refresh overview';
  refreshBtn.textContent = '⟳';
  refreshBtn.onclick = (): void => void loadOverview();
  headerRight.appendChild(refreshBtn);

  const runPipelineBtn = document.createElement('button');
  runPipelineBtn.type = 'button';
  runPipelineBtn.className = 'dtk-ui-runbtn';
  runPipelineBtn.textContent = 'Run pipeline';
  runPipelineBtn.onclick = (): void => openRunPanel();
  headerRight.appendChild(runPipelineBtn);

  const newMetricBtn = document.createElement('button');
  newMetricBtn.type = 'button';
  newMetricBtn.className = 'dtk-ui-newbtn';
  newMetricBtn.textContent = 'New metric';
  newMetricBtn.onclick = (): void => openMetricEditorCreate();
  headerRight.appendChild(newMetricBtn);

  // Small "n/N" progress chip — visible only while the incremental per-metric
  // stats load is in flight, hidden the instant it completes.
  const progressChip = document.createElement('span');
  progressChip.className = 'dtk-ui-progresschip';
  progressChip.style.display = 'none';
  headerRight.appendChild(progressChip);

  function setLoadProgress(loaded: number, total: number): void {
    if (total === 0 || loaded >= total) {
      progressChip.style.display = 'none';
      return;
    }
    progressChip.textContent = `${loaded}/${total}`;
    progressChip.style.display = '';
  }

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

  // ---- next-steps strip (post-create guided flow), between header and content --
  const nextStepsBox = document.createElement('div');
  nextStepsBox.className = 'dtk-ui-nextsteps-box';
  root.appendChild(nextStepsBox);

  function paintNextSteps(): void {
    renderNextSteps(nextStepsBox, state.nextSteps, {
      onLoad: (metric) => void submitNextStepsLoad(metric),
      onTune: (metric) => void submitTune(metric),
      onFollow: (jobId) => followJob(jobId),
      onDismiss: (): void => {
        state.nextSteps = null;
        paintNextSteps();
      },
    });
  }

  /** Spawn `run --steps load,detect` for the freshly created metric (never alert). */
  async function submitNextStepsLoad(metric: string): Promise<void> {
    if (pipelineSubmitPending) return;
    pipelineSubmitPending = true;
    try {
      const res = await postRun({
        select: metric,
        steps: ['load', 'detect'],
        from: null,
        to: null,
        full_refresh: false,
        force: false,
      });
      trackSpawnedJob('run', `run --select ${metric}`, res.job_id, null);
      if (state.nextSteps && state.nextSteps.metric === metric) {
        state.nextSteps = { metric, jobId: res.job_id, phase: 'running' };
        paintNextSteps();
      }
    } catch (e) {
      toast(root, 'error', (e as Error).message);
    } finally {
      pipelineSubmitPending = false;
    }
  }

  /** Reflect the tracked load job's outcome into the strip on every jobs tick. */
  function syncNextStepsFromJobs(): void {
    const st = state.nextSteps;
    if (!st || !st.jobId || st.phase !== 'running') return;
    const job = state.jobs.find((j) => j.id === st.jobId);
    if (!job || job.status === 'running') return;
    state.nextSteps = { ...st, phase: job.status === 'done' ? 'done' : 'failed' };
    paintNextSteps();
  }

  // ---- content (tiles / tags / table), rebuilt on every state change --------
  const content = document.createElement('div');
  content.className = 'dtk-ui-content';
  root.appendChild(content);

  function renderContent(): void {
    content.innerHTML = '';

    const total = metricsList.length;
    if (total === 0) {
      const empty = document.createElement('div');
      empty.className = 'dtk-ui-empty';
      empty.textContent = 'No metrics found for this project/selector.';
      content.appendChild(empty);
      return;
    }

    const landed = state.metrics.filter((m) => !m.pending);
    const failed = landed.filter((m) => m.error !== null);
    // Every metric fetched, and every single one failed — the closest thing
    // left to the old monolithic "failed to load overview" case (a per-metric
    // failure alone just red-flags that one row and never blocks the rest).
    if (landed.length === total && failed.length === total) {
      const banner = document.createElement('div');
      banner.className = 'dtk-ui-banner';
      const detail = failed[0]?.error ?? 'unknown error';
      banner.innerHTML = `<span>Failed to load overview: every metric failed (${esc(detail)}).</span>`;
      const retry = document.createElement('button');
      retry.type = 'button';
      retry.className = 'dtk-ui-banner-retry';
      retry.textContent = 'Retry';
      retry.onclick = (): void => void loadOverview();
      banner.appendChild(retry);
      content.appendChild(banner);
    }

    // Tiles get every row (the metrics enabled/total count is config-derived
    // and correct immediately; buildTiles skips pending rows for the stat
    // aggregates itself); the tag rollup reflects only landed rows.
    content.appendChild(buildTiles(state.metrics));
    content.appendChild(
      buildTags(landed, state.tagFilter, (tag) => {
        state.tagFilter = tag;
        renderContent();
      }),
    );

    const filtered =
      state.tagFilter === null
        ? state.metrics
        : state.metrics.filter((m) =>
            state.tagFilter === UNTAGGED ? m.tags.length === 0 : m.tags.includes(state.tagFilter as string),
          );

    const tableResult = buildMetricsTable(filtered, state.sort, Date.now(), {
      onOpen: openDetail,
      onTune: (name) => void submitTune(name),
      onRun: (name) => openRunPanel(name),
      onEdit: (name) => void openMetricEditorEdit(name),
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
    if (!closeEditorIfAllowed()) return; // dirty editor: user chose to keep editing
    if (detailHandle) detailHandle.close();
    detailMetric = name;
    detailHandle = openDetailOverlay(root, name, state.windowPreset, {
      onTune: (n) => void submitTune(n),
      onClose: () => {
        detailHandle = null;
        detailMetric = null;
      },
      onCleanPreview: (n) => cleanPreview(n),
      onCleanExecute: (n) => cleanExecute(n),
    });
  }

  // ---- metric editor overlay (create / edit / delete) -------------------------
  /**
   * Confirm-guarded close of any open editor. Returns false when the user
   * chose to keep their unsaved edits — navigation to another overlay must
   * abort then, so a programmatic close can never silently discard a dirty
   * editor (Esc/backdrop/✕ already prompt inside the editor itself).
   */
  function closeEditorIfAllowed(): boolean {
    if (!editorHandle) return true;
    return editorHandle.requestClose(); // its onClose nulls editorHandle
  }

  function openMetricEditorCreate(): void {
    if (!closeEditorIfAllowed()) return;
    if (detailHandle) {
      detailHandle.close();
      detailHandle = null;
    }
    editorHandle = openMetricEditor(
      root,
      { mode: 'create', text: NEW_METRIC_TEMPLATE, meta: formMeta },
      {
        onSaved: (res, mode) => onEditorSaved(res, mode),
        onDeleted: () => {}, // unreachable in create mode (no delete button)
        onClose: () => {
          editorHandle = null;
        },
      },
    );
  }

  async function openMetricEditorEdit(name: string): Promise<void> {
    // Resolve the dirty-editor question BEFORE the fetch: if the user keeps
    // their edits nothing is fetched, and an overlay opened while the fetch
    // was in flight can't be silently closed by its resolution below.
    if (!closeEditorIfAllowed()) return;
    let src;
    try {
      src = await fetchMetricSource(name);
    } catch (e) {
      toast(root, 'error', (e as Error).message);
      return;
    }
    if (!closeEditorIfAllowed()) return; // an editor opened during the fetch wins
    if (detailHandle) {
      detailHandle.close();
      detailHandle = null;
    }
    editorHandle = openMetricEditor(
      root,
      {
        mode: 'edit',
        name: src.name,
        file: src.file,
        text: src.text,
        digest: src.digest,
        data: src.data ?? null,
        parseError: src.parse_error ?? null,
        meta: formMeta,
      },
      {
        onSaved: (res, mode) => onEditorSaved(res, mode),
        onDeleted: (res) => onEditorDeleted(res),
        onClose: () => {
          editorHandle = null;
        },
      },
    );
  }

  function onEditorSaved(res: MetricMutationResponse, mode: EditorMode): void {
    toast(root, 'info', `Metric '${res.name}' ${mode === 'create' ? 'created' : 'saved'}.`);
    if (res.note) toast(root, 'info', res.note);
    if (mode === 'create') {
      // Kick off the guided tail of the flow: load real data, then tune on it.
      state.nextSteps = { metric: res.name, jobId: null, phase: 'idle' };
      paintNextSteps();
    }
    // A plain edit changes at most its own row — refresh just that one instead
    // of flashing the whole table back to pending and re-fetching every
    // metric's stats. Create/rename/delete change the list's shape, so they
    // keep the full reload.
    if (mode === 'edit' && !res.renamed_from) {
      refreshMetricRow(res.name, res.metrics);
    } else {
      applyMetricsList(res.metrics);
    }
  }

  function onEditorDeleted(res: MetricMutationResponse): void {
    toast(root, 'info', `Metric '${res.name}' deleted (archived).`);
    if (res.note) toast(root, 'info', res.note);
    applyMetricsList(res.metrics);
  }

  /** Re-sync the session metric list after a create/update/delete, then reload. */
  function applyMetricsList(entries: BootMetric[]): void {
    metricsList = entries;
    runPanel.refreshOptions();
    void loadOverview();
  }

  /**
   * Refresh a single row after an in-place edit: adopt the refreshed session
   * list (interval/tags/enabled may have changed), set just that row pending,
   * and re-fetch its stats. Any full reload that starts meanwhile (window
   * change, manual refresh) supersedes this via the shared generation counter.
   */
  function refreshMetricRow(name: string, entries: BootMetric[]): void {
    metricsList = entries;
    runPanel.refreshOptions();
    const bm = entries.find((m) => m.name === name);
    const idx = state.metrics.findIndex((m) => m.name === name);
    if (!bm || idx === -1) {
      void loadOverview(); // row not present — fall back to the full reload
      return;
    }
    const generation = loadGeneration;
    state.metrics[idx] = buildPendingRow(bm);
    renderContent();
    fetchMetricStats(name, state.windowPreset)
      .then((row) => {
        if (generation !== loadGeneration) return; // superseded by a full reload
        row.pending = false;
        const i = state.metrics.findIndex((m) => m.name === name);
        if (i !== -1) state.metrics[i] = row;
        renderContent();
      })
      .catch((e: Error) => {
        if (generation !== loadGeneration) return;
        const i = state.metrics.findIndex((m) => m.name === name);
        if (i !== -1) state.metrics[i] = { ...buildPendingRow(bm), pending: false, error: e.message };
        renderContent();
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

  /**
   * The confirm-strip seed for the detail overlay's "Clean stale" action.
   * Resolves `null` (after toasting why) when there is nothing to confirm:
   * nothing stale, a pipeline job already running, or a fetch error.
   */
  async function cleanPreview(metric: string): Promise<CleanPreviewResponse | null> {
    const busy = pipelineBusy();
    if (busy.busy) {
      toast(root, 'error', busy.reason);
      return null;
    }
    try {
      const p = await fetchCleanPreview(metric);
      if (p.stale_detectors.length === 0 && p.stale_alert_states.length === 0) {
        toast(root, 'info', `Nothing stale for '${metric}' — stored data matches the current config.`);
        return null;
      }
      return p;
    } catch (e) {
      toast(root, 'error', (e as Error).message);
      return null;
    }
  }

  /** Poll a freshly spawned job until it leaves 'running'; true = exit 0. */
  async function waitForJob(jobId: string, timeoutMs = 300_000): Promise<boolean> {
    const deadline = Date.now() + timeoutMs;
    for (;;) {
      let detail;
      try {
        detail = await fetchJobDetail(jobId, 0);
      } catch {
        // A transient poll failure must not read as job failure — the job may
        // well succeed. Keep retrying until the deadline.
        if (Date.now() >= deadline) {
          throw new Error('lost track of the job — follow it in the jobs drawer');
        }
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        continue;
      }
      if (detail.status !== 'running') return detail.status === 'done';
      if (Date.now() >= deadline) {
        throw new Error('the job is still running — follow it in the jobs drawer');
      }
      await new Promise((resolve) => window.setTimeout(resolve, 1000));
    }
  }

  /**
   * Spawn `dtk clean --select <metric> --execute` and wait for it (the delete
   * is seconds, not a pipeline run) so the detail overlay can reload its
   * report right after; the row's stats re-fetch drops the stale chip.
   */
  async function cleanExecute(metric: string): Promise<boolean> {
    if (pipelineSubmitPending) return false;
    pipelineSubmitPending = true;
    let jobId: string;
    try {
      const res = await postClean({ metric });
      jobId = res.job_id;
      trackSpawnedJob('clean', `clean --select ${metric}`, jobId, null);
    } catch (e) {
      toast(root, 'error', (e as Error).message);
      return false;
    } finally {
      pipelineSubmitPending = false;
    }
    try {
      const ok = await waitForJob(jobId);
      if (ok) {
        toast(root, 'info', `Stale data for '${metric}' removed.`);
        // Reload the LIVE detail overlay (if still open for this metric, even
        // after a close/re-open) so only current-config series remain, and
        // refresh the row so its stale chip clears.
        if (detailHandle && detailMetric === metric) detailHandle.reload();
        refreshMetricRow(metric, metricsList);
      } else {
        toast(root, 'error', `clean --select ${metric} failed — see the jobs drawer for the log.`);
      }
      void refreshJobs();
      return ok;
    } catch (e) {
      toast(root, 'error', (e as Error).message);
      return false;
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
    syncNextStepsFromJobs();
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

  // ---- overview load: incremental, per-metric --------------------------------
  //
  // The page used to fetch one monolithic `/api/overview` covering every
  // metric's stats in a single request; on a production-sized project that
  // read is serialized on one DB connection and can take minutes, long
  // enough for the browser to abort it — an endless "Loading overview…"
  // followed by "Failed to fetch". Instead: render every row immediately as
  // `pending` (boot metadata is enough for name/dir/file/tags/interval/
  // enabled), then fetch each metric's stats individually through a small
  // concurrency pool, patching rows in place as they land so the table, tiles
  // and tag rollup all fill in progressively instead of blocking on the
  // slowest metric.
  //
  // A `generation` counter guards against a window change or manual refresh
  // racing an in-flight load: every call bumps it, and any pool worker whose
  // captured generation no longer matches the live one silently stops (its
  // in-flight response is applied nowhere).
  let loadGeneration = 0;

  async function loadOverview(): Promise<void> {
    const generation = ++loadGeneration;
    const windowPreset = state.windowPreset;
    // Snapshot the current metric list — `metricsList` is only ever reassigned
    // wholesale (via `applyMetricsList`, which itself calls `loadOverview`
    // again with a fresh generation), so one invocation stays consistent.
    const metrics = metricsList;

    state.metrics = metrics.map(buildPendingRow);
    refreshBtn.classList.add('spinning');
    setLoadProgress(0, metrics.length);
    renderContent();

    if (metrics.length === 0) {
      refreshBtn.classList.remove('spinning');
      setLoadProgress(0, 0);
      return;
    }

    const queue = [...metrics];
    let landedCount = 0;

    async function worker(): Promise<void> {
      for (;;) {
        if (generation !== loadGeneration) return; // superseded — stop pulling work
        const bm = queue.shift();
        if (!bm) return;
        let row: OverviewMetric;
        try {
          row = await fetchMetricStats(bm.name, windowPreset);
          row.pending = false;
        } catch (e) {
          // A failed per-metric fetch degrades to that one row's error
          // treatment (table.ts renders the red glyph + tooltip) and never
          // blocks the rest of the pool.
          row = { ...buildPendingRow(bm), pending: false, error: (e as Error).message };
        }
        if (generation !== loadGeneration) return; // this load was superseded meanwhile
        const idx = state.metrics.findIndex((m) => m.name === bm.name);
        if (idx !== -1) state.metrics[idx] = row;
        landedCount++;
        setLoadProgress(landedCount, metrics.length);
        renderContent();
      }
    }

    const workerCount = Math.min(STATS_CONCURRENCY, metrics.length);
    await Promise.all(Array.from({ length: workerCount }, () => worker()));

    if (generation === loadGeneration) {
      refreshBtn.classList.remove('spinning');
      setLoadProgress(landedCount, metrics.length);
      runPanel.refreshOptions();
    }
  }

  // ---- boot ---------------------------------------------------------------
  renderContent();
  runPanel.refreshOptions();
  void loadOverview();
  void refreshJobs();
}

(window as unknown as { __DTK_UI__: DtkUiGlobal }).__DTK_UI__ = { render };
