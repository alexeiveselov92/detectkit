// Styling for the `dtk ui` cockpit — a single injected <style data-dtk-ui>,
// scoped under the ROOT_CLASS ('dtk-ui') exactly like report.ts / tune.ts.
//
// Dark terminal aesthetic (unlike the light-paper report/tune pages): this is
// an always-on ops surface, so the whole page — not just the chart panel —
// uses the --term-* palette. Status reads from color alone and color comes
// ONLY from the --st-* tokens (freshness dots, job status, quality warnings);
// everything else (chrome, borders, accents) uses the neutral/clay tokens.

export const ROOT_CLASS = 'dtk-ui';

let styleInjected = false;

export function injectStyle(): void {
  if (styleInjected) return;
  styleInjected = true;
  const css = `
.${ROOT_CLASS}{
  --clay:#d15b36;--clay-700:#b4471f;--ink:#1b1916;--paper:#f5f1e8;
  --muted:#6e675b;--faint:#9a9384;
  --term-bg:#211e1a;--term-border:#332f29;--term-text:#c9c2b4;
  --st-anomaly:#d63232;--st-recovery:#36a64f;--st-nodata:#f0ad4e;--st-error:#5a7a8c;
  --accent-green:#2e9e73;
  --sans:'Schibsted Grotesk',ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
  --mono:'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  /* dark-terminal local surfaces, derived from the term-* palette above */
  --bg:var(--term-bg);--surface:#2a2620;--surface-2:#332e26;--border:var(--term-border);
  --text:var(--term-text);--text-strong:var(--paper);
  display:block;min-height:100vh;background:var(--bg);color:var(--text);
  font-family:var(--sans);position:relative;
}
.${ROOT_CLASS} *{box-sizing:border-box;}
.${ROOT_CLASS} a{color:var(--clay);}
.${ROOT_CLASS}-root{max-width:1400px;margin:0 auto;padding:16px 20px 56px;display:flex;
  flex-direction:column;gap:16px;}
.dtk-ui-content{display:flex;flex-direction:column;gap:16px;}

/* --- header (sticky toolbar) --------------------------------------------------
   Pins the brand + window/run/new/jobs toolbar to the top of the viewport so it
   stays reachable while scrolling the metrics table. The document is the scroll
   container (no ancestor sets overflow), so top:0 pins to the viewport; the
   background matches the page so content scrolls cleanly beneath it. The
   negative top margin cancels the root's top padding (pins flush, same resting
   position as before) and the negative bottom margin cancels the root's flex
   gap, so no page-bg strip shows between the bar and the content sliding under
   it. The divider + shadow appear only once actually stuck (.stuck, toggled
   from ui.ts on scroll), so the bar looks unchanged at rest. */
.dtk-ui-header{position:sticky;top:0;z-index:30;background:var(--bg);
  display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap;
  padding:14px 0;margin:-14px 0 -16px;border-bottom:1px solid transparent;
  transition:box-shadow 0.18s ease,border-color 0.18s ease;}
.dtk-ui-header.stuck{border-bottom-color:var(--border);
  box-shadow:0 10px 24px -18px rgba(0,0,0,0.8);}
.dtk-ui-brand{display:flex;align-items:center;gap:9px;}
.dtk-ui-brand-dot{width:11px;height:11px;border-radius:3px;background:var(--clay);flex:0 0 auto;}
.dtk-ui-brand-name{font-family:var(--mono);font-size:14px;color:var(--text-strong);
  letter-spacing:-0.01em;}
.dtk-ui-brand-name b{font-weight:700;}
.dtk-ui-header-right{display:flex;align-items:center;gap:10px;flex-wrap:wrap;}
.dtk-ui-seg{display:flex;gap:3px;background:var(--surface);border:1px solid var(--border);
  border-radius:8px;padding:3px;}
.dtk-ui-seg-btn{border:0;background:transparent;color:var(--faint);font-family:var(--mono);
  font-size:11.5px;padding:5px 10px;border-radius:6px;cursor:pointer;white-space:nowrap;}
.dtk-ui-seg-btn:hover{color:var(--text);}
.dtk-ui-seg-btn.on{background:var(--clay);color:#fff;font-weight:600;}
.dtk-ui-iconbtn{border:1px solid var(--border);background:var(--surface);color:var(--text);
  border-radius:8px;width:32px;height:32px;display:inline-flex;align-items:center;
  justify-content:center;cursor:pointer;font-size:14px;line-height:1;}
.dtk-ui-iconbtn:hover{border-color:var(--clay);color:#fff;background:var(--clay-700);}
.dtk-ui-iconbtn.spinning{animation:dtk-ui-spin 0.8s linear infinite;}
@keyframes dtk-ui-spin{to{transform:rotate(360deg);}}
.dtk-ui-runbtn{border:0;background:var(--clay);color:#fff;font-family:var(--sans);
  font-size:13px;font-weight:600;padding:8px 15px;border-radius:8px;cursor:pointer;}
.dtk-ui-runbtn:hover{background:var(--clay-700);}
.dtk-ui-newbtn{border:1px solid var(--clay);background:transparent;color:var(--clay);
  font-family:var(--sans);font-size:13px;font-weight:600;padding:8px 15px;border-radius:8px;
  cursor:pointer;}
.dtk-ui-newbtn:hover{background:rgba(209,91,54,0.12);}
.dtk-ui-jobschip{display:inline-flex;align-items:center;gap:7px;border:1px solid var(--border);
  background:var(--surface);color:var(--faint);font-family:var(--mono);font-size:11.5px;
  padding:6px 12px;border-radius:999px;cursor:pointer;white-space:nowrap;}
.dtk-ui-jobschip:hover{border-color:var(--clay);}
.dtk-ui-jobschip-dot{width:7px;height:7px;border-radius:50%;background:var(--faint);flex:0 0 auto;}
.dtk-ui-jobschip.running .dtk-ui-jobschip-dot{background:var(--clay);
  animation:dtk-ui-pulse 1.2s ease-in-out infinite;}
.dtk-ui-jobschip.running{color:var(--text);border-color:var(--clay);}
@keyframes dtk-ui-pulse{0%,100%{opacity:1;}50%{opacity:0.35;}}
.dtk-ui-progresschip{font-family:var(--mono);font-size:11.5px;color:var(--faint);
  white-space:nowrap;}

/* --- banner / empty ------------------------------------------------------ */
.dtk-ui-banner{display:flex;align-items:center;justify-content:space-between;gap:12px;
  background:rgba(214,50,50,0.1);border:1px solid rgba(214,50,50,0.4);border-radius:10px;
  padding:11px 14px;color:var(--text);font-size:13px;}
.dtk-ui-banner-retry{border:1px solid var(--st-anomaly);background:transparent;color:var(--st-anomaly);
  border-radius:7px;padding:6px 13px;font-family:var(--sans);font-size:12.5px;cursor:pointer;
  flex:0 0 auto;}
.dtk-ui-banner-retry:hover{background:rgba(214,50,50,0.15);}
.dtk-ui-empty{padding:60px 20px;text-align:center;color:var(--faint);font-size:14px;}

/* --- stat tiles ----------------------------------------------------------- */
.dtk-ui-tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;}
.dtk-ui-tile{background:var(--surface);border:1px solid var(--border);border-radius:10px;
  padding:12px 14px;display:flex;flex-direction:column;gap:3px;}
.dtk-ui-tile-val{font-family:var(--mono);font-size:23px;font-weight:700;color:var(--text-strong);
  line-height:1.1;}
.dtk-ui-tile-label{font-family:var(--mono);font-size:10.5px;color:var(--faint);
  text-transform:uppercase;letter-spacing:0.06em;}
.dtk-ui-tile-sub{font-size:11.5px;color:var(--muted);font-family:var(--mono);}
.dtk-ui-tile-sub.warn{color:var(--st-nodata);font-weight:600;}
.dtk-ui-tile.err .dtk-ui-tile-val{color:var(--st-anomaly);}

/* --- tag rollup strip ------------------------------------------------------ */
.dtk-ui-tags{display:flex;flex-wrap:wrap;gap:7px;}
.dtk-ui-tag{display:inline-flex;align-items:center;gap:6px;padding:5px 11px;background:var(--surface);
  border:1px solid var(--border);border-radius:999px;font-size:11.5px;color:var(--muted);
  cursor:pointer;font-family:var(--mono);}
.dtk-ui-tag:hover{border-color:var(--clay);color:var(--text);}
.dtk-ui-tag.on{background:var(--clay);border-color:var(--clay);color:#fff;}
.dtk-ui-tag-name{font-weight:600;}
.dtk-ui-tag.on .dtk-ui-tag-name{color:#fff;}
.dtk-ui-tag-n{color:var(--text);}
.dtk-ui-tag.on .dtk-ui-tag-n,.dtk-ui-tag.on .dtk-ui-tag-sub{color:rgba(255,255,255,0.85);}
.dtk-ui-tag-sub{color:var(--faint);}

/* --- metrics table --------------------------------------------------------- */
.dtk-ui-table-wrap{background:var(--surface);border:1px solid var(--border);border-radius:12px;
  overflow:hidden;overflow-x:auto;}
.dtk-ui-group + .dtk-ui-group{border-top:1px solid var(--border);}
.dtk-ui-group-head{display:flex;align-items:baseline;justify-content:space-between;gap:10px;
  padding:9px 14px;background:var(--surface-2);}
.dtk-ui-group-name{font-family:var(--mono);font-size:11.5px;color:var(--text);font-weight:600;}
.dtk-ui-group-sub{font-family:var(--mono);font-size:11px;color:var(--faint);}
/* table-layout:fixed + the <colgroup> in table.ts pin every column to the same
   width in every group, so the blocks line up regardless of each block's
   longest metric name; min-width keeps the columns usable on a narrow viewport
   (the wrap scrolls horizontally instead of squeezing the Name column to zero). */
.dtk-ui-table{width:100%;min-width:1040px;table-layout:fixed;border-collapse:collapse;
  font-size:12.5px;}
.dtk-ui-table thead th{text-align:left;padding:8px 12px;font-family:var(--mono);font-size:10.5px;
  color:var(--faint);text-transform:uppercase;letter-spacing:0.05em;font-weight:600;
  border-bottom:1px solid var(--border);white-space:nowrap;}
.dtk-ui-th{cursor:pointer;user-select:none;}
.dtk-ui-th:hover{color:var(--text);}
.dtk-ui-th-arrow{margin-left:5px;color:var(--clay);}
.dtk-ui-table td{padding:7px 12px;border-bottom:1px solid var(--border);vertical-align:middle;
  color:var(--text);}
.dtk-ui-row:last-child td{border-bottom:0;}
.dtk-ui-row:hover{background:var(--surface-2);}
.dtk-ui-row.disabled{opacity:0.5;}
.dtk-ui-row.errored{background:rgba(214,50,50,0.05);}
.dtk-ui-row.pending{opacity:0.7;}
.dtk-ui-pending{font-family:var(--mono);color:var(--faint);}
.dtk-ui-dotcell{width:14px;}
.dtk-ui-dot{width:9px;height:9px;border-radius:50%;display:inline-block;cursor:help;}
/* Name is the one flexible column (no <col> width) — bound its content so a
   long snake_case identifier wraps inside the cell instead of widening the
   column and shoving the action buttons off the right edge. */
.dtk-ui-namecell{overflow-wrap:anywhere;}
.dtk-ui-name{font-weight:600;color:var(--text-strong);}
.dtk-ui-err-badge{color:var(--st-anomaly);margin-left:6px;cursor:help;font-weight:700;}
.dtk-ui-stalechip{font-family:var(--mono);font-size:9.5px;color:var(--st-nodata);
  border:1px solid var(--st-nodata);border-radius:5px;padding:1px 5px;margin-left:6px;
  cursor:help;white-space:nowrap;vertical-align:1px;}
.dtk-ui-tagchips{display:flex;flex-wrap:wrap;gap:4px;margin-top:2px;}
.dtk-ui-tagchip{font-family:var(--mono);font-size:9.5px;color:var(--faint);
  background:var(--surface-2);border:1px solid var(--border);border-radius:5px;padding:1px 5px;}
.dtk-ui-interval{font-family:var(--mono);color:var(--muted);white-space:nowrap;}
.dtk-ui-sparkcell{width:150px;}
.dtk-ui-spark-empty{font-family:var(--mono);font-size:10.5px;color:var(--faint);font-style:italic;}
.dtk-ui-spark-loading{font-family:var(--mono);font-size:10.5px;color:var(--faint);font-style:italic;
  animation:dtk-ui-pulse 1.2s ease-in-out infinite;}
.dtk-ui-alertscell{white-space:nowrap;}
.dtk-ui-alerts-n{font-family:var(--mono);color:var(--text);}
.dtk-ui-alerts-n.hasany{font-weight:700;color:var(--text-strong);}
.dtk-ui-alerts-n.overbudget{color:var(--st-anomaly);}
.dtk-ui-alerts-sub{font-family:var(--mono);font-size:10.5px;color:var(--faint);margin-left:5px;}
.dtk-ui-lastalert{font-family:var(--mono);font-size:11.5px;color:var(--muted);white-space:nowrap;}
.dtk-ui-rate{font-family:var(--mono);color:var(--text);white-space:nowrap;}
.dtk-ui-quality{white-space:nowrap;cursor:help;}
.dtk-ui-quality-chip{font-family:var(--mono);font-size:11px;color:var(--muted);}
.dtk-ui-quality-chip b{color:var(--text);font-weight:600;}
.dtk-ui-quality.empty{color:var(--faint);}
.dtk-ui-lock{font-family:var(--mono);font-size:9px;letter-spacing:0.04em;color:var(--st-nodata);
  border:1px solid var(--st-nodata);border-radius:4px;padding:1px 5px;cursor:help;}
.dtk-ui-actionscell{white-space:nowrap;text-align:right;}
.dtk-ui-actionbtn{border:1px solid var(--border);background:transparent;color:var(--muted);
  font-family:var(--sans);font-size:11px;padding:4px 9px;border-radius:6px;cursor:pointer;
  margin-left:5px;}
.dtk-ui-actionbtn:hover{border-color:var(--clay);color:var(--text);}

/* --- detail overlay --------------------------------------------------------- */
.dtk-ui-overlay{position:fixed;inset:0;background:rgba(10,9,7,0.72);z-index:50;display:flex;
  align-items:center;justify-content:center;padding:24px;}
.dtk-ui-overlay-modal{width:100%;height:100%;max-width:1500px;background:var(--surface);
  border:1px solid var(--border);border-radius:12px;display:flex;flex-direction:column;
  overflow:hidden;box-shadow:0 30px 80px -20px rgba(0,0,0,0.6);}
.dtk-ui-overlay-head{display:flex;align-items:center;justify-content:space-between;gap:12px;
  padding:11px 16px;border-bottom:1px solid var(--border);background:var(--surface-2);flex:0 0 auto;}
.dtk-ui-overlay-title{font-family:var(--mono);font-size:13.5px;color:var(--text-strong);
  font-weight:700;}
.dtk-ui-overlay-sub{font-family:var(--mono);font-size:11px;color:var(--faint);margin-left:8px;}
.dtk-ui-overlay-actions{display:flex;align-items:center;gap:8px;}
.dtk-ui-overlay-close{border:1px solid var(--border);background:transparent;color:var(--muted);
  border-radius:7px;width:30px;height:30px;cursor:pointer;font-size:14px;}
.dtk-ui-overlay-close:hover{border-color:var(--st-anomaly);color:var(--st-anomaly);}
/* confirm strip for the detail overlay's "Clean stale" action — sits between
   the overlay head and the report iframe, amber like the other warning surfaces */
.dtk-ui-cleanstrip{display:flex;align-items:center;justify-content:space-between;gap:12px;
  flex-wrap:wrap;padding:10px 16px;border-bottom:1px solid var(--border);
  background:rgba(240,173,78,0.08);flex:0 0 auto;}
.dtk-ui-cleanstrip-text{font-size:12.5px;color:var(--text);max-width:900px;}
.dtk-ui-cleanstrip-text b{color:var(--st-nodata);}
.dtk-ui-cleanstrip-warn{color:var(--st-nodata);font-size:11.5px;margin-top:3px;}
.dtk-ui-cleanstrip-actions{display:flex;align-items:center;gap:8px;flex:0 0 auto;}
.dtk-ui-cleanstrip .dtk-ui-btn{flex:0 0 auto;padding:6px 12px;font-size:12px;}
.dtk-ui-overlay-body{flex:1;min-height:0;position:relative;background:var(--term-bg);}
.dtk-ui-overlay-body iframe{width:100%;height:100%;border:0;display:block;background:#fff;}
.dtk-ui-overlay-loading{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
  gap:10px;color:var(--term-text);font-family:var(--mono);font-size:13px;}
.dtk-ui-overlay-loading b{color:var(--clay);font-weight:600;}
.dtk-ui-overlay-spinner{width:14px;height:14px;border-radius:50%;border:2px solid var(--term-border);
  border-top-color:var(--clay);animation:dtk-ui-spin 0.8s linear infinite;flex:none;}
@keyframes dtk-ui-spin{to{transform:rotate(360deg);}}

/* --- metric editor overlay ---------------------------------------------------
   Reuses .dtk-ui-overlay (backdrop) / .dtk-ui-overlay-modal (sizing/chrome) from
   the detail overlay above; everything inside gets its own dtk-ui-editor-*
   classes since the body is a form + textarea rather than a report iframe. */
.dtk-ui-overlay-modal.dtk-ui-editor-modal{max-width:1360px;}
.dtk-ui-editor-panes{flex:1;min-height:0;display:flex;flex-direction:column;}
.dtk-ui-editor-panes > .dtk-ui-form{flex:1;min-height:0;}
.dtk-ui-editor-note{font-size:11px;color:var(--faint);font-style:italic;flex:0 0 auto;}
.dtk-ui-editor-head{display:flex;align-items:center;justify-content:space-between;gap:12px;
  padding:11px 16px;border-bottom:1px solid var(--border);background:var(--surface-2);flex:0 0 auto;}
.dtk-ui-editor-titlewrap{display:flex;align-items:baseline;gap:9px;flex-wrap:wrap;min-width:0;}
.dtk-ui-editor-title{font-family:var(--mono);font-size:13.5px;color:var(--text-strong);
  font-weight:700;white-space:nowrap;}
.dtk-ui-editor-sub{font-family:var(--mono);font-size:11px;color:var(--faint);}
.dtk-ui-editor-body{flex:1;min-height:0;display:flex;flex-direction:column;gap:10px;
  padding:14px 16px;overflow-y:auto;background:var(--surface);}
.dtk-ui-editor-field{display:flex;flex-direction:column;gap:5px;flex:0 0 auto;}
.dtk-ui-editor-hint{font-size:11px;color:var(--faint);}
.dtk-ui-editor-textarea{flex:1;min-height:320px;background:var(--term-bg);color:var(--term-text);
  border:1px solid var(--term-border);border-radius:9px;padding:12px 14px;font-family:var(--mono);
  font-size:12.5px;line-height:1.55;resize:none;tab-size:2;white-space:pre;overflow:auto;}
.dtk-ui-editor-textarea:focus{outline:none;border-color:var(--clay);}
.dtk-ui-editor-error{flex:0 0 auto;margin:0 16px 12px;padding:10px 12px;
  background:rgba(214,50,50,0.1);border:1px solid rgba(214,50,50,0.4);border-radius:9px;
  color:var(--text);font-family:var(--mono);font-size:12px;white-space:pre-wrap;
  word-break:break-word;max-height:160px;overflow-y:auto;}
.dtk-ui-editor-foot{display:flex;align-items:center;justify-content:space-between;gap:12px;
  padding:12px 16px;border-top:1px solid var(--border);background:var(--surface-2);
  flex:0 0 auto;flex-wrap:wrap;}
.dtk-ui-editor-foot-left{display:flex;align-items:center;gap:10px;flex-wrap:wrap;min-width:0;}
.dtk-ui-editor-foot-right{display:flex;align-items:center;gap:10px;flex:0 0 auto;margin-left:auto;}
.dtk-ui-editor-confirm{display:flex;align-items:center;gap:10px;flex-wrap:wrap;}
.dtk-ui-editor-confirm-text{font-size:12px;color:var(--text);max-width:460px;}
.dtk-ui-editor-confirm-text b{color:var(--st-anomaly);}
.dtk-ui-editor-confirm-text code{font-family:var(--mono);font-size:11px;background:var(--surface);
  border:1px solid var(--border);border-radius:4px;padding:1px 5px;}

/* --- drawers (run panel + jobs) --------------------------------------------- */
.dtk-ui-drawer-backdrop{position:fixed;inset:0;background:rgba(10,9,7,0.5);z-index:40;display:none;}
.dtk-ui-drawer-backdrop.open{display:block;}
.dtk-ui-drawer{position:fixed;top:0;right:0;bottom:0;width:min(440px,100vw);background:var(--surface);
  border-left:1px solid var(--border);z-index:41;display:none;flex-direction:column;
  box-shadow:-20px 0 50px -20px rgba(0,0,0,0.6);}
.dtk-ui-drawer.open{display:flex;}
.dtk-ui-drawer-head{display:flex;align-items:center;justify-content:space-between;gap:10px;
  padding:13px 16px;border-bottom:1px solid var(--border);flex:0 0 auto;}
.dtk-ui-drawer-title{font-family:var(--mono);font-size:13px;color:var(--text-strong);
  font-weight:700;text-transform:uppercase;letter-spacing:0.04em;}
.dtk-ui-drawer-close{border:1px solid var(--border);background:transparent;color:var(--muted);
  border-radius:7px;width:28px;height:28px;cursor:pointer;font-size:13px;}
.dtk-ui-drawer-close:hover{border-color:var(--st-anomaly);color:var(--st-anomaly);}
.dtk-ui-drawer-body{flex:1;min-height:0;overflow-y:auto;padding:14px 16px;display:flex;
  flex-direction:column;gap:14px;}

.dtk-ui-field{display:flex;flex-direction:column;gap:5px;}
.dtk-ui-field-label{font-family:var(--mono);font-size:10.5px;color:var(--faint);
  text-transform:uppercase;letter-spacing:0.05em;}
.dtk-ui-input,.dtk-ui-select{background:var(--bg);color:var(--text);border:1px solid var(--border);
  border-radius:7px;padding:8px 10px;font-family:var(--mono);font-size:12.5px;width:100%;}
.dtk-ui-input:focus,.dtk-ui-select:focus{outline:none;border-color:var(--clay);}
.dtk-ui-input::placeholder{color:var(--faint);}
.dtk-ui-row2{display:grid;grid-template-columns:1fr 1fr;gap:10px;}
.dtk-ui-checks{display:flex;gap:14px;flex-wrap:wrap;}
.dtk-ui-check{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--muted);
  cursor:pointer;}
.dtk-ui-check input{accent-color:var(--clay);cursor:pointer;}
.dtk-ui-btnrow{display:flex;gap:8px;flex-wrap:wrap;}
.dtk-ui-btn{border:1px solid var(--border);background:var(--surface-2);color:var(--text);
  font-family:var(--sans);font-size:13px;font-weight:600;padding:9px 15px;border-radius:8px;
  cursor:pointer;flex:1 1 auto;}
.dtk-ui-btn:hover{border-color:var(--clay);}
.dtk-ui-btn:disabled{opacity:0.45;cursor:default;}
.dtk-ui-btn.primary{background:var(--clay);border-color:var(--clay);color:#fff;}
.dtk-ui-btn.primary:hover{background:var(--clay-700);}
.dtk-ui-btn.danger{background:transparent;border-color:var(--st-anomaly);color:var(--st-anomaly);}
.dtk-ui-btn.danger:hover{background:rgba(214,50,50,0.12);}
.dtk-ui-reason{font-size:11.5px;color:var(--st-nodata);}
.dtk-ui-log{background:var(--term-bg);border:1px solid var(--term-border);border-radius:9px;
  padding:10px 12px;font-family:var(--mono);font-size:12px;line-height:1.5;color:var(--term-text);
  max-height:320px;overflow-y:auto;white-space:pre-wrap;word-break:break-word;}
.dtk-ui-log-empty{color:var(--faint);font-style:italic;}
.dtk-ui-log-line.exit-ok{color:var(--st-recovery);font-weight:700;}
.dtk-ui-log-line.exit-fail{color:var(--st-anomaly);font-weight:700;}
.dtk-ui-log-line.exit-stop{color:var(--st-nodata);font-weight:700;}

/* --- jobs drawer ------------------------------------------------------------ */
.dtk-ui-joblist{display:flex;flex-direction:column;gap:7px;}
.dtk-ui-jobrow{display:flex;flex-direction:column;gap:4px;background:var(--surface-2);
  border:1px solid var(--border);border-radius:8px;padding:9px 11px;cursor:pointer;}
.dtk-ui-jobrow:hover{border-color:var(--clay);}
.dtk-ui-jobrow.active{border-color:var(--clay);box-shadow:inset 0 0 0 1px var(--clay);}
.dtk-ui-jobrow-top{display:flex;align-items:center;justify-content:space-between;gap:8px;}
.dtk-ui-jobrow-status{display:inline-flex;align-items:center;gap:6px;font-family:var(--mono);
  font-size:10.5px;text-transform:uppercase;letter-spacing:0.04em;}
.dtk-ui-jobrow-dot{width:7px;height:7px;border-radius:50%;flex:0 0 auto;}
.dtk-ui-jobrow-dot.pulse{animation:dtk-ui-pulse 1.2s ease-in-out infinite;}
.dtk-ui-jobrow-label{font-family:var(--mono);font-size:12px;color:var(--text);word-break:break-word;}
.dtk-ui-jobrow-meta{font-family:var(--mono);font-size:10.5px;color:var(--faint);}
.dtk-ui-jobrow-actions{display:flex;gap:6px;margin-top:2px;}
.dtk-ui-joblink{font-family:var(--mono);font-size:11px;color:var(--clay);}

/* --- toasts ------------------------------------------------------------------ */
.dtk-toasts{position:fixed;right:18px;bottom:18px;z-index:60;display:flex;flex-direction:column;
  gap:8px;max-width:360px;}
.dtk-toast{background:var(--surface);border:1px solid var(--border);border-radius:9px;
  padding:11px 14px;font-family:var(--sans);font-size:13px;color:var(--text);
  box-shadow:0 12px 30px -12px rgba(0,0,0,0.5);animation:dtk-ui-toast-in 0.18s ease-out;}
.dtk-toast-error{border-color:var(--st-anomaly);}
.dtk-toast-info{border-color:var(--clay);}
.dtk-toast-out{opacity:0;transform:translateY(6px);transition:opacity 0.2s,transform 0.2s;}
@keyframes dtk-ui-toast-in{from{opacity:0;transform:translateY(6px);}to{opacity:1;transform:none;}}

/* --- editor tabs (Builder | YAML) -------------------------------------------
   Sits in the metric editor's .dtk-ui-editor-head, next to the title. */
.dtk-ui-edtabs{display:flex;gap:4px;}
.dtk-ui-edtab{border:1px solid var(--border);background:var(--surface);color:var(--faint);
  font-family:var(--mono);font-size:11.5px;padding:5px 12px;border-radius:7px;cursor:pointer;}
.dtk-ui-edtab:hover{color:var(--text);}
.dtk-ui-edtab.on{background:var(--clay);color:#fff;border-color:var(--clay);font-weight:600;}
.dtk-ui-edtab:disabled{opacity:0.4;cursor:not-allowed;}

/* --- live validation chip (editor footer) ------------------------------------ */
.dtk-ui-validchip{display:inline-flex;align-items:center;gap:6px;font-family:var(--mono);
  font-size:11px;color:var(--faint);cursor:help;}
.dtk-ui-validchip-dot{width:7px;height:7px;border-radius:50%;background:var(--faint);flex:0 0 auto;}
.dtk-ui-validchip.checking .dtk-ui-validchip-dot{animation:dtk-ui-pulse 1.2s ease-in-out infinite;}
.dtk-ui-validchip.ok{color:var(--st-recovery);}
.dtk-ui-validchip.ok .dtk-ui-validchip-dot{background:var(--st-recovery);}
.dtk-ui-validchip.warn{color:var(--st-nodata);}
.dtk-ui-validchip.warn .dtk-ui-validchip-dot{background:var(--st-nodata);}
.dtk-ui-validchip.err{color:var(--st-anomaly);}
.dtk-ui-validchip.err .dtk-ui-validchip-dot{background:var(--st-anomaly);}

/* --- next-steps strip (after a create save) --------------------------------- */
.dtk-ui-nextsteps{display:flex;align-items:center;justify-content:space-between;gap:12px;
  flex-wrap:wrap;background:rgba(46,158,115,0.1);border:1px solid rgba(46,158,115,0.35);
  border-radius:10px;padding:11px 14px;}
.dtk-ui-nextsteps.failed{background:rgba(214,50,50,0.08);border-color:rgba(214,50,50,0.35);}
.dtk-ui-nextsteps-text{font-size:13px;color:var(--text);}
.dtk-ui-nextsteps-text b{color:var(--text-strong);}
.dtk-ui-nextsteps-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap;}
.dtk-ui-nextsteps-close{border:0;background:transparent;color:var(--faint);cursor:pointer;
  font-size:14px;padding:2px 6px;line-height:1;}
.dtk-ui-nextsteps-close:hover{color:var(--text);}
.dtk-ui-nextsteps-link{color:var(--clay);text-decoration:underline;cursor:pointer;}
.dtk-ui-nextsteps-spin{width:7px;height:7px;border-radius:50%;background:var(--clay);
  animation:dtk-ui-pulse 1.2s ease-in-out infinite;flex:0 0 auto;}
/* an empty strip host must not eat a flex-gap slot in the root column */
.dtk-ui-nextsteps-box:empty{display:none;}

/* --- metric builder form: grid + rail ---------------------------------------
   Two columns: a scrollable parameter rail (~380px) + the query pane filling
   the rest. The shell gives .dtk-ui-form a flex-fill container (it lives
   inside .dtk-ui-editor-body in Builder mode), so it grows to fill the modal. */
.dtk-ui-form{display:grid;grid-template-columns:minmax(300px,380px) 1fr;gap:16px;
  flex:1;min-height:0;}
.dtk-ui-form-rail{overflow-y:auto;display:flex;flex-direction:column;gap:12px;
  padding-right:4px;min-height:0;}
.dtk-ui-form-main{display:flex;flex-direction:column;min-height:0;gap:10px;}
.dtk-ui-form-query{flex:1;min-height:0;display:flex;flex-direction:column;gap:10px;}

/* --- form sections ------------------------------------------------------------ */
.dtk-ui-form-sec{background:var(--surface-2);border:1px solid var(--border);border-radius:10px;
  padding:12px 13px;display:flex;flex-direction:column;gap:10px;flex:0 0 auto;}
.dtk-ui-form-sec-head{display:flex;align-items:center;justify-content:space-between;}
.dtk-ui-form-sec-title{font-family:var(--sans);font-size:12.5px;font-weight:700;
  color:var(--text-strong);text-transform:uppercase;letter-spacing:0.03em;}
.dtk-ui-form-sec-body{display:flex;flex-direction:column;gap:10px;}

/* --- collapsible "advanced" chunks (native <details>/<summary>) -------------- */
.dtk-ui-form-adv{border-top:1px dashed var(--border);padding-top:8px;margin-top:2px;}
.dtk-ui-form-adv-summary{cursor:pointer;font-family:var(--mono);font-size:11px;color:var(--faint);
  text-transform:uppercase;letter-spacing:0.04em;user-select:none;}
.dtk-ui-form-adv-summary:hover{color:var(--text);}
.dtk-ui-form-adv[open] > .dtk-ui-form-adv-summary{color:var(--clay);}
.dtk-ui-form-adv-body{display:flex;flex-direction:column;gap:10px;margin-top:8px;}

/* --- inline validation / warnings / status text ------------------------------ */
.dtk-ui-form-err-inline{font-size:11px;color:var(--st-anomaly);min-height:14px;}
.dtk-ui-form-err{font-size:12px;color:var(--st-anomaly);}
.dtk-ui-form-err:empty{display:none;}
.dtk-ui-form-warn{display:flex;flex-direction:column;gap:3px;font-size:11.5px;color:var(--st-nodata);}
.dtk-ui-form-warn:empty{display:none;}
.dtk-ui-form-hint-status{font-size:11px;color:var(--faint);font-style:italic;}
.dtk-ui-form-hint-status:empty{display:none;}

/* --- textareas (description / instructions / OSI paste) ---------------------- */
.dtk-ui-textarea{resize:vertical;min-height:56px;line-height:1.45;}

/* --- chip inputs (tags / mentions / synonyms / examples / custom channels) --- */
.dtk-ui-chipinput{display:flex;flex-direction:column;gap:6px;}
.dtk-ui-chipinput-chips{display:flex;flex-wrap:wrap;gap:5px;}
.dtk-ui-chipinput-chips:empty{display:none;}
.dtk-ui-chip{display:inline-flex;align-items:center;gap:4px;background:var(--surface-2);
  border:1px solid var(--border);border-radius:999px;padding:3px 5px 3px 10px;
  font-size:11.5px;color:var(--text);font-family:var(--mono);}
.dtk-ui-chip-x{border:0;background:transparent;color:var(--faint);cursor:pointer;
  font-size:11px;line-height:1;padding:2px 5px;border-radius:50%;}
.dtk-ui-chip-x:hover{color:var(--st-anomaly);background:rgba(214,50,50,0.12);}
.dtk-ui-chipinput-field{background:var(--bg);color:var(--text);border:1px solid var(--border);
  border-radius:7px;padding:6px 9px;font-family:var(--mono);font-size:12px;width:100%;}
.dtk-ui-chipinput-field:focus{outline:none;border-color:var(--clay);}
.dtk-ui-chipinput-field::placeholder{color:var(--faint);}

/* --- preserved-field chips (passthrough, read-only) -------------------------- */
.dtk-ui-preschips{display:flex;flex-wrap:wrap;gap:5px;}
.dtk-ui-preschip{display:inline-block;background:var(--surface-2);border:1px dashed var(--border);
  border-radius:999px;padding:3px 10px;font-size:11px;color:var(--faint);font-family:var(--mono);}

/* --- interval preset chips ----------------------------------------------------- */
.dtk-ui-chip-presets{display:flex;gap:6px;margin-top:4px;}
.dtk-ui-chip-preset{border:1px solid var(--border);background:var(--surface-2);color:var(--muted);
  font-family:var(--mono);font-size:11px;padding:3px 9px;border-radius:6px;cursor:pointer;}
.dtk-ui-chip-preset:hover{border-color:var(--clay);color:var(--text);}

/* --- detector rows ------------------------------------------------------------- */
.dtk-ui-detrows{display:flex;flex-direction:column;gap:8px;}
.dtk-ui-detrow{background:var(--surface);border:1px solid var(--border);border-radius:9px;
  padding:10px 11px;display:flex;flex-direction:column;gap:8px;}
.dtk-ui-detrow-head{display:flex;align-items:center;justify-content:space-between;gap:8px;}
.dtk-ui-detrow-head .dtk-ui-select{flex:1;}
.dtk-ui-detrow-readonly{font-size:11.5px;color:var(--faint);font-style:italic;flex:1;}
.dtk-ui-detrow-fields{display:flex;flex-wrap:wrap;gap:8px;}
.dtk-ui-detrow-fields .dtk-ui-field{flex:1 1 100px;min-width:90px;}
.dtk-ui-detrow-remove{border:1px solid var(--border);background:transparent;color:var(--muted);
  border-radius:6px;width:24px;height:24px;flex:0 0 auto;cursor:pointer;font-size:11px;
  line-height:1;}
.dtk-ui-detrow-remove:hover{border-color:var(--st-anomaly);color:var(--st-anomaly);}

/* --- alerting rail fields + channel checkbox type suffix ---------------------- */
.dtk-ui-alerting-fields{display:flex;flex-direction:column;gap:10px;}
.dtk-ui-check-type{color:var(--faint);font-family:var(--mono);font-size:10.5px;}

/* --- sub-tabs (query pane: SQL | From OSI) ------------------------------------- */
.dtk-ui-subtabs{display:flex;gap:4px;border-bottom:1px solid var(--border);padding-bottom:8px;
  flex:0 0 auto;}
.dtk-ui-subtab{border:1px solid transparent;background:transparent;color:var(--faint);
  font-family:var(--sans);font-size:12.5px;font-weight:600;padding:6px 12px;border-radius:7px;
  cursor:pointer;}
.dtk-ui-subtab:hover{color:var(--text);}
.dtk-ui-subtab.on{background:var(--clay);color:#fff;}
.dtk-ui-subtab-panes{flex:1;min-height:0;display:flex;flex-direction:column;}
.dtk-ui-subtab-pane{flex:1;min-height:0;display:flex;flex-direction:column;gap:10px;
  overflow-y:auto;padding-top:10px;}

/* --- SQL editor (sql-editor.ts): a highlighted <pre> underneath a transparent
   <textarea>, perfectly overlapping — identical font/size/line-height/padding
   on both layers is what makes the illusion work. --------------------------- */
.dtk-ui-sqled{position:relative;flex:1;min-height:280px;border:1px solid var(--term-border);
  border-radius:9px;overflow:hidden;background:var(--term-bg);}
.dtk-ui-sqled-hl,.dtk-ui-sqled-ta{position:absolute;inset:0;margin:0;padding:12px 14px;
  font-family:var(--mono);font-size:12.5px;line-height:1.55;white-space:pre;tab-size:2;
  overflow:auto;border:0;}
.dtk-ui-sqled-hl{color:var(--term-text);pointer-events:none;}
.dtk-ui-sqled-hl code{white-space:pre;font-family:inherit;}
.dtk-ui-sqled-ta{background:transparent;color:transparent;caret-color:var(--term-text);
  resize:none;z-index:1;}
.dtk-ui-sqled-ta:focus{outline:none;}
.dtk-ui-sqled-ta:disabled{cursor:not-allowed;}
.dtk-ui-sqled-note{position:absolute;inset:0;z-index:2;display:flex;align-items:center;
  justify-content:center;text-align:center;padding:20px;background:rgba(33,30,26,0.9);
  color:var(--term-text);font-family:var(--sans);font-size:12.5px;line-height:1.5;}

/* SQL token colors — kw/str/cmt/jinja reuse existing brand tokens; num is the
   one new hardcoded shade the spec calls for (a muted syntax-highlight blue,
   not a brand color). */
.dtk-sql-kw{color:var(--clay);}
.dtk-sql-fn{color:var(--term-text);font-weight:700;}
.dtk-sql-str{color:var(--accent-green);}
.dtk-sql-num{color:#7ba5c9;}
.dtk-sql-cmt{color:var(--faint);font-style:italic;}
.dtk-sql-jinja{color:var(--st-nodata);}

/* --- responsive ------------------------------------------------------------- */
@media (max-width:980px){
  .dtk-ui-form{grid-template-columns:1fr;}
  .dtk-ui-form-rail{max-height:44vh;}
}
@media (max-width:860px){
  .dtk-ui-drawer{width:100vw;}
  .dtk-ui-row2{grid-template-columns:1fr;}
}
`;
  const style = document.createElement('style');
  style.setAttribute('data-dtk-ui', '');
  style.textContent = css;
  document.head.appendChild(style);
}
