"use strict";(()=>{var M=e=>String(e).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");function Ne(e){let n=e/60;return e>=86400&&e%86400===0?e/86400+"d":e>=3600&&e%3600===0?e/3600+"h":n>=1&&e%60===0?n+"min":e+"s"}function Z(e){return e==null||!Number.isFinite(e)?"\u2014":(e*100).toFixed(1)+"%"}function pe(e){return e==null||!Number.isFinite(e)?"\u2014":Math.round(e).toLocaleString("en-US")}function le(e){return e==null||!Number.isFinite(e)?"\u2014":`\u2248${e>=9.5?e.toFixed(0):e.toFixed(1)}/day`}function be(e,n){let o=Math.max(0,e-n),r=Math.round(o/6e4);if(r<1)return"just now";if(r<60)return`${r}m ago`;let t=Math.floor(r/60);if(t<24)return`${t}h ago`;let a=Math.floor(t/24);return a<30?`${a}d ago`:`${Math.floor(a/30)}mo ago`}function $e(e,n){let o=Math.max(0,Math.round((n-e)/1e3));if(o<60)return`${o}s`;let r=Math.floor(o/60),t=o%60;if(r<60)return t?`${r}m ${t}s`:`${r}m`;let a=Math.floor(r/60),u=r%60;return`${a}h ${String(u).padStart(2,"0")}m`}function we(e){return new Date(e).toISOString().slice(0,19).replace("T"," ")}function ve(e){let n=Math.round(e/60);if(n<60)return`${n}m`;let o=Math.floor(n/60),r=n%60;if(o<24)return o+"h"+(r?` ${r}m`:"");let t=Math.floor(o/24),a=o%24;return t+"d"+(a?` ${a}h`:"")}function De(e,n){let o=new Map;for(let r of e){let t=n(r),a=o.get(t);a?a.push(r):o.set(t,[r])}return o}var ct=new URLSearchParams(location.search).get("token")||"";function Me(e,n){let o=new URL(e,location.origin);if(o.searchParams.set("token",ct),n)for(let[r,t]of Object.entries(n))o.searchParams.set(r,t);return o.toString()}function Ee(e,n){return Me(`/metric/${encodeURIComponent(e)}`,{window:n})}async function Pe(e){let n=await e.text().catch(()=>"");return new Error(n||`HTTP ${e.status}`)}async function ge(e,n){let o=await fetch(Me(e,n));if(!o.ok)throw await Pe(o);return o.json()}async function ee(e,n){let o=await fetch(Me(e),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(n)});if(!o.ok)throw await Pe(o);return o.json()}function Ce(e,n){return ge(`/api/stats/${encodeURIComponent(e)}`,{window:n})}function _e(){return ge("/api/jobs")}function He(e,n){return ge(`/api/job/${encodeURIComponent(e)}`,{offset:String(n)})}function Oe(e){return ee("/api/run",e)}function je(e){return ee("/api/autotune",e)}function Ae(e){return ee("/api/unlock",e)}function Be(e){return ee("/api/tune",e)}function Ie(e){return ee(`/api/job/${encodeURIComponent(e)}/stop`,{})}function Je(e){return ge(`/api/metric-source/${encodeURIComponent(e)}`)}function ze(e){return ee("/api/metric-create",e)}function qe(e,n){return ee(`/api/metric/${encodeURIComponent(e)}/update`,n)}function Fe(e){return ee(`/api/metric/${encodeURIComponent(e)}/delete`,{confirm:e})}var oe="dtk-ui",Ue=!1;function Ke(){if(Ue)return;Ue=!0;let e=`
.${oe}{
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
.${oe} *{box-sizing:border-box;}
.${oe} a{color:var(--clay);}
.${oe}-root{max-width:1400px;margin:0 auto;padding:16px 20px 56px;display:flex;
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
`,n=document.createElement("style");n.setAttribute("data-dtk-ui",""),n.textContent=e,document.head.appendChild(n)}var re=null;function ut(e){return re&&re.isConnected||(re=document.createElement("div"),re.className="dtk-toasts",e.appendChild(re)),re}function I(e,n,o){let r=ut(e),t=document.createElement("div");t.className=`dtk-toast dtk-toast-${n}`,t.textContent=o,r.appendChild(t),window.setTimeout(()=>{t.classList.add("dtk-toast-out"),window.setTimeout(()=>t.remove(),220)},5e3)}function ie(e,n,o,r){let t="dtk-ui-tile"+(r!=null&&r.err?" err":""),a=r!=null&&r.warn?"dtk-ui-tile-sub warn":"dtk-ui-tile-sub";return`<div class="${t}"><div class="dtk-ui-tile-val">${M(e)}</div><div class="dtk-ui-tile-label">${M(n)}</div>`+(o?`<div class="${a}">${M(o)}</div>`:"")+"</div>"}function Ye(e){let n=document.createElement("div");n.className="dtk-ui-tiles";let o=e.length,r=e.filter(s=>s.enabled).length,t=e.filter(s=>!s.pending),a=0,u=0,g=0,h=0,c=!1;for(let s of t)a+=s.alerts.anomaly,u+=s.alerts.no_data,s.alerts.anomaly>0&&g++,s.alerts.per_day!==null&&(h+=s.alerts.per_day,c=!0);let f=[];for(let s of t)if(s.enabled){if(s.last_point===null){f.push({m:s,lag:1/0});continue}s.lag_seconds!==null&&s.interval_seconds>0&&s.lag_seconds>2*s.interval_seconds&&f.push({m:s,lag:s.lag_seconds})}f.sort((s,p)=>p.lag-s.lag);let w=f.length===0?void 0:`worst: ${f[0].m.name}${Number.isFinite(f[0].lag)?` (${ve(f[0].lag)})`:" (no data)"}`;n.innerHTML=ie(`${r}/${o}`,"Metrics","enabled / total")+ie(pe(a),"Alerts in window",c?le(h):void 0)+ie(pe(u),"No-data events")+ie(pe(g),"Metrics alerting")+ie(pe(f.length),"Stale metrics",w,{warn:f.length>0,err:f.length>0});let v=t.filter(s=>s.quality!==null);if(v.length>0){let s=0,p=0,k=0,S=0,m=0;for(let T of v){let N=T.quality;N&&(s+=N.caught,p+=N.incidents_in_window,k+=N.false_alerts,S+=T.alerts.anomaly,T.budget>m&&(m=T.budget))}let L=p>0?s/p:null,d=S>0?k/S:null,b=d!==null&&m>0&&d>m;n.innerHTML+=ie(Z(L),"Labeled recall",`${v.length} metric(s) labeled`)+ie(Z(d),"False-alert rate",b?`\u25B2 over ${Z(m)} budget`:void 0,{warn:b})}return n}var me="untagged";function pt(e){let n=new Map,o=(r,t)=>{let a=n.get(r);a||(a={tag:r,count:0,alerts:0,perDaySum:0,havePerDay:!1},n.set(r,a)),a.count++,a.alerts+=t.alerts.anomaly,t.alerts.per_day!==null&&(a.perDaySum+=t.alerts.per_day,a.havePerDay=!0)};for(let r of e)if(r.tags.length===0)o(me,r);else for(let t of r.tags)o(t,r);return[...n.values()].sort((r,t)=>t.count-r.count||r.tag.localeCompare(t.tag))}function We(e,n,o){let r=document.createElement("div");r.className="dtk-ui-tags";let t=document.createElement("button");t.type="button",t.className="dtk-ui-tag"+(n===null?" on":""),t.innerHTML=`<span class="dtk-ui-tag-name">All</span><span class="dtk-ui-tag-n">${e.length}</span>`,t.onclick=()=>o(null),r.appendChild(t);for(let a of pt(e)){let u=document.createElement("button");u.type="button",u.className="dtk-ui-tag"+(n===a.tag?" on":"");let g=a.havePerDay?` \xB7 ${le(a.perDaySum)}`:"";u.innerHTML=`<span class="dtk-ui-tag-name">${M(a.tag===me?me:`#${a.tag}`)}</span><span class="dtk-ui-tag-n">${a.count} metric${a.count===1?"":"s"}</span><span class="dtk-ui-tag-n">${a.alerts} alert${a.alerts===1?"":"s"}</span>`+(g?`<span class="dtk-ui-tag-sub">${M(g)}</span>`:""),u.onclick=()=>o(a.tag),r.appendChild(u)}return r}var mt={"--term-bg":"#211e1a","--clay":"#d15b36","--st-anomaly":"#d63232","--st-recovery":"#36a64f","--st-nodata":"#f0ad4e","--st-error":"#5a7a8c","--faint":"#9a9384","--muted":"#6e675b","--border":"#332f29","--term-border":"#332f29"};function ke(e){return getComputedStyle(document.documentElement).getPropertyValue(e).trim()||mt[e]||"#888"}function ft(e){let n=e.replace("#","").trim();n.length===3&&(n=n[0]+n[0]+n[1]+n[1]+n[2]+n[2]);let o=parseInt(n,16);return n.length!==6||Number.isNaN(o)?[209,91,54]:[o>>16&255,o>>8&255,o&255]}function Ge(e,n){let[o,r,t]=ft(e);return`rgba(${o},${r},${t},${n})`}var Ot=Number.isFinite;var Xe=140,Ve=30;function Qe(e,n,o){let r=Math.max(1,window.devicePixelRatio||1);e.style.width=`${Xe}px`,e.style.height=`${Ve}px`,e.width=Math.round(Xe*r),e.height=Math.round(Ve*r);let t=e.getContext("2d");if(!t||(t.clearRect(0,0,e.width,e.height),n.length===0))return;let a=3*r,u=e.width,g=e.height,h=n[0].t,c=n[n.length-1].t,f=c-h||1,w=d=>a+(d-h)/f*Math.max(1,u-2*a),v=1/0,s=-1/0;for(let d of n)d.v!==null&&Number.isFinite(d.v)&&(d.v<v&&(v=d.v),d.v>s&&(s=d.v));let p=!Number.isFinite(v)||!Number.isFinite(s);p&&(v=0,s=1),s<=v&&(s=v+1);let k=d=>g-a-(d-v)/(s-v)*Math.max(1,g-2*a);if(p){let d=g/2;t.strokeStyle=Ge(ke("--faint"),.5),t.lineWidth=1*r,t.setLineDash([2*r,2*r]),t.beginPath(),t.moveTo(a,d),t.lineTo(u-a,d),t.stroke(),t.setLineDash([]);return}t.strokeStyle=ke("--term-text"),t.lineWidth=1*r,t.lineJoin="round",t.beginPath();let S=!1;for(let d of n){if(d.v===null||!Number.isFinite(d.v)){S=!1;continue}let b=w(d.t),T=k(d.v);S?t.lineTo(b,T):(t.moveTo(b,T),S=!0)}if(t.stroke(),o.length===0)return;let m=[];for(let d of n)d.v!==null&&Number.isFinite(d.v)&&m.push([d.t,d.v]);let L=d=>{if(m.length===0)return null;if(d<=m[0][0])return m[0][1];if(d>=m[m.length-1][0])return m[m.length-1][1];for(let b=1;b<m.length;b++){let[T,N]=m[b];if(d<=T){let[$,J]=m[b-1],_=T===$?0:(d-$)/(T-$);return J+(N-J)*_}}return m[m.length-1][1]};t.fillStyle=ke("--st-anomaly");for(let d of o){if(d<h||d>c)continue;let b=L(d);b!==null&&(t.beginPath(),t.arc(w(d),k(b),2*r,0,Math.PI*2),t.fill())}}var xe='<span class="dtk-ui-pending">\xB7\xB7\xB7</span>';function de(e){return{name:e.name,dir:e.dir,file:e.file,tags:e.tags,enabled:e.enabled,interval_seconds:e.interval_seconds,detectors:[],alert_rule:null,last_point:null,first_point_in_window:null,lag_seconds:null,locked:!1,points:0,flagged:0,anomaly_rate:null,alerts:{anomaly:0,recovery:0,no_data:0,per_day:null,last_ts:null},quality:null,budget:0,spark:[],spark_anoms:[],error:null,pending:!0}}var Te={alerts:"desc",name:"asc",rate:"desc",freshness:"desc"};function et(e){var t;if(e.pending)return{color:"var(--faint)",title:"loading\u2026",rank:0};if(!e.enabled)return{color:"var(--faint)",title:"disabled",rank:-1};if(e.last_point===null)return{color:"var(--st-anomaly)",title:"no datapoints loaded yet",rank:1/0};let n=(t=e.lag_seconds)!=null?t:0,o=e.interval_seconds>0?n/e.interval_seconds:0,r=`lag ${ve(Math.max(0,n))} (${o.toFixed(1)}\xD7 interval) \xB7 last point ${we(e.last_point)} UTC`;return o<2?{color:"var(--st-recovery)",title:r,rank:n}:o<6?{color:"var(--st-nodata)",title:r,rank:n}:{color:"var(--st-anomaly)",title:r,rank:n}}function bt(e){return e.length===0?"":`<div class="dtk-ui-tagchips">${e.map(n=>`<span class="dtk-ui-tagchip">${M(n)}</span>`).join("")}</div>`}function vt(e){let n=e.quality;if(!n)return'<span class="dtk-ui-quality empty">\u2014</span>';let o=`Incidents: ${n.incidents} (${n.incidents_in_window} in window) \xB7 caught ${n.caught} \xB7 false alerts ${n.false_alerts} \xB7 reviewed ${n.reviewed} (valid ${n.reviewed_valid}, false ${n.reviewed_false}) \xB7 ${n.labels_file}`;return`<span class="dtk-ui-quality" title="${M(o)}"><span class="dtk-ui-quality-chip">R <b>${M(Z(n.recall))}</b></span> \xB7 <span class="dtk-ui-quality-chip">FDR <b>${M(Z(n.fdr))}</b></span> \xB7 <span class="dtk-ui-quality-chip">\u2713${n.reviewed_valid}</span></span>`}function gt(e){let n=e.alert_rule?`min_detectors=${e.alert_rule.min_detectors} \xB7 direction=${e.alert_rule.direction} \xB7 consecutive=${e.alert_rule.consecutive} (${e.alert_rule.enabled}/${e.alert_rule.configs} config(s) enabled)`:"no alerting configured";return`detectors: ${e.detectors.join(", ")||"\u2014"}
alert rule: ${n}
file: ${e.file}`}function kt(e,n,o,r){let t=document.createElement("tr");t.className="dtk-ui-row"+(e.enabled?"":" disabled")+(e.error?" errored":"")+(e.pending?" pending":"");let a=et(e),u=document.createElement("td");u.className="dtk-ui-dotcell",u.innerHTML=`<span class="dtk-ui-dot" style="background:${a.color}" title="${M(a.title)}"></span>`,t.appendChild(u);let g=document.createElement("td");g.className="dtk-ui-namecell";let h=e.error?`<span class="dtk-ui-err-badge" title="${M(e.error)}">!</span>`:"";g.title=gt(e),g.innerHTML=`<span class="dtk-ui-name">${M(e.name)}</span>${h}${bt(e.tags)}`,t.appendChild(g);let c=document.createElement("td");c.innerHTML=`<span class="dtk-ui-interval">${M(Ne(e.interval_seconds))}</span>`,t.appendChild(c);let f=document.createElement("td");if(f.className="dtk-ui-sparkcell",e.pending)f.innerHTML='<span class="dtk-ui-spark-loading">loading\u2026</span>';else if(e.spark.length===0)f.innerHTML='<span class="dtk-ui-spark-empty">no data yet</span>';else{let T=document.createElement("canvas");T.className="dtk-spark",f.appendChild(T),r.push({canvas:T,points:e.spark.map(([N,$])=>({t:N,v:$})),anoms:e.spark_anoms})}t.appendChild(f);let w=document.createElement("td");if(w.className="dtk-ui-alertscell",e.pending)w.innerHTML=xe;else{let T=e.quality!==null&&e.quality.fdr!==null&&e.quality.fdr>e.budget,N="dtk-ui-alerts-n"+(e.alerts.anomaly>0?" hasany":"")+(T?" overbudget":""),$=e.alerts.per_day!==null?`<span class="dtk-ui-alerts-sub">\xB7 ${M(le(e.alerts.per_day))}</span>`:"";w.innerHTML=`<span class="${N}">${e.alerts.anomaly}</span>${$}`}t.appendChild(w);let v=document.createElement("td");e.pending?v.innerHTML=xe:e.alerts.last_ts!==null?v.innerHTML=`<span class="dtk-ui-lastalert" title="${M(we(e.alerts.last_ts))} UTC">${M(be(n,e.alerts.last_ts))}</span>`:v.innerHTML='<span class="dtk-ui-lastalert">\u2014</span>',t.appendChild(v);let s=document.createElement("td");s.innerHTML=e.pending?xe:`<span class="dtk-ui-rate">${M(Z(e.anomaly_rate))}</span>`,t.appendChild(s);let p=document.createElement("td");p.innerHTML=e.pending?xe:vt(e),t.appendChild(p);let k=document.createElement("td");k.innerHTML=e.locked?'<span class="dtk-ui-lock" title="pipeline lock currently held for this metric">LOCK</span>':"",t.appendChild(k);let S=document.createElement("td");S.className="dtk-ui-actionscell";let m=document.createElement("button");m.type="button",m.className="dtk-ui-actionbtn",m.textContent="Open",m.onclick=()=>o.onOpen(e.name);let L=document.createElement("button");L.type="button",L.className="dtk-ui-actionbtn",L.textContent="Tune",L.onclick=()=>o.onTune(e.name);let d=document.createElement("button");d.type="button",d.className="dtk-ui-actionbtn",d.textContent="Run",d.onclick=()=>o.onRun(e.name);let b=document.createElement("button");return b.type="button",b.className="dtk-ui-actionbtn",b.textContent="Edit",b.onclick=()=>o.onEdit(e.name),S.append(m,L,d,b),t.appendChild(S),t}function Ze(e,n){var o;switch(n){case"alerts":return e.alerts.anomaly;case"name":return e.name.toLowerCase();case"rate":return(o=e.anomaly_rate)!=null?o:-1;case"freshness":return et(e).rank}}function xt(e,n){let o=e.filter(a=>a.enabled),r=e.filter(a=>!a.enabled),t=n.dir==="asc"?1:-1;return o.sort((a,u)=>{let g=Ze(a,n.key),h=Ze(u,n.key);return g<h?-1*t:g>h?1*t:a.name.localeCompare(u.name)}),r.sort((a,u)=>a.name.localeCompare(u.name)),[...o,...r]}var ht=[{label:"\u25CF",key:"freshness"},{label:"Name",key:"name"},{label:"Interval",key:null},{label:"Trend",key:null},{label:"Alerts",key:"alerts"},{label:"Last alert",key:null},{label:"Rate",key:"rate"},{label:"Quality",key:null},{label:"",key:null},{label:"",key:null}];function yt(e,n){let o=document.createElement("tr");for(let r of ht){let t=document.createElement("th");if(r.key){t.className="dtk-ui-th";let a=e.key===r.key?`<span class="dtk-ui-th-arrow">${e.dir==="asc"?"\u25B5":"\u25BE"}</span>`:"";t.innerHTML=`${M(r.label)}${a}`,t.onclick=()=>n.onSortChange(r.key)}else t.textContent=r.label;o.appendChild(t)}return o}function wt(e){return e===""?"metrics/":`metrics/${e}/`}function tt(e,n,o,r){var h;let t=[],a=document.createElement("div");if(a.className="dtk-ui-table-wrap",e.length===0)return a.innerHTML='<div class="dtk-ui-empty">No metrics match the current filter.</div>',{el:a,paint:()=>{}};let u=De(e,c=>c.dir),g=[...u.keys()].sort((c,f)=>c===f?0:c===""?-1:f===""?1:c.localeCompare(f));for(let c of g){let f=(h=u.get(c))!=null?h:[],w=document.createElement("div");w.className="dtk-ui-group";let v=f.reduce((m,L)=>m+L.alerts.anomaly,0),s=document.createElement("div");s.className="dtk-ui-group-head",s.innerHTML=`<span class="dtk-ui-group-name">${M(wt(c))}</span><span class="dtk-ui-group-sub">${f.length} metric${f.length===1?"":"s"} \xB7 ${v} alert${v===1?"":"s"}</span>`,w.appendChild(s);let p=document.createElement("table");p.className="dtk-ui-table";let k=document.createElement("thead");k.appendChild(yt(n,r)),p.appendChild(k);let S=document.createElement("tbody");for(let m of xt(f,n))S.appendChild(kt(m,o,r,t));p.appendChild(S),w.appendChild(p),a.appendChild(w)}return{el:a,paint:()=>{for(let c of t)Qe(c.canvas,c.points,c.anoms)}}}var Mt='a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';function he(e,n){let o=document.createElement("div");o.className="dtk-ui-overlay";let r=document.createElement("div");r.className="dtk-ui-overlay-modal"+(n.modalClass?` ${n.modalClass}`:""),r.setAttribute("role","dialog"),r.setAttribute("aria-modal","true"),o.appendChild(r);let t=document.activeElement instanceof HTMLElement?document.activeElement:null;function a(c){let f=Array.from(r.querySelectorAll(Mt)).filter(k=>k.offsetParent!==null);if(f.length===0)return;let w=f[0],v=f[f.length-1],s=document.activeElement,p=s instanceof HTMLElement&&r.contains(s);c.shiftKey&&(!p||s===w)?(c.preventDefault(),v.focus()):!c.shiftKey&&(!p||s===v)&&(c.preventDefault(),w.focus())}function u(c){c.key==="Escape"?n.onRequestClose():c.key==="Tab"&&a(c)}o.addEventListener("click",c=>{c.target===o&&n.onRequestClose()}),document.addEventListener("keydown",u),e.appendChild(o);let g=!1;function h(){g||(g=!0,document.removeEventListener("keydown",u),o.remove(),t==null||t.focus())}return{backdrop:o,modal:r,close:h}}function nt(e,n,o,r){let t=he(e,{onRequestClose:()=>s()}),{modal:a}=t,u=document.createElement("div");u.className="dtk-ui-overlay-head",u.innerHTML=`<span><span class="dtk-ui-overlay-title">${M(n)}</span><span class="dtk-ui-overlay-sub">window: ${M(o)}</span></span>`;let g=document.createElement("div");g.className="dtk-ui-overlay-actions";let h=document.createElement("button");h.type="button",h.className="dtk-ui-btn",h.textContent="Tune",h.onclick=()=>r.onTune(n);let c=document.createElement("button");c.type="button",c.className="dtk-ui-overlay-close",c.textContent="\u2715",c.title="Close (Esc)",g.append(h,c),u.appendChild(g),a.appendChild(u);let f=document.createElement("div");f.className="dtk-ui-overlay-body";let w=document.createElement("div");w.className="dtk-ui-overlay-loading",w.innerHTML=`<span class="dtk-ui-overlay-spinner"></span><span>Building the report for <b>${M(n)}</b>\u2026</span>`,f.appendChild(w);let v=document.createElement("iframe");v.title=`detectkit report \u2014 ${n}`,v.style.visibility="hidden",v.addEventListener("load",()=>{w.style.display="none",v.style.visibility="visible"}),v.src=Ee(n,o),f.appendChild(v),a.appendChild(f);function s(){t.close(),r.onClose()}return c.onclick=s,{setWindow(p){let k=u.querySelector(".dtk-ui-overlay-sub");k&&(k.textContent=`window: ${p}`),w.style.display="",v.style.visibility="hidden",v.src=Ee(n,p)},close:s}}var ot=/^\d{4}-\d{2}-\d{2}( \d{2}:\d{2}:\d{2})?$/,rt="dtk-ui-run-select-options";function it(e,n){let o=document.createElement("div");o.className="dtk-ui-drawer-backdrop";let r=document.createElement("div");r.className="dtk-ui-drawer";let t=document.createElement("div");t.className="dtk-ui-drawer-head",t.innerHTML='<span class="dtk-ui-drawer-title">Run pipeline</span>';let a=document.createElement("button");a.type="button",a.className="dtk-ui-drawer-close",a.textContent="\u2715",t.appendChild(a),r.appendChild(t);let u=document.createElement("div");u.className="dtk-ui-drawer-body",r.appendChild(u);let g=document.createElement("div");g.className="dtk-ui-field";let h=document.createElement("datalist");h.id=rt;let c=document.createElement("input");c.type="text",c.className="dtk-ui-input",c.placeholder="metric name, tag:x, glob, or *",c.value="*",c.setAttribute("list",rt),g.innerHTML='<span class="dtk-ui-field-label">Select</span>',g.append(c,h),u.appendChild(g);let f=document.createElement("div");f.className="dtk-ui-field",f.innerHTML='<span class="dtk-ui-field-label">Steps</span>';let w=document.createElement("div");w.className="dtk-ui-checks";let v={};for(let R of["load","detect","alert"]){let H=document.createElement("label");H.className="dtk-ui-check";let F=document.createElement("input");F.type="checkbox",F.checked=!0,F.onchange=P,H.append(F,document.createTextNode(R)),w.appendChild(H),v[R]=F}f.appendChild(w),u.appendChild(f);let s=document.createElement("div");s.className="dtk-ui-row2";let p=document.createElement("div");p.className="dtk-ui-field",p.innerHTML='<span class="dtk-ui-field-label">From</span>';let k=document.createElement("input");k.type="text",k.className="dtk-ui-input",k.placeholder="YYYY-MM-DD [HH:MM:SS]",k.oninput=P,p.appendChild(k);let S=document.createElement("div");S.className="dtk-ui-field",S.innerHTML='<span class="dtk-ui-field-label">To</span>';let m=document.createElement("input");m.type="text",m.className="dtk-ui-input",m.placeholder="YYYY-MM-DD [HH:MM:SS]",m.oninput=P,S.appendChild(m),s.append(p,S),u.appendChild(s);let L=document.createElement("div");L.className="dtk-ui-checks";let d=document.createElement("label");d.className="dtk-ui-check";let b=document.createElement("input");b.type="checkbox",d.append(b,document.createTextNode("force (skip lock check)"));let T=document.createElement("label");T.className="dtk-ui-check";let N=document.createElement("input");N.type="checkbox",T.append(N,document.createTextNode("full refresh")),L.append(d,T),u.appendChild(L);let $=document.createElement("div");$.className="dtk-ui-btnrow";let J=document.createElement("button");J.type="button",J.className="dtk-ui-btn primary",J.textContent="Run";let _=document.createElement("button");_.type="button",_.className="dtk-ui-btn",_.textContent="Autotune";let U=document.createElement("button");U.type="button",U.className="dtk-ui-btn danger",U.textContent="Unlock",$.append(J,_,U),u.appendChild($);let te=document.createElement("div");te.className="dtk-ui-reason",u.appendChild(te);let q=document.createElement("div");q.className="dtk-ui-field",q.innerHTML='<span class="dtk-ui-field-label">Log</span>';let j=document.createElement("div");j.className="dtk-ui-log";let X=document.createElement("div");X.className="dtk-ui-log-body";let x=document.createElement("div");x.className="dtk-ui-log-line",j.append(X,x),q.appendChild(j),u.appendChild(q);let C=[];function D(){X.innerHTML=C.length===0?'<span class="dtk-ui-log-empty">no output yet</span>':C.map(M).join("<br>")}D();function z(){return j.scrollTop+j.clientHeight>=j.scrollHeight-24}function K(){return Object.keys(v).filter(R=>v[R].checked)}function P(){let R=n.isPipelineBusy(),H=c.value.trim(),F=k.value.trim()===""||ot.test(k.value.trim()),ce=m.value.trim()===""||ot.test(m.value.trim()),V="";R.busy?V=R.reason:H===""?V="select is required":!F||!ce?V="from/to must be YYYY-MM-DD or YYYY-MM-DD HH:MM:SS":K().length===0&&(V="pick at least one step to run"),te.textContent=V,J.disabled=V!=="",_.disabled=R.busy||H===""||!F||!ce,U.disabled=R.busy||H===""}function A(){return{select:c.value.trim(),steps:K(),from:k.value.trim()||null,to:m.value.trim()||null,full_refresh:N.checked,force:b.checked}}J.onclick=()=>n.submitRun(A()),_.onclick=()=>n.submitAutotune({select:c.value.trim(),from:k.value.trim()||null,to:m.value.trim()||null}),U.onclick=()=>{let R=c.value.trim();window.confirm(`Unlock the pipeline lock for "${R}"? Only do this if you're sure no dtk process is actually running against it.`)&&n.submitUnlock({select:R})};function W(){o.classList.remove("open"),r.classList.remove("open")}return a.onclick=W,o.onclick=W,e.append(o,r),{el:r,open(R){R&&(c.value=R),o.classList.add("open"),r.classList.add("open"),P()},close:W,isOpen(){return r.classList.contains("open")},refreshOptions(){h.innerHTML=["*",...n.getSelectOptions()].map(R=>`<option value="${M(R)}"></option>`).join("")},refreshBusyState:P,resetLog(){C=[],D(),x.textContent="",x.className="dtk-ui-log-line"},appendLog(R){if(R.length===0)return;let H=z();C.push(...R),D(),H&&(j.scrollTop=j.scrollHeight)},setLogStatus(R,H){if(R==="running")return;let F=R==="done"&&H===0?"exit-ok":R==="stopped"?"exit-stop":"exit-fail";x.className=`dtk-ui-log-line ${F}`,x.textContent=`\u2500\u2500 ${R} (exit ${H!=null?H:"?"}) \u2500\u2500`}}}function Et(e){return e==="done"?"var(--st-recovery)":e==="failed"?"var(--st-anomaly)":e==="running"?"var(--clay)":"var(--faint)"}function at(e,n){let o=document.createElement("div");o.className="dtk-ui-drawer-backdrop";let r=document.createElement("div");r.className="dtk-ui-drawer";let t=document.createElement("div");t.className="dtk-ui-drawer-head",t.innerHTML='<span class="dtk-ui-drawer-title">Jobs</span>';let a=document.createElement("button");a.type="button",a.className="dtk-ui-drawer-close",a.textContent="\u2715",t.appendChild(a),r.appendChild(t);let u=document.createElement("div");u.className="dtk-ui-drawer-body",r.appendChild(u);let g=document.createElement("div");g.className="dtk-ui-joblist",u.appendChild(g);function h(){o.classList.remove("open"),r.classList.remove("open")}return a.onclick=h,o.onclick=h,e.append(o,r),{el:r,open(){o.classList.add("open"),r.classList.add("open")},close:h,isOpen(){return r.classList.contains("open")},render(c,f,w){var v;if(c.length===0){g.innerHTML='<div class="dtk-ui-empty">No jobs yet.</div>';return}g.innerHTML="";for(let s of c){let p=document.createElement("div");p.className="dtk-ui-jobrow"+(s.id===w?" active":"");let k=s.status==="running"?" pulse":"",S=$e(s.started_at,(v=s.finished_at)!=null?v:f),m=document.createElement("div");m.className="dtk-ui-jobrow-top",m.innerHTML=`<span class="dtk-ui-jobrow-status"><span class="dtk-ui-jobrow-dot${k}" style="background:${Et(s.status)}"></span>${M(s.kind)} \xB7 ${M(s.status)}</span><span class="dtk-ui-jobrow-meta">${M(be(f,s.started_at))} \xB7 ${M(S)}</span>`,p.appendChild(m);let L=document.createElement("div");L.className="dtk-ui-jobrow-label",L.textContent=s.label,p.appendChild(L);let d=document.createElement("div");if(d.className="dtk-ui-jobrow-actions",s.status==="running"){let b=document.createElement("button");b.type="button",b.className="dtk-ui-actionbtn",b.textContent="Stop",b.onclick=T=>{T.stopPropagation(),n.onStop(s.id)},d.appendChild(b)}if(s.kind==="tune"&&s.url){let b=document.createElement("a");b.className="dtk-ui-joblink",b.href=s.url,b.target="_blank",b.rel="noopener",b.textContent="Open tuner",b.onclick=T=>T.stopPropagation(),d.appendChild(b)}d.childElementCount>0&&p.appendChild(d),p.onclick=()=>n.onFollow(s.id),g.appendChild(p)}}}}var st=`# New metric \u2014 edit the query and name, then Create.
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
`;function Se(e,n,o){var X;let r=n.mode==="create",t=!1,a=!1,u=he(e,{modalClass:"dtk-ui-editor-modal",onRequestClose:()=>{j()}}),{modal:g}=u,h=document.createElement("div");h.className="dtk-ui-editor-head";let c=document.createElement("div");c.className="dtk-ui-editor-titlewrap";let f=document.createElement("span");if(f.className="dtk-ui-editor-title",f.textContent=r?"New metric":`Edit ${(X=n.name)!=null?X:""}`,c.appendChild(f),!r&&n.file){let x=document.createElement("span");x.className="dtk-ui-editor-sub",x.textContent=n.file,c.appendChild(x)}h.appendChild(c);let w=document.createElement("button");w.type="button",w.className="dtk-ui-overlay-close",w.textContent="\u2715",w.title="Close (Esc)",w.onclick=()=>{j()},h.appendChild(w),g.appendChild(h);let v=document.createElement("div");v.className="dtk-ui-editor-body",g.appendChild(v);let s=null;if(r){let x=document.createElement("div");x.className="dtk-ui-editor-field",x.innerHTML='<span class="dtk-ui-field-label">Folder</span>',s=document.createElement("input"),s.type="text",s.className="dtk-ui-input",s.placeholder="optional subfolder under metrics/",x.appendChild(s);let C=document.createElement("div");C.className="dtk-ui-editor-hint",C.textContent="The file is written as metrics/[folder/]<name>.yml \u2014 <name> comes from the YAML below.",x.appendChild(C),v.appendChild(x)}let p=document.createElement("textarea");p.className="dtk-ui-editor-textarea",p.spellcheck=!1,p.autocapitalize="off",p.value=n.text,p.addEventListener("input",()=>{t=!0}),p.addEventListener("keydown",x=>{if(x.key==="Tab"){x.preventDefault();let C=p.selectionStart,D=p.selectionEnd;p.value=`${p.value.slice(0,C)}  ${p.value.slice(D)}`,p.selectionStart=p.selectionEnd=C+2,t=!0;return}(x.ctrlKey||x.metaKey)&&x.key.toLowerCase()==="s"&&(x.preventDefault(),U())}),v.appendChild(p);let k=document.createElement("div");k.className="dtk-ui-editor-error",k.style.display="none",g.appendChild(k);function S(x){k.textContent=x,k.style.display=""}function m(){k.style.display="none",k.textContent=""}let L=document.createElement("div");L.className="dtk-ui-editor-foot";let d=document.createElement("div");d.className="dtk-ui-editor-foot-left";let b=document.createElement("div");b.className="dtk-ui-editor-foot-right",L.append(d,b),g.appendChild(L);let T=document.createElement("button");T.type="button",T.className="dtk-ui-btn primary";let N=r?"Create metric":"Save changes";T.textContent=N,T.onclick=()=>{U()},b.appendChild(T);function $(){let x=document.createElement("button");return x.type="button",x.className="dtk-ui-btn danger",x.textContent="Delete metric\u2026",x.onclick=()=>J(),x}r||d.appendChild($());function J(){var A,W;let x=(A=n.name)!=null?A:"",C=(W=n.file)!=null?W:"";d.innerHTML="";let D=document.createElement("div");D.className="dtk-ui-editor-confirm";let z=document.createElement("span");z.className="dtk-ui-editor-confirm-text",z.innerHTML=`Delete <b>${M(x)}</b>? The file <code>${M(C)}</code> is archived to <code>metrics/.history/</code> and removed. Data rows in the <code>_dtk_*</code> tables remain until <code>dtk clean</code>.`,D.appendChild(z);let K=document.createElement("button");K.type="button",K.className="dtk-ui-btn danger",K.textContent="Delete metric",K.onclick=()=>{te(x,K,P)};let P=document.createElement("button");P.type="button",P.className="dtk-ui-btn",P.textContent="Cancel",P.onclick=()=>{d.innerHTML="",d.appendChild($())},D.append(K,P),d.appendChild(D)}function _(x){a=x,T.disabled=x,T.textContent=x?"Saving\u2026":N}async function U(){var x;if(!a){m(),_(!0);try{let C=p.value,D=r?await ze({text:C,folder:(s==null?void 0:s.value.trim())||void 0}):await qe((x=n.name)!=null?x:"",{text:C,digest:n.digest});t=!1,o.onSaved(D,n.mode),q()}catch(C){S(C.message)}finally{_(!1)}}}async function te(x,C,D){if(!a){m(),a=!0,C.disabled=!0,D.disabled=!0,C.textContent="Deleting\u2026";try{let z=await Fe(x);t=!1,o.onDeleted(z),q()}catch(z){S(z.message),C.disabled=!1,D.disabled=!1,C.textContent="Delete metric"}finally{a=!1}}}function q(){u.close(),o.onClose()}function j(){return t&&!window.confirm("Discard unsaved changes?")?!1:(q(),!0)}return p.focus(),{close:q,requestClose:j}}var Ct=3,Tt=[{value:"24h",label:"24h"},{value:"7d",label:"7d"},{value:"30d",label:"30d"},{value:"90d",label:"90d"},{value:"all",label:"All"}];function St(e,n){Ke(),n.classList.add(oe),n.innerHTML="";let o=document.createElement("div");o.className=`${oe}-root`,n.appendChild(o);let r=e.metrics,t={windowPreset:e.initial_window||"30d",metrics:r.map(de),jobs:[],followedJobId:null,followOffset:0,tagFilter:null,sort:{key:"alerts",dir:Te.alerts}},a=null,u=null,g,h;function c(){let i=new Set,l=new Set;for(let y of r){i.add(y.name);for(let B of y.tags)l.add(B)}return[...i,...[...l].map(y=>`tag:${y}`)]}function f(){let i=t.jobs.find(l=>l.status==="running"&&l.kind!=="tune");return i?{busy:!0,reason:`a pipeline job is already running (${i.label})`}:{busy:!1,reason:""}}let w=document.createElement("div");w.className="dtk-ui-header",o.appendChild(w);let v=document.createElement("div");v.className="dtk-ui-brand",v.innerHTML=`<span class="dtk-ui-brand-dot"></span><span class="dtk-ui-brand-name">detectkit \xB7 <b>${M(e.project)}</b></span>`,w.appendChild(v);let s=document.createElement("div");s.className="dtk-ui-header-right",w.appendChild(s);let p=document.createElement("div");p.className="dtk-ui-seg";for(let i of Tt){let l=document.createElement("button");l.type="button",l.className="dtk-ui-seg-btn"+(t.windowPreset===i.value?" on":""),l.textContent=i.label,l.onclick=()=>{t.windowPreset!==i.value&&(t.windowPreset=i.value,p.querySelectorAll(".dtk-ui-seg-btn").forEach(y=>y.classList.remove("on")),l.classList.add("on"),a&&a.setWindow(i.value),ae())},p.appendChild(l)}s.appendChild(p);let k=document.createElement("button");k.type="button",k.className="dtk-ui-iconbtn",k.title="Refresh overview",k.textContent="\u27F3",k.onclick=()=>{ae()},s.appendChild(k);let S=document.createElement("button");S.type="button",S.className="dtk-ui-runbtn",S.textContent="Run pipeline",S.onclick=()=>z(),s.appendChild(S);let m=document.createElement("button");m.type="button",m.className="dtk-ui-newbtn",m.textContent="New metric",m.onclick=()=>U(),s.appendChild(m);let L=document.createElement("span");L.className="dtk-ui-progresschip",L.style.display="none",s.appendChild(L);function d(i,l){if(l===0||i>=l){L.style.display="none";return}L.textContent=`${i}/${l}`,L.style.display=""}let b=document.createElement("button");b.type="button",b.className="dtk-ui-jobschip",b.innerHTML='<span class="dtk-ui-jobschip-dot"></span><span>idle</span>',b.onclick=()=>{D.isOpen()?D.close():K()},s.appendChild(b);function T(){let i=t.jobs.find(B=>B.status==="running");b.classList.toggle("running",!!i);let l=i?`${i.kind} ${i.label}`:"idle",y=b.querySelector("span:last-child");y&&(y.textContent=l),b.title=i?`Started ${new Date(i.started_at).toLocaleString()}`:"No jobs running"}let N=document.createElement("div");N.className="dtk-ui-content",o.appendChild(N);function $(){var O,G;N.innerHTML="";let i=r.length;if(i===0){let E=document.createElement("div");E.className="dtk-ui-empty",E.textContent="No metrics found for this project/selector.",N.appendChild(E);return}let l=t.metrics.filter(E=>!E.pending),y=l.filter(E=>E.error!==null);if(l.length===i&&y.length===i){let E=document.createElement("div");E.className="dtk-ui-banner";let se=(G=(O=y[0])==null?void 0:O.error)!=null?G:"unknown error";E.innerHTML=`<span>Failed to load overview: every metric failed (${M(se)}).</span>`;let Q=document.createElement("button");Q.type="button",Q.className="dtk-ui-banner-retry",Q.textContent="Retry",Q.onclick=()=>{ae()},E.appendChild(Q),N.appendChild(E)}N.appendChild(Ye(t.metrics)),N.appendChild(We(l,t.tagFilter,E=>{t.tagFilter=E,$()}));let B=t.tagFilter===null?t.metrics:t.metrics.filter(E=>t.tagFilter===me?E.tags.length===0:E.tags.includes(t.tagFilter)),Y=tt(B,t.sort,Date.now(),{onOpen:J,onTune:E=>{ce(E)},onRun:E=>z(E),onEdit:E=>{te(E)},onSortChange:E=>{t.sort=t.sort.key===E?{key:E,dir:t.sort.dir==="asc"?"desc":"asc"}:{key:E,dir:Te[E]},$()}});N.appendChild(Y.el),Y.paint()}function J(i){_()&&(a&&a.close(),a=nt(o,i,t.windowPreset,{onTune:l=>{ce(l)},onClose:()=>{a=null}}))}function _(){return u?u.requestClose():!0}function U(){_()&&(a&&(a.close(),a=null),u=Se(o,{mode:"create",text:st},{onSaved:(i,l)=>q(i,l),onDeleted:()=>{},onClose:()=>{u=null}}))}async function te(i){if(!_())return;let l;try{l=await Je(i)}catch(y){I(o,"error",y.message);return}_()&&(a&&(a.close(),a=null),u=Se(o,{mode:"edit",name:l.name,file:l.file,text:l.text,digest:l.digest},{onSaved:(y,B)=>q(y,B),onDeleted:y=>j(y),onClose:()=>{u=null}}))}function q(i,l){I(o,"info",`Metric '${i.name}' ${l==="create"?"created":"saved"}.`),i.note&&I(o,"info",i.note),l==="edit"&&!i.renamed_from?x(i.name,i.metrics):X(i.metrics)}function j(i){I(o,"info",`Metric '${i.name}' deleted (archived).`),i.note&&I(o,"info",i.note),X(i.metrics)}function X(i){r=i,C.refreshOptions(),ae()}function x(i,l){r=l,C.refreshOptions();let y=l.find(O=>O.name===i),B=t.metrics.findIndex(O=>O.name===i);if(!y||B===-1){ae();return}let Y=ne;t.metrics[B]=de(y),$(),Ce(i,t.windowPreset).then(O=>{if(Y!==ne)return;O.pending=!1;let G=t.metrics.findIndex(E=>E.name===i);G!==-1&&(t.metrics[G]=O),$()}).catch(O=>{if(Y!==ne)return;let G=t.metrics.findIndex(E=>E.name===i);G!==-1&&(t.metrics[G]={...de(y),pending:!1,error:O.message}),$()})}let C=it(o,{submitRun:i=>{R(i)},submitAutotune:i=>{H(i)},submitUnlock:i=>{F(i)},getSelectOptions:c,isPipelineBusy:f}),D=at(o,{onFollow:i=>fe(i),onStop:i=>{V(i)}});function z(i){D.close(),C.refreshOptions(),C.refreshBusyState(),C.open(i)}function K(){C.close(),D.render(t.jobs,Date.now(),t.followedJobId),D.open(),Re()}function P(i,l,y,B){let Y={id:y,kind:i,label:l,status:"running",returncode:null,url:B,started_at:Date.now(),finished_at:null};t.jobs=[Y,...t.jobs.filter(O=>O.id!==y)],Le(),Re(),ue()}let A=!1,W=new Set;async function R(i){if(!A){A=!0;try{let l=await Oe(i);P("run",`run --select ${i.select}`,l.job_id,null),fe(l.job_id)}catch(l){I(o,"error",l.message)}finally{A=!1}}}async function H(i){if(!A){A=!0;try{let l=await je(i);P("autotune",`autotune --select ${i.select}`,l.job_id,null),fe(l.job_id)}catch(l){I(o,"error",l.message)}finally{A=!1}}}async function F(i){if(!A){A=!0;try{let l=await Ae(i);P("unlock",`unlock --select ${i.select}`,l.job_id,null),fe(l.job_id)}catch(l){I(o,"error",l.message)}finally{A=!1}}}async function ce(i){if(!W.has(i)){W.add(i),I(o,"info",`Opening tuner for ${i}\u2026`);try{let l=await Be({metric:i});P("tune",`tune --select ${i}`,l.job_id,l.url),window.open(l.url,"_blank")}catch(l){I(o,"error",l.message)}finally{W.delete(i)}}}async function V(i){try{await Ie(i),I(o,"info","Stop requested."),ue()}catch(l){I(o,"error",l.message)}}function fe(i){t.followedJobId=i,t.followOffset=0,z(),C.resetLog(),dt(i)}function Le(){T(),D.render(t.jobs,Date.now(),t.followedJobId),C.refreshBusyState()}async function ue(){try{let i=await _e();t.jobs=i.jobs}catch{}Le()}function Re(){if(g!==void 0)return;let i=()=>{ue().then(()=>{g=D.isOpen()||t.jobs.some(y=>y.status==="running")?window.setTimeout(i,2e3):void 0})};g=window.setTimeout(i,2e3)}function lt(){h!==void 0&&(window.clearTimeout(h),h=void 0)}function dt(i){lt();let l=()=>{He(i,t.followOffset).then(y=>{if(t.followedJobId===i){if(C.appendLog(y.lines),t.followOffset=y.next_offset,y.status!=="running"){C.setLogStatus(y.status,y.returncode),h=void 0,ue();return}h=window.setTimeout(l,1e3)}}).catch(y=>{I(o,"error",`job ${i}: ${y.message}`),h=void 0})};h=window.setTimeout(l,0)}let ne=0;async function ae(){let i=++ne,l=t.windowPreset,y=r;if(t.metrics=y.map(de),k.classList.add("spinning"),d(0,y.length),$(),y.length===0){k.classList.remove("spinning"),d(0,0);return}let B=[...y],Y=0;async function O(){for(;;){if(i!==ne)return;let E=B.shift();if(!E)return;let se;try{se=await Ce(E.name,l),se.pending=!1}catch(ye){se={...de(E),pending:!1,error:ye.message}}if(i!==ne)return;let Q=t.metrics.findIndex(ye=>ye.name===E.name);Q!==-1&&(t.metrics[Q]=se),Y++,d(Y,y.length),$()}}let G=Math.min(Ct,y.length);await Promise.all(Array.from({length:G},()=>O())),i===ne&&(k.classList.remove("spinning"),d(Y,y.length),C.refreshOptions())}$(),C.refreshOptions(),ae(),ue()}window.__DTK_UI__={render:St};})();
