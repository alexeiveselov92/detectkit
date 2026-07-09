"use strict";(()=>{var y=e=>String(e).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");function Se(e){let n=e/60;return e>=86400&&e%86400===0?e/86400+"d":e>=3600&&e%3600===0?e/3600+"h":n>=1&&e%60===0?n+"min":e+"s"}function V(e){return e==null||!Number.isFinite(e)?"\u2014":(e*100).toFixed(1)+"%"}function le(e){return e==null||!Number.isFinite(e)?"\u2014":Math.round(e).toLocaleString("en-US")}function ie(e){return e==null||!Number.isFinite(e)?"\u2014":`\u2248${e>=9.5?e.toFixed(0):e.toFixed(1)}/day`}function me(e,n){let o=Math.max(0,e-n),r=Math.round(o/6e4);if(r<1)return"just now";if(r<60)return`${r}m ago`;let t=Math.floor(r/60);if(t<24)return`${t}h ago`;let i=Math.floor(t/24);return i<30?`${i}d ago`:`${Math.floor(i/30)}mo ago`}function Le(e,n){let o=Math.max(0,Math.round((n-e)/1e3));if(o<60)return`${o}s`;let r=Math.floor(o/60),t=o%60;if(r<60)return t?`${r}m ${t}s`:`${r}m`;let i=Math.floor(r/60),c=r%60;return`${i}h ${String(c).padStart(2,"0")}m`}function he(e){return new Date(e).toISOString().slice(0,19).replace("T"," ")}function fe(e){let n=Math.round(e/60);if(n<60)return`${n}m`;let o=Math.floor(n/60),r=n%60;if(o<24)return o+"h"+(r?` ${r}m`:"");let t=Math.floor(o/24),i=o%24;return t+"d"+(i?` ${i}h`:"")}function Re(e,n){let o=new Map;for(let r of e){let t=n(r),i=o.get(t);i?i.push(r):o.set(t,[r])}return o}var lt=new URLSearchParams(location.search).get("token")||"";function ye(e,n){let o=new URL(e,location.origin);if(o.searchParams.set("token",lt),n)for(let[r,t]of Object.entries(n))o.searchParams.set(r,t);return o.toString()}function we(e,n){return ye(`/metric/${encodeURIComponent(e)}`,{window:n})}async function Ne(e){let n=await e.text().catch(()=>"");return new Error(n||`HTTP ${e.status}`)}async function be(e,n){let o=await fetch(ye(e,n));if(!o.ok)throw await Ne(o);return o.json()}async function Q(e,n){let o=await fetch(ye(e),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(n)});if(!o.ok)throw await Ne(o);return o.json()}function $e(e,n){return be(`/api/stats/${encodeURIComponent(e)}`,{window:n})}function De(){return be("/api/jobs")}function Pe(e,n){return be(`/api/job/${encodeURIComponent(e)}`,{offset:String(n)})}function _e(e){return Q("/api/run",e)}function He(e){return Q("/api/autotune",e)}function je(e){return Q("/api/unlock",e)}function Oe(e){return Q("/api/tune",e)}function Ae(e){return Q(`/api/job/${encodeURIComponent(e)}/stop`,{})}function Be(e){return be(`/api/metric-source/${encodeURIComponent(e)}`)}function Je(e){return Q("/api/metric-create",e)}function ze(e,n){return Q(`/api/metric/${encodeURIComponent(e)}/update`,n)}function Ie(e){return Q(`/api/metric/${encodeURIComponent(e)}/delete`,{confirm:e})}var ee="dtk-ui",qe=!1;function Fe(){if(qe)return;qe=!0;let e=`
.${ee}{
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
.${ee} *{box-sizing:border-box;}
.${ee} a{color:var(--clay);}
.${ee}-root{max-width:1400px;margin:0 auto;padding:16px 20px 56px;display:flex;
  flex-direction:column;gap:16px;}
.dtk-ui-content{display:flex;flex-direction:column;gap:16px;}

/* --- header ------------------------------------------------------------- */
.dtk-ui-header{display:flex;align-items:center;justify-content:space-between;gap:14px;
  flex-wrap:wrap;padding-bottom:2px;}
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
  overflow:hidden;}
.dtk-ui-group + .dtk-ui-group{border-top:1px solid var(--border);}
.dtk-ui-group-head{display:flex;align-items:baseline;justify-content:space-between;gap:10px;
  padding:9px 14px;background:var(--surface-2);}
.dtk-ui-group-name{font-family:var(--mono);font-size:11.5px;color:var(--text);font-weight:600;}
.dtk-ui-group-sub{font-family:var(--mono);font-size:11px;color:var(--faint);}
.dtk-ui-table{width:100%;border-collapse:collapse;font-size:12.5px;}
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
.dtk-ui-namecell{min-width:170px;}
.dtk-ui-name{font-weight:600;color:var(--text-strong);}
.dtk-ui-err-badge{color:var(--st-anomaly);margin-left:6px;cursor:help;font-weight:700;}
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
.dtk-ui-overlay-modal.dtk-ui-editor-modal{max-width:920px;}
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

/* --- responsive ------------------------------------------------------------- */
@media (max-width:860px){
  .dtk-ui-drawer{width:100vw;}
  .dtk-ui-row2{grid-template-columns:1fr;}
  .dtk-ui-table-wrap{overflow-x:auto;}
}
`,n=document.createElement("style");n.setAttribute("data-dtk-ui",""),n.textContent=e,document.head.appendChild(n)}var te=null;function dt(e){return te&&te.isConnected||(te=document.createElement("div"),te.className="dtk-toasts",e.appendChild(te)),te}function B(e,n,o){let r=dt(e),t=document.createElement("div");t.className=`dtk-toast dtk-toast-${n}`,t.textContent=o,r.appendChild(t),window.setTimeout(()=>{t.classList.add("dtk-toast-out"),window.setTimeout(()=>t.remove(),220)},5e3)}function ne(e,n,o,r){let t="dtk-ui-tile"+(r!=null&&r.err?" err":""),i=r!=null&&r.warn?"dtk-ui-tile-sub warn":"dtk-ui-tile-sub";return`<div class="${t}"><div class="dtk-ui-tile-val">${y(e)}</div><div class="dtk-ui-tile-label">${y(n)}</div>`+(o?`<div class="${i}">${y(o)}</div>`:"")+"</div>"}function Ue(e){let n=document.createElement("div");n.className="dtk-ui-tiles";let o=e.length,r=e.filter(s=>s.enabled).length,t=e.filter(s=>!s.pending),i=0,c=0,k=0,h=0,f=!1;for(let s of t)i+=s.alerts.anomaly,c+=s.alerts.no_data,s.alerts.anomaly>0&&k++,s.alerts.per_day!==null&&(h+=s.alerts.per_day,f=!0);let g=[];for(let s of t)if(s.enabled){if(s.last_point===null){g.push({m:s,lag:1/0});continue}s.lag_seconds!==null&&s.interval_seconds>0&&s.lag_seconds>2*s.interval_seconds&&g.push({m:s,lag:s.lag_seconds})}g.sort((s,u)=>u.lag-s.lag);let M=g.length===0?void 0:`worst: ${g[0].m.name}${Number.isFinite(g[0].lag)?` (${fe(g[0].lag)})`:" (no data)"}`;n.innerHTML=ne(`${r}/${o}`,"Metrics","enabled / total")+ne(le(i),"Alerts in window",f?ie(h):void 0)+ne(le(c),"No-data events")+ne(le(k),"Metrics alerting")+ne(le(g.length),"Stale metrics",M,{warn:g.length>0,err:g.length>0});let x=t.filter(s=>s.quality!==null);if(x.length>0){let s=0,u=0,v=0,C=0,m=0;for(let E of x){let R=E.quality;R&&(s+=R.caught,u+=R.incidents_in_window,v+=R.false_alerts,C+=E.alerts.anomaly,E.budget>m&&(m=E.budget))}let S=u>0?s/u:null,l=C>0?v/C:null,b=l!==null&&m>0&&l>m;n.innerHTML+=ne(V(S),"Labeled recall",`${x.length} metric(s) labeled`)+ne(V(l),"False-alert rate",b?`\u25B2 over ${V(m)} budget`:void 0,{warn:b})}return n}var de="untagged";function ct(e){let n=new Map,o=(r,t)=>{let i=n.get(r);i||(i={tag:r,count:0,alerts:0,perDaySum:0,havePerDay:!1},n.set(r,i)),i.count++,i.alerts+=t.alerts.anomaly,t.alerts.per_day!==null&&(i.perDaySum+=t.alerts.per_day,i.havePerDay=!0)};for(let r of e)if(r.tags.length===0)o(de,r);else for(let t of r.tags)o(t,r);return[...n.values()].sort((r,t)=>t.count-r.count||r.tag.localeCompare(t.tag))}function Ke(e,n,o){let r=document.createElement("div");r.className="dtk-ui-tags";let t=document.createElement("button");t.type="button",t.className="dtk-ui-tag"+(n===null?" on":""),t.innerHTML=`<span class="dtk-ui-tag-name">All</span><span class="dtk-ui-tag-n">${e.length}</span>`,t.onclick=()=>o(null),r.appendChild(t);for(let i of ct(e)){let c=document.createElement("button");c.type="button",c.className="dtk-ui-tag"+(n===i.tag?" on":"");let k=i.havePerDay?` \xB7 ${ie(i.perDaySum)}`:"";c.innerHTML=`<span class="dtk-ui-tag-name">${y(i.tag===de?de:`#${i.tag}`)}</span><span class="dtk-ui-tag-n">${i.count} metric${i.count===1?"":"s"}</span><span class="dtk-ui-tag-n">${i.alerts} alert${i.alerts===1?"":"s"}</span>`+(k?`<span class="dtk-ui-tag-sub">${y(k)}</span>`:""),c.onclick=()=>o(i.tag),r.appendChild(c)}return r}var ut={"--term-bg":"#211e1a","--clay":"#d15b36","--st-anomaly":"#d63232","--st-recovery":"#36a64f","--st-nodata":"#f0ad4e","--st-error":"#5a7a8c","--faint":"#9a9384","--muted":"#6e675b","--border":"#332f29","--term-border":"#332f29"};function ve(e){return getComputedStyle(document.documentElement).getPropertyValue(e).trim()||ut[e]||"#888"}function pt(e){let n=e.replace("#","").trim();n.length===3&&(n=n[0]+n[0]+n[1]+n[1]+n[2]+n[2]);let o=parseInt(n,16);return n.length!==6||Number.isNaN(o)?[209,91,54]:[o>>16&255,o>>8&255,o&255]}function Ye(e,n){let[o,r,t]=pt(e);return`rgba(${o},${r},${t},${n})`}var Pt=Number.isFinite;var We=140,Ge=30;function Xe(e,n,o){let r=Math.max(1,window.devicePixelRatio||1);e.style.width=`${We}px`,e.style.height=`${Ge}px`,e.width=Math.round(We*r),e.height=Math.round(Ge*r);let t=e.getContext("2d");if(!t||(t.clearRect(0,0,e.width,e.height),n.length===0))return;let i=3*r,c=e.width,k=e.height,h=n[0].t,f=n[n.length-1].t,g=f-h||1,M=l=>i+(l-h)/g*Math.max(1,c-2*i),x=1/0,s=-1/0;for(let l of n)l.v!==null&&Number.isFinite(l.v)&&(l.v<x&&(x=l.v),l.v>s&&(s=l.v));let u=!Number.isFinite(x)||!Number.isFinite(s);u&&(x=0,s=1),s<=x&&(s=x+1);let v=l=>k-i-(l-x)/(s-x)*Math.max(1,k-2*i);if(u){let l=k/2;t.strokeStyle=Ye(ve("--faint"),.5),t.lineWidth=1*r,t.setLineDash([2*r,2*r]),t.beginPath(),t.moveTo(i,l),t.lineTo(c-i,l),t.stroke(),t.setLineDash([]);return}t.strokeStyle=ve("--term-text"),t.lineWidth=1*r,t.lineJoin="round",t.beginPath();let C=!1;for(let l of n){if(l.v===null||!Number.isFinite(l.v)){C=!1;continue}let b=M(l.t),E=v(l.v);C?t.lineTo(b,E):(t.moveTo(b,E),C=!0)}if(t.stroke(),o.length===0)return;let m=[];for(let l of n)l.v!==null&&Number.isFinite(l.v)&&m.push([l.t,l.v]);let S=l=>{if(m.length===0)return null;if(l<=m[0][0])return m[0][1];if(l>=m[m.length-1][0])return m[m.length-1][1];for(let b=1;b<m.length;b++){let[E,R]=m[b];if(l<=E){let[P,J]=m[b-1],_=E===P?0:(l-P)/(E-P);return J+(R-J)*_}}return m[m.length-1][1]};t.fillStyle=ve("--st-anomaly");for(let l of o){if(l<h||l>f)continue;let b=S(l);b!==null&&(t.beginPath(),t.arc(M(l),v(b),2*r,0,Math.PI*2),t.fill())}}var ge='<span class="dtk-ui-pending">\xB7\xB7\xB7</span>';function ke(e){return{name:e.name,dir:e.dir,file:e.file,tags:e.tags,enabled:e.enabled,interval_seconds:e.interval_seconds,detectors:[],alert_rule:null,last_point:null,first_point_in_window:null,lag_seconds:null,locked:!1,points:0,flagged:0,anomaly_rate:null,alerts:{anomaly:0,recovery:0,no_data:0,per_day:null,last_ts:null},quality:null,budget:0,spark:[],spark_anoms:[],error:null,pending:!0}}var Me={alerts:"desc",name:"asc",rate:"desc",freshness:"desc"};function Qe(e){var t;if(e.pending)return{color:"var(--faint)",title:"loading\u2026",rank:0};if(!e.enabled)return{color:"var(--faint)",title:"disabled",rank:-1};if(e.last_point===null)return{color:"var(--st-anomaly)",title:"no datapoints loaded yet",rank:1/0};let n=(t=e.lag_seconds)!=null?t:0,o=e.interval_seconds>0?n/e.interval_seconds:0,r=`lag ${fe(Math.max(0,n))} (${o.toFixed(1)}\xD7 interval) \xB7 last point ${he(e.last_point)} UTC`;return o<2?{color:"var(--st-recovery)",title:r,rank:n}:o<6?{color:"var(--st-nodata)",title:r,rank:n}:{color:"var(--st-anomaly)",title:r,rank:n}}function mt(e){return e.length===0?"":`<div class="dtk-ui-tagchips">${e.map(n=>`<span class="dtk-ui-tagchip">${y(n)}</span>`).join("")}</div>`}function ft(e){let n=e.quality;if(!n)return'<span class="dtk-ui-quality empty">\u2014</span>';let o=`Incidents: ${n.incidents} (${n.incidents_in_window} in window) \xB7 caught ${n.caught} \xB7 false alerts ${n.false_alerts} \xB7 reviewed ${n.reviewed} (valid ${n.reviewed_valid}, false ${n.reviewed_false}) \xB7 ${n.labels_file}`;return`<span class="dtk-ui-quality" title="${y(o)}"><span class="dtk-ui-quality-chip">R <b>${y(V(n.recall))}</b></span> \xB7 <span class="dtk-ui-quality-chip">FDR <b>${y(V(n.fdr))}</b></span> \xB7 <span class="dtk-ui-quality-chip">\u2713${n.reviewed_valid}</span></span>`}function bt(e){let n=e.alert_rule?`min_detectors=${e.alert_rule.min_detectors} \xB7 direction=${e.alert_rule.direction} \xB7 consecutive=${e.alert_rule.consecutive} (${e.alert_rule.enabled}/${e.alert_rule.configs} config(s) enabled)`:"no alerting configured";return`detectors: ${e.detectors.join(", ")||"\u2014"}
alert rule: ${n}
file: ${e.file}`}function vt(e,n,o,r){let t=document.createElement("tr");t.className="dtk-ui-row"+(e.enabled?"":" disabled")+(e.error?" errored":"")+(e.pending?" pending":"");let i=Qe(e),c=document.createElement("td");c.className="dtk-ui-dotcell",c.innerHTML=`<span class="dtk-ui-dot" style="background:${i.color}" title="${y(i.title)}"></span>`,t.appendChild(c);let k=document.createElement("td");k.className="dtk-ui-namecell";let h=e.error?`<span class="dtk-ui-err-badge" title="${y(e.error)}">!</span>`:"";k.title=bt(e),k.innerHTML=`<span class="dtk-ui-name">${y(e.name)}</span>${h}${mt(e.tags)}`,t.appendChild(k);let f=document.createElement("td");f.innerHTML=`<span class="dtk-ui-interval">${y(Se(e.interval_seconds))}</span>`,t.appendChild(f);let g=document.createElement("td");if(g.className="dtk-ui-sparkcell",e.pending)g.innerHTML='<span class="dtk-ui-spark-loading">loading\u2026</span>';else if(e.spark.length===0)g.innerHTML='<span class="dtk-ui-spark-empty">no data yet</span>';else{let E=document.createElement("canvas");E.className="dtk-spark",g.appendChild(E),r.push({canvas:E,points:e.spark.map(([R,P])=>({t:R,v:P})),anoms:e.spark_anoms})}t.appendChild(g);let M=document.createElement("td");if(M.className="dtk-ui-alertscell",e.pending)M.innerHTML=ge;else{let E=e.quality!==null&&e.quality.fdr!==null&&e.quality.fdr>e.budget,R="dtk-ui-alerts-n"+(e.alerts.anomaly>0?" hasany":"")+(E?" overbudget":""),P=e.alerts.per_day!==null?`<span class="dtk-ui-alerts-sub">\xB7 ${y(ie(e.alerts.per_day))}</span>`:"";M.innerHTML=`<span class="${R}">${e.alerts.anomaly}</span>${P}`}t.appendChild(M);let x=document.createElement("td");e.pending?x.innerHTML=ge:e.alerts.last_ts!==null?x.innerHTML=`<span class="dtk-ui-lastalert" title="${y(he(e.alerts.last_ts))} UTC">${y(me(n,e.alerts.last_ts))}</span>`:x.innerHTML='<span class="dtk-ui-lastalert">\u2014</span>',t.appendChild(x);let s=document.createElement("td");s.innerHTML=e.pending?ge:`<span class="dtk-ui-rate">${y(V(e.anomaly_rate))}</span>`,t.appendChild(s);let u=document.createElement("td");u.innerHTML=e.pending?ge:ft(e),t.appendChild(u);let v=document.createElement("td");v.innerHTML=e.locked?'<span class="dtk-ui-lock" title="pipeline lock currently held for this metric">LOCK</span>':"",t.appendChild(v);let C=document.createElement("td");C.className="dtk-ui-actionscell";let m=document.createElement("button");m.type="button",m.className="dtk-ui-actionbtn",m.textContent="Open",m.onclick=()=>o.onOpen(e.name);let S=document.createElement("button");S.type="button",S.className="dtk-ui-actionbtn",S.textContent="Tune",S.onclick=()=>o.onTune(e.name);let l=document.createElement("button");l.type="button",l.className="dtk-ui-actionbtn",l.textContent="Run",l.onclick=()=>o.onRun(e.name);let b=document.createElement("button");return b.type="button",b.className="dtk-ui-actionbtn",b.textContent="Edit",b.onclick=()=>o.onEdit(e.name),C.append(m,S,l,b),t.appendChild(C),t}function Ve(e,n){var o;switch(n){case"alerts":return e.alerts.anomaly;case"name":return e.name.toLowerCase();case"rate":return(o=e.anomaly_rate)!=null?o:-1;case"freshness":return Qe(e).rank}}function gt(e,n){let o=e.filter(i=>i.enabled),r=e.filter(i=>!i.enabled),t=n.dir==="asc"?1:-1;return o.sort((i,c)=>{let k=Ve(i,n.key),h=Ve(c,n.key);return k<h?-1*t:k>h?1*t:i.name.localeCompare(c.name)}),r.sort((i,c)=>i.name.localeCompare(c.name)),[...o,...r]}var kt=[{label:"\u25CF",key:"freshness"},{label:"Name",key:"name"},{label:"Interval",key:null},{label:"Trend",key:null},{label:"Alerts",key:"alerts"},{label:"Last alert",key:null},{label:"Rate",key:"rate"},{label:"Quality",key:null},{label:"",key:null},{label:"",key:null}];function xt(e,n){let o=document.createElement("tr");for(let r of kt){let t=document.createElement("th");if(r.key){t.className="dtk-ui-th";let i=e.key===r.key?`<span class="dtk-ui-th-arrow">${e.dir==="asc"?"\u25B5":"\u25BE"}</span>`:"";t.innerHTML=`${y(r.label)}${i}`,t.onclick=()=>n.onSortChange(r.key)}else t.textContent=r.label;o.appendChild(t)}return o}function ht(e){return e===""?"metrics/":`metrics/${e}/`}function Ze(e,n,o,r){var h;let t=[],i=document.createElement("div");if(i.className="dtk-ui-table-wrap",e.length===0)return i.innerHTML='<div class="dtk-ui-empty">No metrics match the current filter.</div>',{el:i,paint:()=>{}};let c=Re(e,f=>f.dir),k=[...c.keys()].sort((f,g)=>f===g?0:f===""?-1:g===""?1:f.localeCompare(g));for(let f of k){let g=(h=c.get(f))!=null?h:[],M=document.createElement("div");M.className="dtk-ui-group";let x=g.reduce((m,S)=>m+S.alerts.anomaly,0),s=document.createElement("div");s.className="dtk-ui-group-head",s.innerHTML=`<span class="dtk-ui-group-name">${y(ht(f))}</span><span class="dtk-ui-group-sub">${g.length} metric${g.length===1?"":"s"} \xB7 ${x} alert${x===1?"":"s"}</span>`,M.appendChild(s);let u=document.createElement("table");u.className="dtk-ui-table";let v=document.createElement("thead");v.appendChild(xt(n,r)),u.appendChild(v);let C=document.createElement("tbody");for(let m of gt(g,n))C.appendChild(vt(m,o,r,t));u.appendChild(C),M.appendChild(u),i.appendChild(M)}return{el:i,paint:()=>{for(let f of t)Xe(f.canvas,f.points,f.anoms)}}}function et(e,n,o,r){let t=document.createElement("div");t.className="dtk-ui-overlay";let i=document.createElement("div");i.className="dtk-ui-overlay-modal",t.appendChild(i);let c=document.createElement("div");c.className="dtk-ui-overlay-head",c.innerHTML=`<span><span class="dtk-ui-overlay-title">${y(n)}</span><span class="dtk-ui-overlay-sub">window: ${y(o)}</span></span>`;let k=document.createElement("div");k.className="dtk-ui-overlay-actions";let h=document.createElement("button");h.type="button",h.className="dtk-ui-btn",h.textContent="Tune",h.onclick=()=>r.onTune(n);let f=document.createElement("button");f.type="button",f.className="dtk-ui-overlay-close",f.textContent="\u2715",f.title="Close (Esc)",k.append(h,f),c.appendChild(k),i.appendChild(c);let g=document.createElement("div");g.className="dtk-ui-overlay-body";let M=document.createElement("div");M.className="dtk-ui-overlay-loading",M.innerHTML=`<span class="dtk-ui-overlay-spinner"></span><span>Building the report for <b>${y(n)}</b>\u2026</span>`,g.appendChild(M);let x=document.createElement("iframe");x.title=`detectkit report \u2014 ${n}`,x.style.visibility="hidden",x.addEventListener("load",()=>{M.style.display="none",x.style.visibility="visible"}),x.src=we(n,o),g.appendChild(x),i.appendChild(g),e.appendChild(t);function s(){document.removeEventListener("keydown",u),t.remove(),r.onClose()}function u(v){v.key==="Escape"&&s()}return t.addEventListener("click",v=>{v.target===t&&s()}),f.onclick=s,document.addEventListener("keydown",u),{setWindow(v){let C=c.querySelector(".dtk-ui-overlay-sub");C&&(C.textContent=`window: ${v}`),M.style.display="",x.style.visibility="hidden",x.src=we(n,v)},close:s}}var tt=/^\d{4}-\d{2}-\d{2}( \d{2}:\d{2}:\d{2})?$/,nt="dtk-ui-run-select-options";function ot(e,n){let o=document.createElement("div");o.className="dtk-ui-drawer-backdrop";let r=document.createElement("div");r.className="dtk-ui-drawer";let t=document.createElement("div");t.className="dtk-ui-drawer-head",t.innerHTML='<span class="dtk-ui-drawer-title">Run pipeline</span>';let i=document.createElement("button");i.type="button",i.className="dtk-ui-drawer-close",i.textContent="\u2715",t.appendChild(i),r.appendChild(t);let c=document.createElement("div");c.className="dtk-ui-drawer-body",r.appendChild(c);let k=document.createElement("div");k.className="dtk-ui-field";let h=document.createElement("datalist");h.id=nt;let f=document.createElement("input");f.type="text",f.className="dtk-ui-input",f.placeholder="metric name, tag:x, glob, or *",f.value="*",f.setAttribute("list",nt),k.innerHTML='<span class="dtk-ui-field-label">Select</span>',k.append(f,h),c.appendChild(k);let g=document.createElement("div");g.className="dtk-ui-field",g.innerHTML='<span class="dtk-ui-field-label">Steps</span>';let M=document.createElement("div");M.className="dtk-ui-checks";let x={};for(let L of["load","detect","alert"]){let H=document.createElement("label");H.className="dtk-ui-check";let z=document.createElement("input");z.type="checkbox",z.checked=!0,z.onchange=$,H.append(z,document.createTextNode(L)),M.appendChild(H),x[L]=z}g.appendChild(M),c.appendChild(g);let s=document.createElement("div");s.className="dtk-ui-row2";let u=document.createElement("div");u.className="dtk-ui-field",u.innerHTML='<span class="dtk-ui-field-label">From</span>';let v=document.createElement("input");v.type="text",v.className="dtk-ui-input",v.placeholder="YYYY-MM-DD [HH:MM:SS]",v.oninput=$,u.appendChild(v);let C=document.createElement("div");C.className="dtk-ui-field",C.innerHTML='<span class="dtk-ui-field-label">To</span>';let m=document.createElement("input");m.type="text",m.className="dtk-ui-input",m.placeholder="YYYY-MM-DD [HH:MM:SS]",m.oninput=$,C.appendChild(m),s.append(u,C),c.appendChild(s);let S=document.createElement("div");S.className="dtk-ui-checks";let l=document.createElement("label");l.className="dtk-ui-check";let b=document.createElement("input");b.type="checkbox",l.append(b,document.createTextNode("force (skip lock check)"));let E=document.createElement("label");E.className="dtk-ui-check";let R=document.createElement("input");R.type="checkbox",E.append(R,document.createTextNode("full refresh")),S.append(l,E),c.appendChild(S);let P=document.createElement("div");P.className="dtk-ui-btnrow";let J=document.createElement("button");J.type="button",J.className="dtk-ui-btn primary",J.textContent="Run";let _=document.createElement("button");_.type="button",_.className="dtk-ui-btn",_.textContent="Autotune";let F=document.createElement("button");F.type="button",F.className="dtk-ui-btn danger",F.textContent="Unlock",P.append(J,_,F),c.appendChild(P);let Z=document.createElement("div");Z.className="dtk-ui-reason",c.appendChild(Z);let I=document.createElement("div");I.className="dtk-ui-field",I.innerHTML='<span class="dtk-ui-field-label">Log</span>';let j=document.createElement("div");j.className="dtk-ui-log";let Y=document.createElement("div");Y.className="dtk-ui-log-body";let D=document.createElement("div");D.className="dtk-ui-log-line",j.append(Y,D),I.appendChild(j),c.appendChild(I);let p=[];function N(){Y.innerHTML=p.length===0?'<span class="dtk-ui-log-empty">no output yet</span>':p.map(y).join("<br>")}N();function O(){return j.scrollTop+j.clientHeight>=j.scrollHeight-24}function A(){return Object.keys(x).filter(L=>x[L].checked)}function $(){let L=n.isPipelineBusy(),H=f.value.trim(),z=v.value.trim()===""||tt.test(v.value.trim()),ce=m.value.trim()===""||tt.test(m.value.trim()),U="";L.busy?U=L.reason:H===""?U="select is required":!z||!ce?U="from/to must be YYYY-MM-DD or YYYY-MM-DD HH:MM:SS":A().length===0&&(U="pick at least one step to run"),Z.textContent=U,J.disabled=U!=="",_.disabled=L.busy||H===""||!z||!ce,F.disabled=L.busy||H===""}function q(){return{select:f.value.trim(),steps:A(),from:v.value.trim()||null,to:m.value.trim()||null,full_refresh:R.checked,force:b.checked}}J.onclick=()=>n.submitRun(q()),_.onclick=()=>n.submitAutotune({select:f.value.trim(),from:v.value.trim()||null,to:m.value.trim()||null}),F.onclick=()=>{let L=f.value.trim();window.confirm(`Unlock the pipeline lock for "${L}"? Only do this if you're sure no dtk process is actually running against it.`)&&n.submitUnlock({select:L})};function W(){o.classList.remove("open"),r.classList.remove("open")}return i.onclick=W,o.onclick=W,e.append(o,r),{el:r,open(L){L&&(f.value=L),o.classList.add("open"),r.classList.add("open"),$()},close:W,isOpen(){return r.classList.contains("open")},refreshOptions(){h.innerHTML=["*",...n.getSelectOptions()].map(L=>`<option value="${y(L)}"></option>`).join("")},refreshBusyState:$,resetLog(){p=[],N(),D.textContent="",D.className="dtk-ui-log-line"},appendLog(L){if(L.length===0)return;let H=O();p.push(...L),N(),H&&(j.scrollTop=j.scrollHeight)},setLogStatus(L,H){if(L==="running")return;let z=L==="done"&&H===0?"exit-ok":L==="stopped"?"exit-stop":"exit-fail";D.className=`dtk-ui-log-line ${z}`,D.textContent=`\u2500\u2500 ${L} (exit ${H!=null?H:"?"}) \u2500\u2500`}}}function yt(e){return e==="done"?"var(--st-recovery)":e==="failed"?"var(--st-anomaly)":e==="running"?"var(--clay)":"var(--faint)"}function rt(e,n){let o=document.createElement("div");o.className="dtk-ui-drawer-backdrop";let r=document.createElement("div");r.className="dtk-ui-drawer";let t=document.createElement("div");t.className="dtk-ui-drawer-head",t.innerHTML='<span class="dtk-ui-drawer-title">Jobs</span>';let i=document.createElement("button");i.type="button",i.className="dtk-ui-drawer-close",i.textContent="\u2715",t.appendChild(i),r.appendChild(t);let c=document.createElement("div");c.className="dtk-ui-drawer-body",r.appendChild(c);let k=document.createElement("div");k.className="dtk-ui-joblist",c.appendChild(k);function h(){o.classList.remove("open"),r.classList.remove("open")}return i.onclick=h,o.onclick=h,e.append(o,r),{el:r,open(){o.classList.add("open"),r.classList.add("open")},close:h,isOpen(){return r.classList.contains("open")},render(f,g,M){var x;if(f.length===0){k.innerHTML='<div class="dtk-ui-empty">No jobs yet.</div>';return}k.innerHTML="";for(let s of f){let u=document.createElement("div");u.className="dtk-ui-jobrow"+(s.id===M?" active":"");let v=s.status==="running"?" pulse":"",C=Le(s.started_at,(x=s.finished_at)!=null?x:g),m=document.createElement("div");m.className="dtk-ui-jobrow-top",m.innerHTML=`<span class="dtk-ui-jobrow-status"><span class="dtk-ui-jobrow-dot${v}" style="background:${yt(s.status)}"></span>${y(s.kind)} \xB7 ${y(s.status)}</span><span class="dtk-ui-jobrow-meta">${y(me(g,s.started_at))} \xB7 ${y(C)}</span>`,u.appendChild(m);let S=document.createElement("div");S.className="dtk-ui-jobrow-label",S.textContent=s.label,u.appendChild(S);let l=document.createElement("div");if(l.className="dtk-ui-jobrow-actions",s.status==="running"){let b=document.createElement("button");b.type="button",b.className="dtk-ui-actionbtn",b.textContent="Stop",b.onclick=E=>{E.stopPropagation(),n.onStop(s.id)},l.appendChild(b)}if(s.kind==="tune"&&s.url){let b=document.createElement("a");b.className="dtk-ui-joblink",b.href=s.url,b.target="_blank",b.rel="noopener",b.textContent="Open tuner",b.onclick=E=>E.stopPropagation(),l.appendChild(b)}l.childElementCount>0&&u.appendChild(l),u.onclick=()=>n.onFollow(s.id),k.appendChild(u)}}}}var it=`# New metric \u2014 edit the query and name, then Create.
# Template variables available in query:
#   {{ dtk_start_time }} / {{ dtk_end_time }} \u2014 load window bounds
#   {{ interval_seconds }} \u2014 metric interval in seconds
name: my_metric
description: ""

query: |
  SELECT
    toStartOfInterval(event_time, INTERVAL {{ interval_seconds }} SECOND) AS timestamp,
    count() AS value
  FROM my_table
  WHERE event_time >= '{{ dtk_start_time }}'
    AND event_time < '{{ dtk_end_time }}'
  GROUP BY timestamp
  ORDER BY timestamp

interval: 1h

detectors:
  - type: mad
    params:
      threshold: 3.0
      window_size: 100

# Alerting (optional) \u2014 channels are names from profiles.yml alert_channels
# alerting:
#   enabled: true
#   channels: [my_channel]
#   consecutive_anomalies: 3
`;function Ee(e,n,o){var D;let r=n.mode==="create",t=!1,i=!1,c=document.createElement("div");c.className="dtk-ui-overlay";let k=document.createElement("div");k.className="dtk-ui-overlay-modal dtk-ui-editor-modal",c.appendChild(k);let h=document.createElement("div");h.className="dtk-ui-editor-head";let f=document.createElement("div");f.className="dtk-ui-editor-titlewrap";let g=document.createElement("span");if(g.className="dtk-ui-editor-title",g.textContent=r?"New metric":`Edit ${(D=n.name)!=null?D:""}`,f.appendChild(g),!r&&n.file){let p=document.createElement("span");p.className="dtk-ui-editor-sub",p.textContent=n.file,f.appendChild(p)}h.appendChild(f);let M=document.createElement("button");M.type="button",M.className="dtk-ui-overlay-close",M.textContent="\u2715",M.title="Close (Esc)",M.onclick=()=>j(),h.appendChild(M),k.appendChild(h);let x=document.createElement("div");x.className="dtk-ui-editor-body",k.appendChild(x);let s=null;if(r){let p=document.createElement("div");p.className="dtk-ui-editor-field",p.innerHTML='<span class="dtk-ui-field-label">Folder</span>',s=document.createElement("input"),s.type="text",s.className="dtk-ui-input",s.placeholder="optional subfolder under metrics/",p.appendChild(s);let N=document.createElement("div");N.className="dtk-ui-editor-hint",N.textContent="The file is written as metrics/[folder/]<name>.yml \u2014 <name> comes from the YAML below.",p.appendChild(N),x.appendChild(p)}let u=document.createElement("textarea");u.className="dtk-ui-editor-textarea",u.spellcheck=!1,u.autocapitalize="off",u.value=n.text,u.addEventListener("input",()=>{t=!0}),u.addEventListener("keydown",p=>{if(p.key==="Tab"){p.preventDefault();let N=u.selectionStart,O=u.selectionEnd;u.value=`${u.value.slice(0,N)}  ${u.value.slice(O)}`,u.selectionStart=u.selectionEnd=N+2,t=!0;return}(p.ctrlKey||p.metaKey)&&p.key.toLowerCase()==="s"&&(p.preventDefault(),F())}),x.appendChild(u);let v=document.createElement("div");v.className="dtk-ui-editor-error",v.style.display="none",k.appendChild(v);function C(p){v.textContent=p,v.style.display=""}function m(){v.style.display="none",v.textContent=""}let S=document.createElement("div");S.className="dtk-ui-editor-foot";let l=document.createElement("div");l.className="dtk-ui-editor-foot-left";let b=document.createElement("div");b.className="dtk-ui-editor-foot-right",S.append(l,b),k.appendChild(S);let E=document.createElement("button");E.type="button",E.className="dtk-ui-btn primary";let R=r?"Create metric":"Save changes";E.textContent=R,E.onclick=()=>{F()},b.appendChild(E);function P(){let p=document.createElement("button");return p.type="button",p.className="dtk-ui-btn danger",p.textContent="Delete metric\u2026",p.onclick=()=>J(),p}r||l.appendChild(P());function J(){var W,L;let p=(W=n.name)!=null?W:"",N=(L=n.file)!=null?L:"";l.innerHTML="";let O=document.createElement("div");O.className="dtk-ui-editor-confirm";let A=document.createElement("span");A.className="dtk-ui-editor-confirm-text",A.innerHTML=`Delete <b>${y(p)}</b>? The file <code>${y(N)}</code> is archived to <code>metrics/.history/</code> and removed. Data rows in the <code>_dtk_*</code> tables remain until <code>dtk clean</code>.`,O.appendChild(A);let $=document.createElement("button");$.type="button",$.className="dtk-ui-btn danger",$.textContent="Delete metric",$.onclick=()=>{Z(p,$,q)};let q=document.createElement("button");q.type="button",q.className="dtk-ui-btn",q.textContent="Cancel",q.onclick=()=>{l.innerHTML="",l.appendChild(P())},O.append($,q),l.appendChild(O)}function _(p){i=p,E.disabled=p,E.textContent=p?"Saving\u2026":R}async function F(){var p;if(!i){m(),_(!0);try{let N=u.value,O=r?await Je({text:N,folder:(s==null?void 0:s.value.trim())||void 0}):await ze((p=n.name)!=null?p:"",{text:N,digest:n.digest});t=!1,o.onSaved(O,n.mode),I()}catch(N){C(N.message)}finally{_(!1)}}}async function Z(p,N,O){if(!i){m(),i=!0,N.disabled=!0,O.disabled=!0,N.textContent="Deleting\u2026";try{let A=await Ie(p);t=!1,o.onDeleted(A),I()}catch(A){C(A.message),N.disabled=!1,O.disabled=!1,N.textContent="Delete metric"}finally{i=!1}}}function I(){document.removeEventListener("keydown",Y),c.remove(),o.onClose()}function j(){return t&&!window.confirm("Discard unsaved changes?")?!1:(I(),!0)}function Y(p){p.key==="Escape"&&j()}return c.addEventListener("click",p=>{p.target===c&&j()}),document.addEventListener("keydown",Y),e.appendChild(c),u.focus(),{close:I,requestClose:j}}var wt=3,Mt=[{value:"24h",label:"24h"},{value:"7d",label:"7d"},{value:"30d",label:"30d"},{value:"90d",label:"90d"},{value:"all",label:"All"}];function Et(e,n){Fe(),n.classList.add(ee),n.innerHTML="";let o=document.createElement("div");o.className=`${ee}-root`,n.appendChild(o);let r=e.metrics,t={windowPreset:e.initial_window||"30d",metrics:r.map(ke),jobs:[],followedJobId:null,followOffset:0,tagFilter:null,sort:{key:"alerts",dir:Me.alerts}},i=null,c=null,k,h;function f(){let a=new Set,d=new Set;for(let w of r){a.add(w.name);for(let K of w.tags)d.add(K)}return[...a,...[...d].map(w=>`tag:${w}`)]}function g(){let a=t.jobs.find(d=>d.status==="running"&&d.kind!=="tune");return a?{busy:!0,reason:`a pipeline job is already running (${a.label})`}:{busy:!1,reason:""}}let M=document.createElement("div");M.className="dtk-ui-header",o.appendChild(M);let x=document.createElement("div");x.className="dtk-ui-brand",x.innerHTML=`<span class="dtk-ui-brand-dot"></span><span class="dtk-ui-brand-name">detectkit \xB7 <b>${y(e.project)}</b></span>`,M.appendChild(x);let s=document.createElement("div");s.className="dtk-ui-header-right",M.appendChild(s);let u=document.createElement("div");u.className="dtk-ui-seg";for(let a of Mt){let d=document.createElement("button");d.type="button",d.className="dtk-ui-seg-btn"+(t.windowPreset===a.value?" on":""),d.textContent=a.label,d.onclick=()=>{t.windowPreset!==a.value&&(t.windowPreset=a.value,u.querySelectorAll(".dtk-ui-seg-btn").forEach(w=>w.classList.remove("on")),d.classList.add("on"),i&&i.setWindow(a.value),se())},u.appendChild(d)}s.appendChild(u);let v=document.createElement("button");v.type="button",v.className="dtk-ui-iconbtn",v.title="Refresh overview",v.textContent="\u27F3",v.onclick=()=>{se()},s.appendChild(v);let C=document.createElement("button");C.type="button",C.className="dtk-ui-runbtn",C.textContent="Run pipeline",C.onclick=()=>N(),s.appendChild(C);let m=document.createElement("button");m.type="button",m.className="dtk-ui-newbtn",m.textContent="New metric",m.onclick=()=>F(),s.appendChild(m);let S=document.createElement("span");S.className="dtk-ui-progresschip",S.style.display="none",s.appendChild(S);function l(a,d){if(d===0||a>=d){S.style.display="none";return}S.textContent=`${a}/${d}`,S.style.display=""}let b=document.createElement("button");b.type="button",b.className="dtk-ui-jobschip",b.innerHTML='<span class="dtk-ui-jobschip-dot"></span><span>idle</span>',b.onclick=()=>{p.isOpen()?p.close():O()},s.appendChild(b);function E(){let a=t.jobs.find(K=>K.status==="running");b.classList.toggle("running",!!a);let d=a?`${a.kind} ${a.label}`:"idle",w=b.querySelector("span:last-child");w&&(w.textContent=d),b.title=a?`Started ${new Date(a.started_at).toLocaleString()}`:"No jobs running"}let R=document.createElement("div");R.className="dtk-ui-content",o.appendChild(R);function P(){var oe,pe;R.innerHTML="";let a=r.length;if(a===0){let T=document.createElement("div");T.className="dtk-ui-empty",T.textContent="No metrics found for this project/selector.",R.appendChild(T);return}let d=t.metrics.filter(T=>!T.pending),w=d.filter(T=>T.error!==null);if(d.length===a&&w.length===a){let T=document.createElement("div");T.className="dtk-ui-banner";let re=(pe=(oe=w[0])==null?void 0:oe.error)!=null?pe:"unknown error";T.innerHTML=`<span>Failed to load overview: every metric failed (${y(re)}).</span>`;let X=document.createElement("button");X.type="button",X.className="dtk-ui-banner-retry",X.textContent="Retry",X.onclick=()=>{se()},T.appendChild(X),R.appendChild(T)}R.appendChild(Ue(t.metrics)),R.appendChild(Ke(d,t.tagFilter,T=>{t.tagFilter=T,P()}));let K=t.tagFilter===null?t.metrics:t.metrics.filter(T=>t.tagFilter===de?T.tags.length===0:T.tags.includes(t.tagFilter)),G=Ze(K,t.sort,Date.now(),{onOpen:J,onTune:T=>{z(T)},onRun:T=>N(T),onEdit:T=>{Z(T)},onSortChange:T=>{t.sort=t.sort.key===T?{key:T,dir:t.sort.dir==="asc"?"desc":"asc"}:{key:T,dir:Me[T]},P()}});R.appendChild(G.el),G.paint()}function J(a){_()&&(i&&i.close(),i=et(o,a,t.windowPreset,{onTune:d=>{z(d)},onClose:()=>{i=null}}))}function _(){return c?c.requestClose():!0}function F(){_()&&(i&&(i.close(),i=null),c=Ee(o,{mode:"create",text:it},{onSaved:(a,d)=>I(a,d),onDeleted:()=>{},onClose:()=>{c=null}}))}async function Z(a){if(!_())return;let d;try{d=await Be(a)}catch(w){B(o,"error",w.message);return}_()&&(i&&(i.close(),i=null),c=Ee(o,{mode:"edit",name:d.name,file:d.file,text:d.text,digest:d.digest},{onSaved:(w,K)=>I(w,K),onDeleted:w=>j(w),onClose:()=>{c=null}}))}function I(a,d){B(o,"info",`Metric '${a.name}' ${d==="create"?"created":"saved"}.`),a.note&&B(o,"info",a.note),Y(a.metrics)}function j(a){B(o,"info",`Metric '${a.name}' deleted (archived).`),a.note&&B(o,"info",a.note),Y(a.metrics)}function Y(a){r=a,D.refreshOptions(),se()}let D=ot(o,{submitRun:a=>{W(a)},submitAutotune:a=>{L(a)},submitUnlock:a=>{H(a)},getSelectOptions:f,isPipelineBusy:g}),p=rt(o,{onFollow:a=>U(a),onStop:a=>{ce(a)}});function N(a){p.close(),D.refreshOptions(),D.refreshBusyState(),D.open(a)}function O(){D.close(),p.render(t.jobs,Date.now(),t.followedJobId),p.open(),Te()}function A(a,d,w,K){let G={id:w,kind:a,label:d,status:"running",returncode:null,url:K,started_at:Date.now(),finished_at:null};t.jobs=[G,...t.jobs.filter(oe=>oe.id!==w)],Ce(),Te(),ae()}let $=!1,q=new Set;async function W(a){if(!$){$=!0;try{let d=await _e(a);A("run",`run --select ${a.select}`,d.job_id,null),U(d.job_id)}catch(d){B(o,"error",d.message)}finally{$=!1}}}async function L(a){if(!$){$=!0;try{let d=await He(a);A("autotune",`autotune --select ${a.select}`,d.job_id,null),U(d.job_id)}catch(d){B(o,"error",d.message)}finally{$=!1}}}async function H(a){if(!$){$=!0;try{let d=await je(a);A("unlock",`unlock --select ${a.select}`,d.job_id,null),U(d.job_id)}catch(d){B(o,"error",d.message)}finally{$=!1}}}async function z(a){if(!q.has(a)){q.add(a),B(o,"info",`Opening tuner for ${a}\u2026`);try{let d=await Oe({metric:a});A("tune",`tune --select ${a}`,d.job_id,d.url),window.open(d.url,"_blank")}catch(d){B(o,"error",d.message)}finally{q.delete(a)}}}async function ce(a){try{await Ae(a),B(o,"info","Stop requested."),ae()}catch(d){B(o,"error",d.message)}}function U(a){t.followedJobId=a,t.followOffset=0,N(),D.resetLog(),st(a)}function Ce(){E(),p.render(t.jobs,Date.now(),t.followedJobId),D.refreshBusyState()}async function ae(){try{let a=await De();t.jobs=a.jobs}catch{}Ce()}function Te(){if(k!==void 0)return;let a=()=>{ae().then(()=>{k=p.isOpen()||t.jobs.some(w=>w.status==="running")?window.setTimeout(a,2e3):void 0})};k=window.setTimeout(a,2e3)}function at(){h!==void 0&&(window.clearTimeout(h),h=void 0)}function st(a){at();let d=()=>{Pe(a,t.followOffset).then(w=>{if(t.followedJobId===a){if(D.appendLog(w.lines),t.followOffset=w.next_offset,w.status!=="running"){D.setLogStatus(w.status,w.returncode),h=void 0,ae();return}h=window.setTimeout(d,1e3)}}).catch(w=>{B(o,"error",`job ${a}: ${w.message}`),h=void 0})};h=window.setTimeout(d,0)}let ue=0;async function se(){let a=++ue,d=t.windowPreset,w=r;if(t.metrics=w.map(ke),v.classList.add("spinning"),l(0,w.length),P(),w.length===0){v.classList.remove("spinning"),l(0,0);return}let K=[...w],G=0;async function oe(){for(;;){if(a!==ue)return;let T=K.shift();if(!T)return;let re;try{re=await $e(T.name,d),re.pending=!1}catch(xe){re={...ke(T),pending:!1,error:xe.message}}if(a!==ue)return;let X=t.metrics.findIndex(xe=>xe.name===T.name);X!==-1&&(t.metrics[X]=re),G++,l(G,w.length),P()}}let pe=Math.min(wt,w.length);await Promise.all(Array.from({length:pe},()=>oe())),a===ue&&(v.classList.remove("spinning"),l(G,w.length),D.refreshOptions())}P(),D.refreshOptions(),se(),ae()}window.__DTK_UI__={render:Et};})();
