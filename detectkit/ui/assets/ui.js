"use strict";(()=>{var M=e=>String(e).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");function $e(e){let n=e/60;return e>=86400&&e%86400===0?e/86400+"d":e>=3600&&e%3600===0?e/3600+"h":n>=1&&e%60===0?n+"min":e+"s"}function Z(e){return e==null||!Number.isFinite(e)?"\u2014":(e*100).toFixed(1)+"%"}function pe(e){return e==null||!Number.isFinite(e)?"\u2014":Math.round(e).toLocaleString("en-US")}function le(e){return e==null||!Number.isFinite(e)?"\u2014":`\u2248${e>=9.5?e.toFixed(0):e.toFixed(1)}/day`}function ve(e,n){let o=Math.max(0,e-n),r=Math.round(o/6e4);if(r<1)return"just now";if(r<60)return`${r}m ago`;let t=Math.floor(r/60);if(t<24)return`${t}h ago`;let i=Math.floor(t/24);return i<30?`${i}d ago`:`${Math.floor(i/30)}mo ago`}function _e(e,n){let o=Math.max(0,Math.round((n-e)/1e3));if(o<60)return`${o}s`;let r=Math.floor(o/60),t=o%60;if(r<60)return t?`${r}m ${t}s`:`${r}m`;let i=Math.floor(r/60),c=r%60;return`${i}h ${String(c).padStart(2,"0")}m`}function Me(e){return new Date(e).toISOString().slice(0,19).replace("T"," ")}function ge(e,n){return e===null?null:Math.max(0,e-(n!=null?n:0))}function me(e){let n=Math.round(e/60);if(n<60)return`${n}m`;let o=Math.floor(n/60),r=n%60;if(o<24)return o+"h"+(r?` ${r}m`:"");let t=Math.floor(o/24),i=o%24;return t+"d"+(i?` ${i}h`:"")}function Pe(e,n){let o=new Map;for(let r of e){let t=n(r),i=o.get(t);i?i.push(r):o.set(t,[r])}return o}var ut=new URLSearchParams(location.search).get("token")||"";function Ee(e,n){let o=new URL(e,location.origin);if(o.searchParams.set("token",ut),n)for(let[r,t]of Object.entries(n))o.searchParams.set(r,t);return o.toString()}function Ce(e,n){return Ee(`/metric/${encodeURIComponent(e)}`,{window:n})}async function De(e){let n=await e.text().catch(()=>"");return new Error(n||`HTTP ${e.status}`)}async function ke(e,n){let o=await fetch(Ee(e,n));if(!o.ok)throw await De(o);return o.json()}async function ee(e,n){let o=await fetch(Ee(e),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(n)});if(!o.ok)throw await De(o);return o.json()}function Te(e,n){return ke(`/api/stats/${encodeURIComponent(e)}`,{window:n})}function He(){return ke("/api/jobs")}function Oe(e,n){return ke(`/api/job/${encodeURIComponent(e)}`,{offset:String(n)})}function je(e){return ee("/api/run",e)}function Ae(e){return ee("/api/autotune",e)}function Be(e){return ee("/api/unlock",e)}function Ie(e){return ee("/api/tune",e)}function Je(e){return ee(`/api/job/${encodeURIComponent(e)}/stop`,{})}function ze(e){return ke(`/api/metric-source/${encodeURIComponent(e)}`)}function qe(e){return ee("/api/metric-create",e)}function Fe(e,n){return ee(`/api/metric/${encodeURIComponent(e)}/update`,n)}function Ue(e){return ee(`/api/metric/${encodeURIComponent(e)}/delete`,{confirm:e})}var oe="dtk-ui",Ke=!1;function Ye(){if(Ke)return;Ke=!0;let e=`
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
`,n=document.createElement("style");n.setAttribute("data-dtk-ui",""),n.textContent=e,document.head.appendChild(n)}var re=null;function pt(e){return re&&re.isConnected||(re=document.createElement("div"),re.className="dtk-toasts",e.appendChild(re)),re}function I(e,n,o){let r=pt(e),t=document.createElement("div");t.className=`dtk-toast dtk-toast-${n}`,t.textContent=o,r.appendChild(t),window.setTimeout(()=>{t.classList.add("dtk-toast-out"),window.setTimeout(()=>t.remove(),220)},5e3)}function ie(e,n,o,r){let t="dtk-ui-tile"+(r!=null&&r.err?" err":""),i=r!=null&&r.warn?"dtk-ui-tile-sub warn":"dtk-ui-tile-sub";return`<div class="${t}"><div class="dtk-ui-tile-val">${M(e)}</div><div class="dtk-ui-tile-label">${M(n)}</div>`+(o?`<div class="${i}">${M(o)}</div>`:"")+"</div>"}function We(e){let n=document.createElement("div");n.className="dtk-ui-tiles";let o=e.length,r=e.filter(s=>s.enabled).length,t=e.filter(s=>!s.pending),i=0,c=0,v=0,h=0,u=!1;for(let s of t)i+=s.alerts.anomaly,c+=s.alerts.no_data,s.alerts.anomaly>0&&v++,s.alerts.per_day!==null&&(h+=s.alerts.per_day,u=!0);let f=[];for(let s of t){if(!s.enabled)continue;if(s.last_point===null){f.push({m:s,lag:1/0});continue}let p=ge(s.lag_seconds,s.loading_delay_seconds);p!==null&&s.interval_seconds>0&&p>2*s.interval_seconds&&f.push({m:s,lag:p})}f.sort((s,p)=>p.lag-s.lag);let w=f.length===0?void 0:`worst: ${f[0].m.name}${Number.isFinite(f[0].lag)?` (${me(f[0].lag)})`:" (no data)"}`;n.innerHTML=ie(`${r}/${o}`,"Metrics","enabled / total")+ie(pe(i),"Alerts in window",u?le(h):void 0)+ie(pe(c),"No-data events")+ie(pe(v),"Metrics alerting")+ie(pe(f.length),"Stale metrics",w,{warn:f.length>0,err:f.length>0});let g=t.filter(s=>s.quality!==null);if(g.length>0){let s=0,p=0,k=0,S=0,m=0;for(let T of g){let N=T.quality;N&&(s+=N.caught,p+=N.incidents_in_window,k+=N.false_alerts,S+=T.alerts.anomaly,T.budget>m&&(m=T.budget))}let L=p>0?s/p:null,d=S>0?k/S:null,b=d!==null&&m>0&&d>m;n.innerHTML+=ie(Z(L),"Labeled recall",`${g.length} metric(s) labeled`)+ie(Z(d),"False-alert rate",b?`\u25B2 over ${Z(m)} budget`:void 0,{warn:b})}return n}var fe="untagged";function mt(e){let n=new Map,o=(r,t)=>{let i=n.get(r);i||(i={tag:r,count:0,alerts:0,perDaySum:0,havePerDay:!1},n.set(r,i)),i.count++,i.alerts+=t.alerts.anomaly,t.alerts.per_day!==null&&(i.perDaySum+=t.alerts.per_day,i.havePerDay=!0)};for(let r of e)if(r.tags.length===0)o(fe,r);else for(let t of r.tags)o(t,r);return[...n.values()].sort((r,t)=>t.count-r.count||r.tag.localeCompare(t.tag))}function Ge(e,n,o){let r=document.createElement("div");r.className="dtk-ui-tags";let t=document.createElement("button");t.type="button",t.className="dtk-ui-tag"+(n===null?" on":""),t.innerHTML=`<span class="dtk-ui-tag-name">All</span><span class="dtk-ui-tag-n">${e.length}</span>`,t.onclick=()=>o(null),r.appendChild(t);for(let i of mt(e)){let c=document.createElement("button");c.type="button",c.className="dtk-ui-tag"+(n===i.tag?" on":"");let v=i.havePerDay?` \xB7 ${le(i.perDaySum)}`:"";c.innerHTML=`<span class="dtk-ui-tag-name">${M(i.tag===fe?fe:`#${i.tag}`)}</span><span class="dtk-ui-tag-n">${i.count} metric${i.count===1?"":"s"}</span><span class="dtk-ui-tag-n">${i.alerts} alert${i.alerts===1?"":"s"}</span>`+(v?`<span class="dtk-ui-tag-sub">${M(v)}</span>`:""),c.onclick=()=>o(i.tag),r.appendChild(c)}return r}var ft={"--term-bg":"#211e1a","--clay":"#d15b36","--st-anomaly":"#d63232","--st-recovery":"#36a64f","--st-nodata":"#f0ad4e","--st-error":"#5a7a8c","--faint":"#9a9384","--muted":"#6e675b","--border":"#332f29","--term-border":"#332f29"};function xe(e){return getComputedStyle(document.documentElement).getPropertyValue(e).trim()||ft[e]||"#888"}function bt(e){let n=e.replace("#","").trim();n.length===3&&(n=n[0]+n[0]+n[1]+n[1]+n[2]+n[2]);let o=parseInt(n,16);return n.length!==6||Number.isNaN(o)?[209,91,54]:[o>>16&255,o>>8&255,o&255]}function Xe(e,n){let[o,r,t]=bt(e);return`rgba(${o},${r},${t},${n})`}var jt=Number.isFinite;var Ve=140,Qe=30;function Ze(e,n,o){let r=Math.max(1,window.devicePixelRatio||1);e.style.width=`${Ve}px`,e.style.height=`${Qe}px`,e.width=Math.round(Ve*r),e.height=Math.round(Qe*r);let t=e.getContext("2d");if(!t||(t.clearRect(0,0,e.width,e.height),n.length===0))return;let i=3*r,c=e.width,v=e.height,h=n[0].t,u=n[n.length-1].t,f=u-h||1,w=d=>i+(d-h)/f*Math.max(1,c-2*i),g=1/0,s=-1/0;for(let d of n)d.v!==null&&Number.isFinite(d.v)&&(d.v<g&&(g=d.v),d.v>s&&(s=d.v));let p=!Number.isFinite(g)||!Number.isFinite(s);p&&(g=0,s=1),s<=g&&(s=g+1);let k=d=>v-i-(d-g)/(s-g)*Math.max(1,v-2*i);if(p){let d=v/2;t.strokeStyle=Xe(xe("--faint"),.5),t.lineWidth=1*r,t.setLineDash([2*r,2*r]),t.beginPath(),t.moveTo(i,d),t.lineTo(c-i,d),t.stroke(),t.setLineDash([]);return}t.strokeStyle=xe("--term-text"),t.lineWidth=1*r,t.lineJoin="round",t.beginPath();let S=!1;for(let d of n){if(d.v===null||!Number.isFinite(d.v)){S=!1;continue}let b=w(d.t),T=k(d.v);S?t.lineTo(b,T):(t.moveTo(b,T),S=!0)}if(t.stroke(),o.length===0)return;let m=[];for(let d of n)d.v!==null&&Number.isFinite(d.v)&&m.push([d.t,d.v]);let L=d=>{if(m.length===0)return null;if(d<=m[0][0])return m[0][1];if(d>=m[m.length-1][0])return m[m.length-1][1];for(let b=1;b<m.length;b++){let[T,N]=m[b];if(d<=T){let[$,J]=m[b-1],D=T===$?0:(d-$)/(T-$);return J+(N-J)*D}}return m[m.length-1][1]};t.fillStyle=xe("--st-anomaly");for(let d of o){if(d<h||d>u)continue;let b=L(d);b!==null&&(t.beginPath(),t.arc(w(d),k(b),2*r,0,Math.PI*2),t.fill())}}var he='<span class="dtk-ui-pending">\xB7\xB7\xB7</span>';function de(e){return{name:e.name,dir:e.dir,file:e.file,tags:e.tags,enabled:e.enabled,interval_seconds:e.interval_seconds,loading_delay_seconds:0,detectors:[],alert_rule:null,last_point:null,first_point_in_window:null,lag_seconds:null,locked:!1,points:0,flagged:0,anomaly_rate:null,alerts:{anomaly:0,recovery:0,no_data:0,per_day:null,last_ts:null},quality:null,budget:0,spark:[],spark_anoms:[],error:null,pending:!0}}var Se={alerts:"desc",name:"asc",rate:"desc",freshness:"desc"};function tt(e){var c,v;if(e.pending)return{color:"var(--faint)",title:"loading\u2026",rank:0};if(!e.enabled)return{color:"var(--faint)",title:"disabled",rank:-1};if(e.last_point===null)return{color:"var(--st-anomaly)",title:"no datapoints loaded yet",rank:1/0};let n=(c=e.loading_delay_seconds)!=null?c:0,o=(v=ge(e.lag_seconds,e.loading_delay_seconds))!=null?v:0,r=e.interval_seconds>0?o/e.interval_seconds:0,t=n>0?` \xB7 maturity delay ${me(n)} excluded`:"",i=`lag ${me(o)} (${r.toFixed(1)}\xD7 interval)${t} \xB7 last point ${Me(e.last_point)} UTC`;return r<2?{color:"var(--st-recovery)",title:i,rank:o}:r<6?{color:"var(--st-nodata)",title:i,rank:o}:{color:"var(--st-anomaly)",title:i,rank:o}}function vt(e){return e.length===0?"":`<div class="dtk-ui-tagchips">${e.map(n=>`<span class="dtk-ui-tagchip">${M(n)}</span>`).join("")}</div>`}function gt(e){let n=e.quality;if(!n)return'<span class="dtk-ui-quality empty">\u2014</span>';let o=`Incidents: ${n.incidents} (${n.incidents_in_window} in window) \xB7 caught ${n.caught} \xB7 false alerts ${n.false_alerts} \xB7 reviewed ${n.reviewed} (valid ${n.reviewed_valid}, false ${n.reviewed_false}) \xB7 ${n.labels_file}`;return`<span class="dtk-ui-quality" title="${M(o)}"><span class="dtk-ui-quality-chip">R <b>${M(Z(n.recall))}</b></span> \xB7 <span class="dtk-ui-quality-chip">FDR <b>${M(Z(n.fdr))}</b></span> \xB7 <span class="dtk-ui-quality-chip">\u2713${n.reviewed_valid}</span></span>`}function kt(e){let n=e.alert_rule?`min_detectors=${e.alert_rule.min_detectors} \xB7 direction=${e.alert_rule.direction} \xB7 consecutive=${e.alert_rule.consecutive} (${e.alert_rule.enabled}/${e.alert_rule.configs} config(s) enabled)`:"no alerting configured";return`detectors: ${e.detectors.join(", ")||"\u2014"}
alert rule: ${n}
file: ${e.file}`}function xt(e,n,o,r){let t=document.createElement("tr");t.className="dtk-ui-row"+(e.enabled?"":" disabled")+(e.error?" errored":"")+(e.pending?" pending":"");let i=tt(e),c=document.createElement("td");c.className="dtk-ui-dotcell",c.innerHTML=`<span class="dtk-ui-dot" style="background:${i.color}" title="${M(i.title)}"></span>`,t.appendChild(c);let v=document.createElement("td");v.className="dtk-ui-namecell";let h=e.error?`<span class="dtk-ui-err-badge" title="${M(e.error)}">!</span>`:"";v.title=kt(e),v.innerHTML=`<span class="dtk-ui-name">${M(e.name)}</span>${h}${vt(e.tags)}`,t.appendChild(v);let u=document.createElement("td");u.innerHTML=`<span class="dtk-ui-interval">${M($e(e.interval_seconds))}</span>`,t.appendChild(u);let f=document.createElement("td");if(f.className="dtk-ui-sparkcell",e.pending)f.innerHTML='<span class="dtk-ui-spark-loading">loading\u2026</span>';else if(e.spark.length===0)f.innerHTML='<span class="dtk-ui-spark-empty">no data yet</span>';else{let T=document.createElement("canvas");T.className="dtk-spark",f.appendChild(T),r.push({canvas:T,points:e.spark.map(([N,$])=>({t:N,v:$})),anoms:e.spark_anoms})}t.appendChild(f);let w=document.createElement("td");if(w.className="dtk-ui-alertscell",e.pending)w.innerHTML=he;else{let T=e.quality!==null&&e.quality.fdr!==null&&e.quality.fdr>e.budget,N="dtk-ui-alerts-n"+(e.alerts.anomaly>0?" hasany":"")+(T?" overbudget":""),$=e.alerts.per_day!==null?`<span class="dtk-ui-alerts-sub">\xB7 ${M(le(e.alerts.per_day))}</span>`:"";w.innerHTML=`<span class="${N}">${e.alerts.anomaly}</span>${$}`}t.appendChild(w);let g=document.createElement("td");e.pending?g.innerHTML=he:e.alerts.last_ts!==null?g.innerHTML=`<span class="dtk-ui-lastalert" title="${M(Me(e.alerts.last_ts))} UTC">${M(ve(n,e.alerts.last_ts))}</span>`:g.innerHTML='<span class="dtk-ui-lastalert">\u2014</span>',t.appendChild(g);let s=document.createElement("td");s.innerHTML=e.pending?he:`<span class="dtk-ui-rate">${M(Z(e.anomaly_rate))}</span>`,t.appendChild(s);let p=document.createElement("td");p.innerHTML=e.pending?he:gt(e),t.appendChild(p);let k=document.createElement("td");k.innerHTML=e.locked?'<span class="dtk-ui-lock" title="pipeline lock currently held for this metric">LOCK</span>':"",t.appendChild(k);let S=document.createElement("td");S.className="dtk-ui-actionscell";let m=document.createElement("button");m.type="button",m.className="dtk-ui-actionbtn",m.textContent="Open",m.onclick=()=>o.onOpen(e.name);let L=document.createElement("button");L.type="button",L.className="dtk-ui-actionbtn",L.textContent="Tune",L.onclick=()=>o.onTune(e.name);let d=document.createElement("button");d.type="button",d.className="dtk-ui-actionbtn",d.textContent="Run",d.onclick=()=>o.onRun(e.name);let b=document.createElement("button");return b.type="button",b.className="dtk-ui-actionbtn",b.textContent="Edit",b.onclick=()=>o.onEdit(e.name),S.append(m,L,d,b),t.appendChild(S),t}function et(e,n){var o;switch(n){case"alerts":return e.alerts.anomaly;case"name":return e.name.toLowerCase();case"rate":return(o=e.anomaly_rate)!=null?o:-1;case"freshness":return tt(e).rank}}function ht(e,n){let o=e.filter(i=>i.enabled),r=e.filter(i=>!i.enabled),t=n.dir==="asc"?1:-1;return o.sort((i,c)=>{let v=et(i,n.key),h=et(c,n.key);return v<h?-1*t:v>h?1*t:i.name.localeCompare(c.name)}),r.sort((i,c)=>i.name.localeCompare(c.name)),[...o,...r]}var yt=[{label:"\u25CF",key:"freshness"},{label:"Name",key:"name"},{label:"Interval",key:null},{label:"Trend",key:null},{label:"Alerts",key:"alerts"},{label:"Last alert",key:null},{label:"Rate",key:"rate"},{label:"Quality",key:null},{label:"",key:null},{label:"",key:null}];function wt(e,n){let o=document.createElement("tr");for(let r of yt){let t=document.createElement("th");if(r.key){t.className="dtk-ui-th";let i=e.key===r.key?`<span class="dtk-ui-th-arrow">${e.dir==="asc"?"\u25B5":"\u25BE"}</span>`:"";t.innerHTML=`${M(r.label)}${i}`,t.onclick=()=>n.onSortChange(r.key)}else t.textContent=r.label;o.appendChild(t)}return o}function Mt(e){return e===""?"metrics/":`metrics/${e}/`}function nt(e,n,o,r){var h;let t=[],i=document.createElement("div");if(i.className="dtk-ui-table-wrap",e.length===0)return i.innerHTML='<div class="dtk-ui-empty">No metrics match the current filter.</div>',{el:i,paint:()=>{}};let c=Pe(e,u=>u.dir),v=[...c.keys()].sort((u,f)=>u===f?0:u===""?-1:f===""?1:u.localeCompare(f));for(let u of v){let f=(h=c.get(u))!=null?h:[],w=document.createElement("div");w.className="dtk-ui-group";let g=f.reduce((m,L)=>m+L.alerts.anomaly,0),s=document.createElement("div");s.className="dtk-ui-group-head",s.innerHTML=`<span class="dtk-ui-group-name">${M(Mt(u))}</span><span class="dtk-ui-group-sub">${f.length} metric${f.length===1?"":"s"} \xB7 ${g} alert${g===1?"":"s"}</span>`,w.appendChild(s);let p=document.createElement("table");p.className="dtk-ui-table";let k=document.createElement("thead");k.appendChild(wt(n,r)),p.appendChild(k);let S=document.createElement("tbody");for(let m of ht(f,n))S.appendChild(xt(m,o,r,t));p.appendChild(S),w.appendChild(p),i.appendChild(w)}return{el:i,paint:()=>{for(let u of t)Ze(u.canvas,u.points,u.anoms)}}}var Et='a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';function ye(e,n){let o=document.createElement("div");o.className="dtk-ui-overlay";let r=document.createElement("div");r.className="dtk-ui-overlay-modal"+(n.modalClass?` ${n.modalClass}`:""),r.setAttribute("role","dialog"),r.setAttribute("aria-modal","true"),o.appendChild(r);let t=document.activeElement instanceof HTMLElement?document.activeElement:null;function i(u){let f=Array.from(r.querySelectorAll(Et)).filter(k=>k.offsetParent!==null);if(f.length===0)return;let w=f[0],g=f[f.length-1],s=document.activeElement,p=s instanceof HTMLElement&&r.contains(s);u.shiftKey&&(!p||s===w)?(u.preventDefault(),g.focus()):!u.shiftKey&&(!p||s===g)&&(u.preventDefault(),w.focus())}function c(u){u.key==="Escape"?n.onRequestClose():u.key==="Tab"&&i(u)}o.addEventListener("click",u=>{u.target===o&&n.onRequestClose()}),document.addEventListener("keydown",c),e.appendChild(o);let v=!1;function h(){v||(v=!0,document.removeEventListener("keydown",c),o.remove(),t==null||t.focus())}return{backdrop:o,modal:r,close:h}}function ot(e,n,o,r){let t=ye(e,{onRequestClose:()=>s()}),{modal:i}=t,c=document.createElement("div");c.className="dtk-ui-overlay-head",c.innerHTML=`<span><span class="dtk-ui-overlay-title">${M(n)}</span><span class="dtk-ui-overlay-sub">window: ${M(o)}</span></span>`;let v=document.createElement("div");v.className="dtk-ui-overlay-actions";let h=document.createElement("button");h.type="button",h.className="dtk-ui-btn",h.textContent="Tune",h.onclick=()=>r.onTune(n);let u=document.createElement("button");u.type="button",u.className="dtk-ui-overlay-close",u.textContent="\u2715",u.title="Close (Esc)",v.append(h,u),c.appendChild(v),i.appendChild(c);let f=document.createElement("div");f.className="dtk-ui-overlay-body";let w=document.createElement("div");w.className="dtk-ui-overlay-loading",w.innerHTML=`<span class="dtk-ui-overlay-spinner"></span><span>Building the report for <b>${M(n)}</b>\u2026</span>`,f.appendChild(w);let g=document.createElement("iframe");g.title=`detectkit report \u2014 ${n}`,g.style.visibility="hidden",g.addEventListener("load",()=>{w.style.display="none",g.style.visibility="visible"}),g.src=Ce(n,o),f.appendChild(g),i.appendChild(f);function s(){t.close(),r.onClose()}return u.onclick=s,{setWindow(p){let k=c.querySelector(".dtk-ui-overlay-sub");k&&(k.textContent=`window: ${p}`),w.style.display="",g.style.visibility="hidden",g.src=Ce(n,p)},close:s}}var rt=/^\d{4}-\d{2}-\d{2}( \d{2}:\d{2}:\d{2})?$/,it="dtk-ui-run-select-options";function at(e,n){let o=document.createElement("div");o.className="dtk-ui-drawer-backdrop";let r=document.createElement("div");r.className="dtk-ui-drawer";let t=document.createElement("div");t.className="dtk-ui-drawer-head",t.innerHTML='<span class="dtk-ui-drawer-title">Run pipeline</span>';let i=document.createElement("button");i.type="button",i.className="dtk-ui-drawer-close",i.textContent="\u2715",t.appendChild(i),r.appendChild(t);let c=document.createElement("div");c.className="dtk-ui-drawer-body",r.appendChild(c);let v=document.createElement("div");v.className="dtk-ui-field";let h=document.createElement("datalist");h.id=it;let u=document.createElement("input");u.type="text",u.className="dtk-ui-input",u.placeholder="metric name, tag:x, glob, or *",u.value="*",u.setAttribute("list",it),v.innerHTML='<span class="dtk-ui-field-label">Select</span>',v.append(u,h),c.appendChild(v);let f=document.createElement("div");f.className="dtk-ui-field",f.innerHTML='<span class="dtk-ui-field-label">Steps</span>';let w=document.createElement("div");w.className="dtk-ui-checks";let g={};for(let R of["load","detect","alert"]){let H=document.createElement("label");H.className="dtk-ui-check";let F=document.createElement("input");F.type="checkbox",F.checked=!0,F.onchange=P,H.append(F,document.createTextNode(R)),w.appendChild(H),g[R]=F}f.appendChild(w),c.appendChild(f);let s=document.createElement("div");s.className="dtk-ui-row2";let p=document.createElement("div");p.className="dtk-ui-field",p.innerHTML='<span class="dtk-ui-field-label">From</span>';let k=document.createElement("input");k.type="text",k.className="dtk-ui-input",k.placeholder="YYYY-MM-DD [HH:MM:SS]",k.oninput=P,p.appendChild(k);let S=document.createElement("div");S.className="dtk-ui-field",S.innerHTML='<span class="dtk-ui-field-label">To</span>';let m=document.createElement("input");m.type="text",m.className="dtk-ui-input",m.placeholder="YYYY-MM-DD [HH:MM:SS]",m.oninput=P,S.appendChild(m),s.append(p,S),c.appendChild(s);let L=document.createElement("div");L.className="dtk-ui-checks";let d=document.createElement("label");d.className="dtk-ui-check";let b=document.createElement("input");b.type="checkbox",d.append(b,document.createTextNode("force (skip lock check)"));let T=document.createElement("label");T.className="dtk-ui-check";let N=document.createElement("input");N.type="checkbox",T.append(N,document.createTextNode("full refresh")),L.append(d,T),c.appendChild(L);let $=document.createElement("div");$.className="dtk-ui-btnrow";let J=document.createElement("button");J.type="button",J.className="dtk-ui-btn primary",J.textContent="Run";let D=document.createElement("button");D.type="button",D.className="dtk-ui-btn",D.textContent="Autotune";let U=document.createElement("button");U.type="button",U.className="dtk-ui-btn danger",U.textContent="Unlock",$.append(J,D,U),c.appendChild($);let te=document.createElement("div");te.className="dtk-ui-reason",c.appendChild(te);let q=document.createElement("div");q.className="dtk-ui-field",q.innerHTML='<span class="dtk-ui-field-label">Log</span>';let j=document.createElement("div");j.className="dtk-ui-log";let X=document.createElement("div");X.className="dtk-ui-log-body";let x=document.createElement("div");x.className="dtk-ui-log-line",j.append(X,x),q.appendChild(j),c.appendChild(q);let C=[];function _(){X.innerHTML=C.length===0?'<span class="dtk-ui-log-empty">no output yet</span>':C.map(M).join("<br>")}_();function z(){return j.scrollTop+j.clientHeight>=j.scrollHeight-24}function K(){return Object.keys(g).filter(R=>g[R].checked)}function P(){let R=n.isPipelineBusy(),H=u.value.trim(),F=k.value.trim()===""||rt.test(k.value.trim()),ce=m.value.trim()===""||rt.test(m.value.trim()),V="";R.busy?V=R.reason:H===""?V="select is required":!F||!ce?V="from/to must be YYYY-MM-DD or YYYY-MM-DD HH:MM:SS":K().length===0&&(V="pick at least one step to run"),te.textContent=V,J.disabled=V!=="",D.disabled=R.busy||H===""||!F||!ce,U.disabled=R.busy||H===""}function A(){return{select:u.value.trim(),steps:K(),from:k.value.trim()||null,to:m.value.trim()||null,full_refresh:N.checked,force:b.checked}}J.onclick=()=>n.submitRun(A()),D.onclick=()=>n.submitAutotune({select:u.value.trim(),from:k.value.trim()||null,to:m.value.trim()||null}),U.onclick=()=>{let R=u.value.trim();window.confirm(`Unlock the pipeline lock for "${R}"? Only do this if you're sure no dtk process is actually running against it.`)&&n.submitUnlock({select:R})};function W(){o.classList.remove("open"),r.classList.remove("open")}return i.onclick=W,o.onclick=W,e.append(o,r),{el:r,open(R){R&&(u.value=R),o.classList.add("open"),r.classList.add("open"),P()},close:W,isOpen(){return r.classList.contains("open")},refreshOptions(){h.innerHTML=["*",...n.getSelectOptions()].map(R=>`<option value="${M(R)}"></option>`).join("")},refreshBusyState:P,resetLog(){C=[],_(),x.textContent="",x.className="dtk-ui-log-line"},appendLog(R){if(R.length===0)return;let H=z();C.push(...R),_(),H&&(j.scrollTop=j.scrollHeight)},setLogStatus(R,H){if(R==="running")return;let F=R==="done"&&H===0?"exit-ok":R==="stopped"?"exit-stop":"exit-fail";x.className=`dtk-ui-log-line ${F}`,x.textContent=`\u2500\u2500 ${R} (exit ${H!=null?H:"?"}) \u2500\u2500`}}}function Ct(e){return e==="done"?"var(--st-recovery)":e==="failed"?"var(--st-anomaly)":e==="running"?"var(--clay)":"var(--faint)"}function st(e,n){let o=document.createElement("div");o.className="dtk-ui-drawer-backdrop";let r=document.createElement("div");r.className="dtk-ui-drawer";let t=document.createElement("div");t.className="dtk-ui-drawer-head",t.innerHTML='<span class="dtk-ui-drawer-title">Jobs</span>';let i=document.createElement("button");i.type="button",i.className="dtk-ui-drawer-close",i.textContent="\u2715",t.appendChild(i),r.appendChild(t);let c=document.createElement("div");c.className="dtk-ui-drawer-body",r.appendChild(c);let v=document.createElement("div");v.className="dtk-ui-joblist",c.appendChild(v);function h(){o.classList.remove("open"),r.classList.remove("open")}return i.onclick=h,o.onclick=h,e.append(o,r),{el:r,open(){o.classList.add("open"),r.classList.add("open")},close:h,isOpen(){return r.classList.contains("open")},render(u,f,w){var g;if(u.length===0){v.innerHTML='<div class="dtk-ui-empty">No jobs yet.</div>';return}v.innerHTML="";for(let s of u){let p=document.createElement("div");p.className="dtk-ui-jobrow"+(s.id===w?" active":"");let k=s.status==="running"?" pulse":"",S=_e(s.started_at,(g=s.finished_at)!=null?g:f),m=document.createElement("div");m.className="dtk-ui-jobrow-top",m.innerHTML=`<span class="dtk-ui-jobrow-status"><span class="dtk-ui-jobrow-dot${k}" style="background:${Ct(s.status)}"></span>${M(s.kind)} \xB7 ${M(s.status)}</span><span class="dtk-ui-jobrow-meta">${M(ve(f,s.started_at))} \xB7 ${M(S)}</span>`,p.appendChild(m);let L=document.createElement("div");L.className="dtk-ui-jobrow-label",L.textContent=s.label,p.appendChild(L);let d=document.createElement("div");if(d.className="dtk-ui-jobrow-actions",s.status==="running"){let b=document.createElement("button");b.type="button",b.className="dtk-ui-actionbtn",b.textContent="Stop",b.onclick=T=>{T.stopPropagation(),n.onStop(s.id)},d.appendChild(b)}if(s.kind==="tune"&&s.url){let b=document.createElement("a");b.className="dtk-ui-joblink",b.href=s.url,b.target="_blank",b.rel="noopener",b.textContent="Open tuner",b.onclick=T=>T.stopPropagation(),d.appendChild(b)}d.childElementCount>0&&p.appendChild(d),p.onclick=()=>n.onFollow(s.id),v.appendChild(p)}}}}var lt=`# New metric \u2014 edit the query and name, then Create.
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
`;function Le(e,n,o){var X;let r=n.mode==="create",t=!1,i=!1,c=ye(e,{modalClass:"dtk-ui-editor-modal",onRequestClose:()=>{j()}}),{modal:v}=c,h=document.createElement("div");h.className="dtk-ui-editor-head";let u=document.createElement("div");u.className="dtk-ui-editor-titlewrap";let f=document.createElement("span");if(f.className="dtk-ui-editor-title",f.textContent=r?"New metric":`Edit ${(X=n.name)!=null?X:""}`,u.appendChild(f),!r&&n.file){let x=document.createElement("span");x.className="dtk-ui-editor-sub",x.textContent=n.file,u.appendChild(x)}h.appendChild(u);let w=document.createElement("button");w.type="button",w.className="dtk-ui-overlay-close",w.textContent="\u2715",w.title="Close (Esc)",w.onclick=()=>{j()},h.appendChild(w),v.appendChild(h);let g=document.createElement("div");g.className="dtk-ui-editor-body",v.appendChild(g);let s=null;if(r){let x=document.createElement("div");x.className="dtk-ui-editor-field",x.innerHTML='<span class="dtk-ui-field-label">Folder</span>',s=document.createElement("input"),s.type="text",s.className="dtk-ui-input",s.placeholder="optional subfolder under metrics/",x.appendChild(s);let C=document.createElement("div");C.className="dtk-ui-editor-hint",C.textContent="The file is written as metrics/[folder/]<name>.yml \u2014 <name> comes from the YAML below.",x.appendChild(C),g.appendChild(x)}let p=document.createElement("textarea");p.className="dtk-ui-editor-textarea",p.spellcheck=!1,p.autocapitalize="off",p.value=n.text,p.addEventListener("input",()=>{t=!0}),p.addEventListener("keydown",x=>{if(x.key==="Tab"){x.preventDefault();let C=p.selectionStart,_=p.selectionEnd;p.value=`${p.value.slice(0,C)}  ${p.value.slice(_)}`,p.selectionStart=p.selectionEnd=C+2,t=!0;return}(x.ctrlKey||x.metaKey)&&x.key.toLowerCase()==="s"&&(x.preventDefault(),U())}),g.appendChild(p);let k=document.createElement("div");k.className="dtk-ui-editor-error",k.style.display="none",v.appendChild(k);function S(x){k.textContent=x,k.style.display=""}function m(){k.style.display="none",k.textContent=""}let L=document.createElement("div");L.className="dtk-ui-editor-foot";let d=document.createElement("div");d.className="dtk-ui-editor-foot-left";let b=document.createElement("div");b.className="dtk-ui-editor-foot-right",L.append(d,b),v.appendChild(L);let T=document.createElement("button");T.type="button",T.className="dtk-ui-btn primary";let N=r?"Create metric":"Save changes";T.textContent=N,T.onclick=()=>{U()},b.appendChild(T);function $(){let x=document.createElement("button");return x.type="button",x.className="dtk-ui-btn danger",x.textContent="Delete metric\u2026",x.onclick=()=>J(),x}r||d.appendChild($());function J(){var A,W;let x=(A=n.name)!=null?A:"",C=(W=n.file)!=null?W:"";d.innerHTML="";let _=document.createElement("div");_.className="dtk-ui-editor-confirm";let z=document.createElement("span");z.className="dtk-ui-editor-confirm-text",z.innerHTML=`Delete <b>${M(x)}</b>? The file <code>${M(C)}</code> is archived to <code>metrics/.history/</code> and removed. Data rows in the <code>_dtk_*</code> tables remain until <code>dtk clean</code>.`,_.appendChild(z);let K=document.createElement("button");K.type="button",K.className="dtk-ui-btn danger",K.textContent="Delete metric",K.onclick=()=>{te(x,K,P)};let P=document.createElement("button");P.type="button",P.className="dtk-ui-btn",P.textContent="Cancel",P.onclick=()=>{d.innerHTML="",d.appendChild($())},_.append(K,P),d.appendChild(_)}function D(x){i=x,T.disabled=x,T.textContent=x?"Saving\u2026":N}async function U(){var x;if(!i){m(),D(!0);try{let C=p.value,_=r?await qe({text:C,folder:(s==null?void 0:s.value.trim())||void 0}):await Fe((x=n.name)!=null?x:"",{text:C,digest:n.digest});t=!1,o.onSaved(_,n.mode),q()}catch(C){S(C.message)}finally{D(!1)}}}async function te(x,C,_){if(!i){m(),i=!0,C.disabled=!0,_.disabled=!0,C.textContent="Deleting\u2026";try{let z=await Ue(x);t=!1,o.onDeleted(z),q()}catch(z){S(z.message),C.disabled=!1,_.disabled=!1,C.textContent="Delete metric"}finally{i=!1}}}function q(){c.close(),o.onClose()}function j(){return t&&!window.confirm("Discard unsaved changes?")?!1:(q(),!0)}return p.focus(),{close:q,requestClose:j}}var Tt=3,St=[{value:"24h",label:"24h"},{value:"7d",label:"7d"},{value:"30d",label:"30d"},{value:"90d",label:"90d"},{value:"all",label:"All"}];function Lt(e,n){Ye(),n.classList.add(oe),n.innerHTML="";let o=document.createElement("div");o.className=`${oe}-root`,n.appendChild(o);let r=e.metrics,t={windowPreset:e.initial_window||"30d",metrics:r.map(de),jobs:[],followedJobId:null,followOffset:0,tagFilter:null,sort:{key:"alerts",dir:Se.alerts}},i=null,c=null,v,h;function u(){let a=new Set,l=new Set;for(let y of r){a.add(y.name);for(let B of y.tags)l.add(B)}return[...a,...[...l].map(y=>`tag:${y}`)]}function f(){let a=t.jobs.find(l=>l.status==="running"&&l.kind!=="tune");return a?{busy:!0,reason:`a pipeline job is already running (${a.label})`}:{busy:!1,reason:""}}let w=document.createElement("div");w.className="dtk-ui-header",o.appendChild(w);let g=document.createElement("div");g.className="dtk-ui-brand",g.innerHTML=`<span class="dtk-ui-brand-dot"></span><span class="dtk-ui-brand-name">detectkit \xB7 <b>${M(e.project)}</b></span>`,w.appendChild(g);let s=document.createElement("div");s.className="dtk-ui-header-right",w.appendChild(s);let p=document.createElement("div");p.className="dtk-ui-seg";for(let a of St){let l=document.createElement("button");l.type="button",l.className="dtk-ui-seg-btn"+(t.windowPreset===a.value?" on":""),l.textContent=a.label,l.onclick=()=>{t.windowPreset!==a.value&&(t.windowPreset=a.value,p.querySelectorAll(".dtk-ui-seg-btn").forEach(y=>y.classList.remove("on")),l.classList.add("on"),i&&i.setWindow(a.value),ae())},p.appendChild(l)}s.appendChild(p);let k=document.createElement("button");k.type="button",k.className="dtk-ui-iconbtn",k.title="Refresh overview",k.textContent="\u27F3",k.onclick=()=>{ae()},s.appendChild(k);let S=document.createElement("button");S.type="button",S.className="dtk-ui-runbtn",S.textContent="Run pipeline",S.onclick=()=>z(),s.appendChild(S);let m=document.createElement("button");m.type="button",m.className="dtk-ui-newbtn",m.textContent="New metric",m.onclick=()=>U(),s.appendChild(m);let L=document.createElement("span");L.className="dtk-ui-progresschip",L.style.display="none",s.appendChild(L);function d(a,l){if(l===0||a>=l){L.style.display="none";return}L.textContent=`${a}/${l}`,L.style.display=""}let b=document.createElement("button");b.type="button",b.className="dtk-ui-jobschip",b.innerHTML='<span class="dtk-ui-jobschip-dot"></span><span>idle</span>',b.onclick=()=>{_.isOpen()?_.close():K()},s.appendChild(b);function T(){let a=t.jobs.find(B=>B.status==="running");b.classList.toggle("running",!!a);let l=a?`${a.kind} ${a.label}`:"idle",y=b.querySelector("span:last-child");y&&(y.textContent=l),b.title=a?`Started ${new Date(a.started_at).toLocaleString()}`:"No jobs running"}let N=document.createElement("div");N.className="dtk-ui-content",o.appendChild(N);function $(){var O,G;N.innerHTML="";let a=r.length;if(a===0){let E=document.createElement("div");E.className="dtk-ui-empty",E.textContent="No metrics found for this project/selector.",N.appendChild(E);return}let l=t.metrics.filter(E=>!E.pending),y=l.filter(E=>E.error!==null);if(l.length===a&&y.length===a){let E=document.createElement("div");E.className="dtk-ui-banner";let se=(G=(O=y[0])==null?void 0:O.error)!=null?G:"unknown error";E.innerHTML=`<span>Failed to load overview: every metric failed (${M(se)}).</span>`;let Q=document.createElement("button");Q.type="button",Q.className="dtk-ui-banner-retry",Q.textContent="Retry",Q.onclick=()=>{ae()},E.appendChild(Q),N.appendChild(E)}N.appendChild(We(t.metrics)),N.appendChild(Ge(l,t.tagFilter,E=>{t.tagFilter=E,$()}));let B=t.tagFilter===null?t.metrics:t.metrics.filter(E=>t.tagFilter===fe?E.tags.length===0:E.tags.includes(t.tagFilter)),Y=nt(B,t.sort,Date.now(),{onOpen:J,onTune:E=>{ce(E)},onRun:E=>z(E),onEdit:E=>{te(E)},onSortChange:E=>{t.sort=t.sort.key===E?{key:E,dir:t.sort.dir==="asc"?"desc":"asc"}:{key:E,dir:Se[E]},$()}});N.appendChild(Y.el),Y.paint()}function J(a){D()&&(i&&i.close(),i=ot(o,a,t.windowPreset,{onTune:l=>{ce(l)},onClose:()=>{i=null}}))}function D(){return c?c.requestClose():!0}function U(){D()&&(i&&(i.close(),i=null),c=Le(o,{mode:"create",text:lt},{onSaved:(a,l)=>q(a,l),onDeleted:()=>{},onClose:()=>{c=null}}))}async function te(a){if(!D())return;let l;try{l=await ze(a)}catch(y){I(o,"error",y.message);return}D()&&(i&&(i.close(),i=null),c=Le(o,{mode:"edit",name:l.name,file:l.file,text:l.text,digest:l.digest},{onSaved:(y,B)=>q(y,B),onDeleted:y=>j(y),onClose:()=>{c=null}}))}function q(a,l){I(o,"info",`Metric '${a.name}' ${l==="create"?"created":"saved"}.`),a.note&&I(o,"info",a.note),l==="edit"&&!a.renamed_from?x(a.name,a.metrics):X(a.metrics)}function j(a){I(o,"info",`Metric '${a.name}' deleted (archived).`),a.note&&I(o,"info",a.note),X(a.metrics)}function X(a){r=a,C.refreshOptions(),ae()}function x(a,l){r=l,C.refreshOptions();let y=l.find(O=>O.name===a),B=t.metrics.findIndex(O=>O.name===a);if(!y||B===-1){ae();return}let Y=ne;t.metrics[B]=de(y),$(),Te(a,t.windowPreset).then(O=>{if(Y!==ne)return;O.pending=!1;let G=t.metrics.findIndex(E=>E.name===a);G!==-1&&(t.metrics[G]=O),$()}).catch(O=>{if(Y!==ne)return;let G=t.metrics.findIndex(E=>E.name===a);G!==-1&&(t.metrics[G]={...de(y),pending:!1,error:O.message}),$()})}let C=at(o,{submitRun:a=>{R(a)},submitAutotune:a=>{H(a)},submitUnlock:a=>{F(a)},getSelectOptions:u,isPipelineBusy:f}),_=st(o,{onFollow:a=>be(a),onStop:a=>{V(a)}});function z(a){_.close(),C.refreshOptions(),C.refreshBusyState(),C.open(a)}function K(){C.close(),_.render(t.jobs,Date.now(),t.followedJobId),_.open(),Ne()}function P(a,l,y,B){let Y={id:y,kind:a,label:l,status:"running",returncode:null,url:B,started_at:Date.now(),finished_at:null};t.jobs=[Y,...t.jobs.filter(O=>O.id!==y)],Re(),Ne(),ue()}let A=!1,W=new Set;async function R(a){if(!A){A=!0;try{let l=await je(a);P("run",`run --select ${a.select}`,l.job_id,null),be(l.job_id)}catch(l){I(o,"error",l.message)}finally{A=!1}}}async function H(a){if(!A){A=!0;try{let l=await Ae(a);P("autotune",`autotune --select ${a.select}`,l.job_id,null),be(l.job_id)}catch(l){I(o,"error",l.message)}finally{A=!1}}}async function F(a){if(!A){A=!0;try{let l=await Be(a);P("unlock",`unlock --select ${a.select}`,l.job_id,null),be(l.job_id)}catch(l){I(o,"error",l.message)}finally{A=!1}}}async function ce(a){if(!W.has(a)){W.add(a),I(o,"info",`Opening tuner for ${a}\u2026`);try{let l=await Ie({metric:a});P("tune",`tune --select ${a}`,l.job_id,l.url),window.open(l.url,"_blank")}catch(l){I(o,"error",l.message)}finally{W.delete(a)}}}async function V(a){try{await Je(a),I(o,"info","Stop requested."),ue()}catch(l){I(o,"error",l.message)}}function be(a){t.followedJobId=a,t.followOffset=0,z(),C.resetLog(),ct(a)}function Re(){T(),_.render(t.jobs,Date.now(),t.followedJobId),C.refreshBusyState()}async function ue(){try{let a=await He();t.jobs=a.jobs}catch{}Re()}function Ne(){if(v!==void 0)return;let a=()=>{ue().then(()=>{v=_.isOpen()||t.jobs.some(y=>y.status==="running")?window.setTimeout(a,2e3):void 0})};v=window.setTimeout(a,2e3)}function dt(){h!==void 0&&(window.clearTimeout(h),h=void 0)}function ct(a){dt();let l=()=>{Oe(a,t.followOffset).then(y=>{if(t.followedJobId===a){if(C.appendLog(y.lines),t.followOffset=y.next_offset,y.status!=="running"){C.setLogStatus(y.status,y.returncode),h=void 0,ue();return}h=window.setTimeout(l,1e3)}}).catch(y=>{I(o,"error",`job ${a}: ${y.message}`),h=void 0})};h=window.setTimeout(l,0)}let ne=0;async function ae(){let a=++ne,l=t.windowPreset,y=r;if(t.metrics=y.map(de),k.classList.add("spinning"),d(0,y.length),$(),y.length===0){k.classList.remove("spinning"),d(0,0);return}let B=[...y],Y=0;async function O(){for(;;){if(a!==ne)return;let E=B.shift();if(!E)return;let se;try{se=await Te(E.name,l),se.pending=!1}catch(we){se={...de(E),pending:!1,error:we.message}}if(a!==ne)return;let Q=t.metrics.findIndex(we=>we.name===E.name);Q!==-1&&(t.metrics[Q]=se),Y++,d(Y,y.length),$()}}let G=Math.min(Tt,y.length);await Promise.all(Array.from({length:G},()=>O())),a===ne&&(k.classList.remove("spinning"),d(Y,y.length),C.refreshOptions())}$(),C.refreshOptions(),ae(),ue()}window.__DTK_UI__={render:Lt};})();
