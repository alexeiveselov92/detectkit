// ---------------------------------------------------------------------------
// Styles (brand tokens; injected once)
// ---------------------------------------------------------------------------

let styled = false;
export function injectStyle(): void {
  if (styled) return;
  styled = true;
  const css = `
.dtk-tune{--c:#d15b36;--c7:#b4471f;--ink:#1b1916;--muted:#6e675b;--faint:#9a9384;
  --paper:#f5f1e8;--surface:#fbf9f3;--border:#e6e0d4;--green:#2e9e73;--anom:#d63232;
  --mono:'JetBrains Mono',ui-monospace,Menlo,monospace;
  --sans:'Schibsted Grotesk',system-ui,-apple-system,Segoe UI,Roboto,sans-serif;}
.dtk-tune-root{max-width:1680px;margin:0 auto;padding:12px 16px;font-family:var(--sans);color:var(--ink);
  height:100dvh;display:flex;flex-direction:column;gap:10px;overflow:hidden;}
.dtk-tune-header{flex:0 0 auto;}
.dtk-tune-titlerow{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;}
.dtk-tune-title{font-size:19px;margin:0;font-weight:700;}
.dtk-tune-badge{font-family:var(--mono);font-size:10px;text-transform:uppercase;letter-spacing:.06em;
  color:#fff;background:var(--c);border-radius:999px;padding:3px 9px;}
.dtk-tune-sub{color:var(--muted);font-size:12px;margin-top:2px;font-family:var(--mono);}
.dtk-tune-desc{color:var(--muted);font-size:12px;margin-top:3px;white-space:pre-wrap;max-height:2.6em;overflow:auto;}
/* cockpit: chart-windshield (stage) + always-visible mode-aware control rail */
.dtk-tune-cockpit{display:flex;gap:12px;flex:1;min-height:0;}
.dtk-tune-stage{position:relative;display:flex;flex-direction:column;gap:8px;flex:1;min-width:0;min-height:0;}
.dtk-tune-hud{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;flex:0 0 auto;}
.dtk-tune-stagefoot{flex:0 0 auto;display:flex;flex-direction:column;gap:6px;}
.dtk-tune-rail{flex:0 0 340px;display:flex;flex-direction:column;min-height:0;background:var(--surface);
  border:1px solid var(--border);border-radius:12px;overflow:hidden;}
.dtk-tune-railhead{flex:0 0 auto;display:flex;align-items:center;justify-content:space-between;gap:8px;
  padding:9px 12px;border-bottom:1px solid var(--border);}
.dtk-rail-title{font-family:var(--mono);font-size:11px;color:var(--muted);text-transform:uppercase;
  letter-spacing:.06em;flex:1 1 auto;}
.dtk-tune-railfoot{flex:0 0 auto;display:flex;flex-direction:column;gap:8px;padding:11px 12px;
  border-top:1px solid var(--border);background:var(--paper);}
.dtk-rail-open{position:absolute;top:50%;right:6px;transform:translateY(-50%);z-index:6;
  border:1px solid var(--border);background:var(--surface);color:var(--ink);border-radius:8px;
  padding:13px 7px;font-size:15px;cursor:pointer;box-shadow:0 1px 6px rgba(27,25,22,.14);}
.dtk-rail-open:hover{border-color:var(--c);color:var(--c7);}
.dtk-dock-toggle{flex:0 0 auto;border:1px solid var(--border);background:var(--surface);color:var(--muted);
  border-radius:7px;padding:4px 10px;font-family:var(--sans);font-size:13px;font-weight:700;cursor:pointer;line-height:1;}
.dtk-dock-toggle:hover{border-color:var(--c);color:var(--c7);}
.dtk-tune-controls{flex:1;min-height:0;overflow-y:auto;display:flex;flex-direction:column;gap:14px;padding:14px;}
.dtk-rail-group{display:flex;flex-direction:column;gap:14px;}
.dtk-ctl{display:flex;flex-direction:column;gap:6px;}
.dtk-ctl-head{display:flex;justify-content:space-between;align-items:baseline;}
.dtk-ctl-label{font-size:12px;font-weight:600;color:var(--ink);}
.dtk-ctl-val{font-family:var(--mono);font-size:12px;color:var(--c7);}
.dtk-seg{display:flex;gap:4px;background:var(--paper);border:1px solid var(--border);border-radius:8px;padding:3px;}
.dtk-seg.dtk-wrap{flex-wrap:wrap;}
.dtk-seg-btn{flex:1 1 auto;border:0;background:transparent;color:var(--muted);font-family:var(--sans);
  font-size:12px;padding:5px 8px;border-radius:6px;cursor:pointer;white-space:nowrap;}
.dtk-seg-btn:hover{color:var(--ink);}
.dtk-seg-btn.on{background:var(--c);color:#fff;font-weight:600;}
.dtk-range{width:100%;accent-color:var(--c);cursor:pointer;}
.dtk-check{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--muted);margin-top:2px;cursor:pointer;}
.dtk-tune-chart{position:relative;width:100%;flex:1;min-height:220px;background:var(--surface);
  border:1px solid var(--border);border-radius:12px;overflow:hidden;}
.dtk-tune-chart canvas{width:100%;height:100%;display:block;}
.dtk-tune-readout{font-family:var(--mono);font-size:12px;color:var(--muted);min-height:18px;}
.dtk-tune-stat{font-family:var(--mono);font-size:12px;color:var(--ink);}
.dtk-tune-warn{font-family:var(--mono);font-size:12px;line-height:1.5;color:var(--c7);
  background:rgba(240,173,78,0.13);border:1px solid rgba(240,173,78,0.5);border-radius:8px;padding:8px 11px;}
.dtk-tune-cfg{background:var(--ink);color:#c9c2b4;border-radius:8px;padding:8px 11px;font-family:var(--mono);
  font-size:12px;overflow-x:auto;}
.dtk-tune-cfg-k{display:flex;width:100%;border:0;background:transparent;color:var(--faint);
  font-family:var(--mono);font-size:11.5px;cursor:pointer;padding:0;text-align:left;}
.dtk-tune-cfg-k:hover{color:#e6e0d4;}
.dtk-tune-cfg-v{display:block;color:#e6e0d4;white-space:pre-wrap;word-break:break-word;margin-top:6px;}
.dtk-tune-apply{display:flex;align-items:center;gap:10px;flex-wrap:wrap;}
.dtk-apply-btn{background:var(--c);color:#fff;border:0;border-radius:8px;padding:10px 18px;font-family:var(--sans);
  font-size:14px;font-weight:600;cursor:pointer;}
.dtk-apply-btn:hover{background:var(--c7);}
.dtk-apply-btn:disabled{opacity:.55;cursor:default;}
.dtk-apply-msg{font-size:13px;}
.dtk-apply-msg.ok{color:var(--green);}
.dtk-apply-msg.err{color:var(--anom);}
.dtk-apply-msg.info{color:var(--muted);}
.dtk-tune-note{font-size:13px;color:var(--muted);background:var(--surface);border:1px dashed var(--border);
  border-radius:8px;padding:10px 12px;}
.dtk-ctl-info{color:var(--faint);font-size:10px;cursor:help;vertical-align:super;}
.dtk-tune-trim{display:flex;flex-direction:column;gap:6px;background:var(--surface);
  border:1px solid var(--border);border-radius:10px;padding:9px 12px;}
.dtk-tune-trim-head{display:flex;justify-content:space-between;align-items:baseline;}
.dtk-tune-trim-val{font-family:var(--mono);font-size:12px;color:var(--c7);}
.dtk-tune-spin{position:absolute;top:10px;right:12px;display:none;align-items:center;gap:7px;
  background:rgba(27,25,22,0.78);color:#e6e0d4;border:1px solid #332f29;border-radius:999px;
  padding:4px 11px 4px 8px;font-family:var(--mono);font-size:11px;pointer-events:none;}
.dtk-tune-spin.on{display:inline-flex;}
.dtk-spin-ring{width:12px;height:12px;border-radius:50%;border:2px solid rgba(245,241,232,0.25);
  border-top-color:var(--c);animation:dtk-spin .7s linear infinite;}
@keyframes dtk-spin{to{transform:rotate(360deg);}}
.dtk-tune-legend{flex:0 0 auto;display:flex;align-items:center;flex-wrap:wrap;gap:8px 16px;font-size:12px;
  color:var(--muted);padding:6px 12px;background:var(--surface);border:1px solid var(--border);border-radius:9px;}
.dtk-leg-item{display:inline-flex;align-items:center;gap:6px;cursor:help;}
.dtk-leg-sw{display:inline-block;flex:0 0 auto;}
.dtk-leg-sw.line{width:16px;height:3px;background:var(--c);border-radius:2px;}
.dtk-leg-sw.band{width:16px;height:11px;background:rgba(209,91,54,0.18);
  border:1px solid rgba(209,91,54,0.5);border-radius:2px;}
.dtk-leg-sw.center{width:16px;height:2px;
  background:repeating-linear-gradient(90deg,var(--faint) 0 4px,transparent 4px 7px);}
.dtk-leg-sw.dot{width:9px;height:9px;border-radius:50%;background:var(--anom);}
.dtk-leg-sw.alert{width:0;height:0;border-left:5px solid transparent;border-right:5px solid transparent;
  border-top:7px solid var(--anom);}
.dtk-leg-sw.alert-ok{width:0;height:0;border-left:5px solid transparent;border-right:5px solid transparent;
  border-top:7px solid var(--green);}
.dtk-leg-sw.alert-no{width:0;height:0;border-left:5px solid transparent;border-right:5px solid transparent;
  border-top:7px solid #5a7a8c;}
.dtk-leg-txt{white-space:nowrap;}
.dtk-season-row{display:flex;align-items:center;justify-content:space-between;gap:8px;}
.dtk-season-col{font-family:var(--mono);font-size:11.5px;color:var(--muted);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.dtk-season-seg{flex:0 0 auto;padding:2px;}
.dtk-season-seg .dtk-seg-btn{flex:0 0 auto;padding:3px 7px;font-family:var(--mono);font-size:11px;}
.dtk-tune-metrics{display:flex;flex-wrap:wrap;gap:8px;margin:0;flex:0 1 auto;}
.dtk-m-chip{display:inline-flex;align-items:center;gap:7px;padding:7px 13px;background:var(--surface);
  border:1px solid var(--border);border-radius:10px;font-size:13px;}
.dtk-m-dot{width:9px;height:9px;border-radius:50%;flex:0 0 auto;}
.dtk-m-v{font-family:var(--mono);font-weight:700;font-size:15px;color:var(--ink);}
.dtk-m-l{color:var(--faint);font-family:var(--mono);font-size:11px;text-transform:uppercase;letter-spacing:.05em;}
.dtk-m-sub{color:var(--muted);font-family:var(--mono);font-size:11.5px;}
.dtk-m-chip.over{border-color:var(--anom);box-shadow:inset 0 0 0 1px rgba(214,50,50,.5);}
.dtk-m-chip.over .dtk-m-sub{color:var(--anom);font-weight:600;}
.dtk-tune-modes{display:inline-flex;gap:4px;background:var(--ink);border-radius:9px;padding:4px;margin:0;flex:0 0 auto;}
.dtk-mode-btn{border:0;background:transparent;color:#c9c2b4;font-family:var(--sans);font-size:13px;font-weight:600;
  padding:7px 16px;border-radius:6px;cursor:pointer;transition:background .12s,color .12s;}
.dtk-mode-btn:hover{color:#fff;}
.dtk-mode-btn.on{background:var(--c);color:#fff;}
.dtk-tune-reviewbar{align-items:center;}
.dtk-tune-reviewbar .dtk-apply-btn{background:var(--green);}
.dtk-tune-reviewbar .dtk-apply-btn:hover{background:#27815d;}
.dtk-at-result{display:flex;flex-direction:column;gap:7px;background:var(--surface);
  border:1px solid var(--border);border-radius:10px;padding:11px 13px;}
.dtk-at-head{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:8px;}
.dtk-at-winner{font-family:var(--mono);font-size:12.5px;font-weight:700;color:var(--ink);}
.dtk-at-score{font-family:var(--mono);font-size:11.5px;color:var(--c7);}
.dtk-at-meta{font-family:var(--mono);font-size:11px;color:var(--muted);word-break:break-word;}
.dtk-at-log{display:flex;flex-direction:column;gap:5px;max-height:240px;overflow:auto;margin-top:4px;}
.dtk-at-logline{display:flex;gap:8px;align-items:baseline;}
.dtk-at-stage{flex:0 0 auto;font-family:var(--mono);font-size:9.5px;text-transform:uppercase;
  letter-spacing:.05em;color:#fff;background:var(--c);border-radius:4px;padding:1px 6px;}
.dtk-at-msg{font-family:var(--mono);font-size:11px;color:var(--ink);}
.dtk-th{display:flex;flex-direction:column;gap:8px;margin:2px 0 6px;}
.dtk-th-toggles{display:flex;gap:8px;flex-wrap:wrap;}
.dtk-th-toggle{align-self:flex-start;border:1px solid var(--border);background:var(--surface);
  color:var(--muted);border-radius:8px;padding:6px 12px;font-family:var(--sans);font-size:12.5px;cursor:pointer;}
.dtk-th-toggle:hover{border-color:var(--c);color:var(--c7);}
.dtk-th-toggle.on{background:var(--c);border-color:var(--c);color:#fff;}
.dtk-th-bar{display:flex;flex-wrap:wrap;align-items:flex-end;gap:10px 14px;padding:11px 13px;
  background:var(--surface);border:1px solid var(--border);border-radius:10px;}
.dtk-th-grp{display:flex;flex-direction:column;gap:3px;}
.dtk-th-lbl{font-family:var(--mono);font-size:10.5px;color:var(--faint);text-transform:uppercase;letter-spacing:.05em;}
.dtk-th-num,.dtk-th-sel{background:var(--paper);color:var(--ink);border:1px solid var(--border);
  border-radius:6px;padding:5px 8px;font-family:var(--mono);font-size:12px;}
.dtk-th-num{width:96px;}
.dtk-th-num:focus,.dtk-th-sel:focus{outline:none;border-color:var(--c);}
.dtk-th-scope{font-family:var(--mono);font-size:11px;color:var(--muted);align-self:center;flex:1 1 160px;}
.dtk-th-add{padding:7px 14px;}
.dtk-th-add:disabled{opacity:.5;cursor:default;}
.dtk-incidents{gap:8px;}
.dtk-inc-list{display:flex;flex-direction:column;gap:6px;max-height:240px;overflow:auto;}
.dtk-inc-empty{font-size:12px;color:var(--faint);font-style:italic;}
.dtk-inc-row{display:flex;align-items:center;gap:6px;flex-wrap:wrap;background:var(--paper);
  border:1px solid var(--border);border-radius:7px;padding:6px 8px;}
.dtk-inc-span{font-family:var(--mono);font-size:10.5px;color:var(--ink);}
.dtk-inc-dur{font-family:var(--mono);font-size:10.5px;color:var(--muted);}
.dtk-inc-label{flex:1 1 90px;min-width:70px;background:var(--surface);color:var(--ink);
  border:1px solid var(--border);border-radius:5px;padding:4px 7px;font-family:var(--sans);font-size:11.5px;}
.dtk-inc-label:focus{outline:none;border-color:var(--c);}
.dtk-inc-btn{border:1px solid var(--border);background:var(--surface);color:var(--muted);border-radius:6px;
  padding:3px 8px;font-size:11px;cursor:pointer;font-family:var(--sans);}
.dtk-inc-btn:hover{border-color:var(--c);color:var(--c7);}
.dtk-inc-del{color:var(--anom);}
.dtk-inc-fromalert{border-color:rgba(46,158,115,.5);background:rgba(46,158,115,.08);}
.dtk-inc-badge{flex:1 1 90px;min-width:70px;font-family:var(--mono);font-size:10.5px;color:var(--green);
  display:inline-flex;align-items:center;font-weight:600;}
.dtk-setname{background:var(--surface);color:var(--ink);border:1px solid var(--border);border-radius:8px;
  padding:9px 11px;font-family:var(--sans);font-size:13px;min-width:180px;}
.dtk-setname::placeholder{color:var(--faint);}
.dtk-setname:focus{outline:none;border-color:var(--c);}
.dtk-labels-btn{background:var(--surface);color:var(--ink);border:1px solid var(--border);}
.dtk-labels-btn:hover{background:var(--paper);border-color:var(--c);color:var(--c7);}
/* Narrow viewports: drop the cockpit to a scrolling stack (chart over rail). */
@media (max-width:900px){
  .dtk-tune-root{height:auto;overflow:visible;}
  .dtk-tune-cockpit{flex-direction:column;}
  .dtk-tune-rail{flex:0 0 auto;width:100%;}
  .dtk-tune-controls{overflow:visible;}
  .dtk-tune-chart{flex:0 0 auto;height:54vh;min-height:320px;}
  .dtk-rail-open{display:none!important;}
}
`;
  const style = document.createElement('style');
  style.textContent = css;
  document.head.appendChild(style);
}
