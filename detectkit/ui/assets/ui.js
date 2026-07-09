"use strict";(()=>{var k=e=>String(e).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");function ke(e){let n=e/60;return e>=86400&&e%86400===0?e/86400+"d":e>=3600&&e%3600===0?e/3600+"h":n>=1&&e%60===0?n+"min":e+"s"}function F(e){return e==null||!Number.isFinite(e)?"\u2014":(e*100).toFixed(1)+"%"}function oe(e){return e==null||!Number.isFinite(e)?"\u2014":Math.round(e).toLocaleString("en-US")}function V(e){return e==null||!Number.isFinite(e)?"\u2014":`\u2248${e>=9.5?e.toFixed(0):e.toFixed(1)}/day`}function le(e,n){let r=Math.max(0,e-n),t=Math.round(r/6e4);if(t<1)return"just now";if(t<60)return`${t}m ago`;let o=Math.floor(t/60);if(o<24)return`${o}h ago`;let a=Math.floor(o/24);return a<30?`${a}d ago`:`${Math.floor(a/30)}mo ago`}function he(e,n){let r=Math.max(0,Math.round((n-e)/1e3));if(r<60)return`${r}s`;let t=Math.floor(r/60),o=r%60;if(t<60)return o?`${t}m ${o}s`:`${t}m`;let a=Math.floor(t/60),c=t%60;return`${a}h ${String(c).padStart(2,"0")}m`}function me(e){return new Date(e).toISOString().slice(0,19).replace("T"," ")}function de(e){let n=Math.round(e/60);if(n<60)return`${n}m`;let r=Math.floor(n/60),t=n%60;if(r<24)return r+"h"+(t?` ${t}m`:"");let o=Math.floor(r/24),a=r%24;return o+"d"+(a?` ${a}h`:"")}function xe(e,n){let r=new Map;for(let t of e){let o=n(t),a=r.get(o);a?a.push(t):r.set(o,[t])}return r}var Ye=new URLSearchParams(location.search).get("token")||"";function fe(e,n){let r=new URL(e,location.origin);if(r.searchParams.set("token",Ye),n)for(let[t,o]of Object.entries(n))r.searchParams.set(t,o);return r.toString()}function be(e,n){return fe(`/metric/${encodeURIComponent(e)}`,{window:n})}async function ye(e){let n=await e.text().catch(()=>"");return new Error(n||`HTTP ${e.status}`)}async function ge(e,n){let r=await fetch(fe(e,n));if(!r.ok)throw await ye(r);return r.json()}async function re(e,n){let r=await fetch(fe(e),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(n)});if(!r.ok)throw await ye(r);return r.json()}function we(e,n){return ge(`/api/stats/${encodeURIComponent(e)}`,{window:n})}function Te(){return ge("/api/jobs")}function Ce(e,n){return ge(`/api/job/${encodeURIComponent(e)}`,{offset:String(n)})}function Me(e){return re("/api/run",e)}function Se(e){return re("/api/autotune",e)}function Ee(e){return re("/api/unlock",e)}function Le(e){return re("/api/tune",e)}function $e(e){return re(`/api/job/${encodeURIComponent(e)}/stop`,{})}var Y="dtk-ui",Re=!1;function Ne(){if(Re)return;Re=!0;let e=`
.${Y}{
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
.${Y} *{box-sizing:border-box;}
.${Y} a{color:var(--clay);}
.${Y}-root{max-width:1400px;margin:0 auto;padding:16px 20px 56px;display:flex;
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
`,n=document.createElement("style");n.setAttribute("data-dtk-ui",""),n.textContent=e,document.head.appendChild(n)}var K=null;function Ke(e){return K&&K.isConnected||(K=document.createElement("div"),K.className="dtk-toasts",e.appendChild(K)),K}function B(e,n,r){let t=Ke(e),o=document.createElement("div");o.className=`dtk-toast dtk-toast-${n}`,o.textContent=r,t.appendChild(o),window.setTimeout(()=>{o.classList.add("dtk-toast-out"),window.setTimeout(()=>o.remove(),220)},5e3)}function W(e,n,r,t){let o="dtk-ui-tile"+(t!=null&&t.err?" err":""),a=t!=null&&t.warn?"dtk-ui-tile-sub warn":"dtk-ui-tile-sub";return`<div class="${o}"><div class="dtk-ui-tile-val">${k(e)}</div><div class="dtk-ui-tile-label">${k(n)}</div>`+(r?`<div class="${a}">${k(r)}</div>`:"")+"</div>"}function Pe(e){let n=document.createElement("div");n.className="dtk-ui-tiles";let r=e.length,t=e.filter(s=>s.enabled).length,o=e.filter(s=>!s.pending),a=0,c=0,h=0,w=0,p=!1;for(let s of o)a+=s.alerts.anomaly,c+=s.alerts.no_data,s.alerts.anomaly>0&&h++,s.alerts.per_day!==null&&(w+=s.alerts.per_day,p=!0);let m=[];for(let s of o)if(s.enabled){if(s.last_point===null){m.push({m:s,lag:1/0});continue}s.lag_seconds!==null&&s.interval_seconds>0&&s.lag_seconds>2*s.interval_seconds&&m.push({m:s,lag:s.lag_seconds})}m.sort((s,g)=>g.lag-s.lag);let x=m.length===0?void 0:`worst: ${m[0].m.name}${Number.isFinite(m[0].lag)?` (${de(m[0].lag)})`:" (no data)"}`;n.innerHTML=W(`${t}/${r}`,"Metrics","enabled / total")+W(oe(a),"Alerts in window",p?V(w):void 0)+W(oe(c),"No-data events")+W(oe(h),"Metrics alerting")+W(oe(m.length),"Stale metrics",x,{warn:m.length>0,err:m.length>0});let b=o.filter(s=>s.quality!==null);if(b.length>0){let s=0,g=0,v=0,T=0,u=0;for(let S of b){let E=S.quality;E&&(s+=E.caught,g+=E.incidents_in_window,v+=E.false_alerts,T+=S.alerts.anomaly,S.budget>u&&(u=S.budget))}let L=g>0?s/g:null,l=T>0?v/T:null,f=l!==null&&u>0&&l>u;n.innerHTML+=W(F(L),"Labeled recall",`${b.length} metric(s) labeled`)+W(F(l),"False-alert rate",f?`\u25B2 over ${F(u)} budget`:void 0,{warn:f})}return n}var ae="untagged";function We(e){let n=new Map,r=(t,o)=>{let a=n.get(t);a||(a={tag:t,count:0,alerts:0,perDaySum:0,havePerDay:!1},n.set(t,a)),a.count++,a.alerts+=o.alerts.anomaly,o.alerts.per_day!==null&&(a.perDaySum+=o.alerts.per_day,a.havePerDay=!0)};for(let t of e)if(t.tags.length===0)r(ae,t);else for(let o of t.tags)r(o,t);return[...n.values()].sort((t,o)=>o.count-t.count||t.tag.localeCompare(o.tag))}function De(e,n,r){let t=document.createElement("div");t.className="dtk-ui-tags";let o=document.createElement("button");o.type="button",o.className="dtk-ui-tag"+(n===null?" on":""),o.innerHTML=`<span class="dtk-ui-tag-name">All</span><span class="dtk-ui-tag-n">${e.length}</span>`,o.onclick=()=>r(null),t.appendChild(o);for(let a of We(e)){let c=document.createElement("button");c.type="button",c.className="dtk-ui-tag"+(n===a.tag?" on":"");let h=a.havePerDay?` \xB7 ${V(a.perDaySum)}`:"";c.innerHTML=`<span class="dtk-ui-tag-name">${k(a.tag===ae?ae:`#${a.tag}`)}</span><span class="dtk-ui-tag-n">${a.count} metric${a.count===1?"":"s"}</span><span class="dtk-ui-tag-n">${a.alerts} alert${a.alerts===1?"":"s"}</span>`+(h?`<span class="dtk-ui-tag-sub">${k(h)}</span>`:""),c.onclick=()=>r(a.tag),t.appendChild(c)}return t}var Ge={"--term-bg":"#211e1a","--clay":"#d15b36","--st-anomaly":"#d63232","--st-recovery":"#36a64f","--st-nodata":"#f0ad4e","--st-error":"#5a7a8c","--faint":"#9a9384","--muted":"#6e675b","--border":"#332f29","--term-border":"#332f29"};function ce(e){return getComputedStyle(document.documentElement).getPropertyValue(e).trim()||Ge[e]||"#888"}function Xe(e){let n=e.replace("#","").trim();n.length===3&&(n=n[0]+n[0]+n[1]+n[1]+n[2]+n[2]);let r=parseInt(n,16);return n.length!==6||Number.isNaN(r)?[209,91,54]:[r>>16&255,r>>8&255,r&255]}function _e(e,n){let[r,t,o]=Xe(e);return`rgba(${r},${t},${o},${n})`}var vt=Number.isFinite;var He=140,je=30;function Oe(e,n,r){let t=Math.max(1,window.devicePixelRatio||1);e.style.width=`${He}px`,e.style.height=`${je}px`,e.width=Math.round(He*t),e.height=Math.round(je*t);let o=e.getContext("2d");if(!o||(o.clearRect(0,0,e.width,e.height),n.length===0))return;let a=3*t,c=e.width,h=e.height,w=n[0].t,p=n[n.length-1].t,m=p-w||1,x=l=>a+(l-w)/m*Math.max(1,c-2*a),b=1/0,s=-1/0;for(let l of n)l.v!==null&&Number.isFinite(l.v)&&(l.v<b&&(b=l.v),l.v>s&&(s=l.v));let g=!Number.isFinite(b)||!Number.isFinite(s);g&&(b=0,s=1),s<=b&&(s=b+1);let v=l=>h-a-(l-b)/(s-b)*Math.max(1,h-2*a);if(g){let l=h/2;o.strokeStyle=_e(ce("--faint"),.5),o.lineWidth=1*t,o.setLineDash([2*t,2*t]),o.beginPath(),o.moveTo(a,l),o.lineTo(c-a,l),o.stroke(),o.setLineDash([]);return}o.strokeStyle=ce("--term-text"),o.lineWidth=1*t,o.lineJoin="round",o.beginPath();let T=!1;for(let l of n){if(l.v===null||!Number.isFinite(l.v)){T=!1;continue}let f=x(l.t),S=v(l.v);T?o.lineTo(f,S):(o.moveTo(f,S),T=!0)}if(o.stroke(),r.length===0)return;let u=[];for(let l of n)l.v!==null&&Number.isFinite(l.v)&&u.push([l.t,l.v]);let L=l=>{if(u.length===0)return null;if(l<=u[0][0])return u[0][1];if(l>=u[u.length-1][0])return u[u.length-1][1];for(let f=1;f<u.length;f++){let[S,E]=u[f];if(l<=S){let[R,P]=u[f-1],O=S===R?0:(l-R)/(S-R);return P+(E-P)*O}}return u[u.length-1][1]};o.fillStyle=ce("--st-anomaly");for(let l of r){if(l<w||l>p)continue;let f=L(l);f!==null&&(o.beginPath(),o.arc(x(l),v(f),2*t,0,Math.PI*2),o.fill())}}var ue='<span class="dtk-ui-pending">\xB7\xB7\xB7</span>';function pe(e){return{name:e.name,dir:e.dir,file:e.file,tags:e.tags,enabled:e.enabled,interval_seconds:e.interval_seconds,detectors:[],alert_rule:null,last_point:null,first_point_in_window:null,lag_seconds:null,locked:!1,points:0,flagged:0,anomaly_rate:null,alerts:{anomaly:0,recovery:0,no_data:0,per_day:null,last_ts:null},quality:null,budget:0,spark:[],spark_anoms:[],error:null,pending:!0}}var ve={alerts:"desc",name:"asc",rate:"desc",freshness:"desc"};function Je(e){var o;if(e.pending)return{color:"var(--faint)",title:"loading\u2026",rank:0};if(!e.enabled)return{color:"var(--faint)",title:"disabled",rank:-1};if(e.last_point===null)return{color:"var(--st-anomaly)",title:"no datapoints loaded yet",rank:1/0};let n=(o=e.lag_seconds)!=null?o:0,r=e.interval_seconds>0?n/e.interval_seconds:0,t=`lag ${de(Math.max(0,n))} (${r.toFixed(1)}\xD7 interval) \xB7 last point ${me(e.last_point)} UTC`;return r<2?{color:"var(--st-recovery)",title:t,rank:n}:r<6?{color:"var(--st-nodata)",title:t,rank:n}:{color:"var(--st-anomaly)",title:t,rank:n}}function Qe(e){return e.length===0?"":`<div class="dtk-ui-tagchips">${e.map(n=>`<span class="dtk-ui-tagchip">${k(n)}</span>`).join("")}</div>`}function Ve(e){let n=e.quality;if(!n)return'<span class="dtk-ui-quality empty">\u2014</span>';let r=`Incidents: ${n.incidents} (${n.incidents_in_window} in window) \xB7 caught ${n.caught} \xB7 false alerts ${n.false_alerts} \xB7 reviewed ${n.reviewed} (valid ${n.reviewed_valid}, false ${n.reviewed_false}) \xB7 ${n.labels_file}`;return`<span class="dtk-ui-quality" title="${k(r)}"><span class="dtk-ui-quality-chip">R <b>${k(F(n.recall))}</b></span> \xB7 <span class="dtk-ui-quality-chip">FDR <b>${k(F(n.fdr))}</b></span> \xB7 <span class="dtk-ui-quality-chip">\u2713${n.reviewed_valid}</span></span>`}function Ze(e){let n=e.alert_rule?`min_detectors=${e.alert_rule.min_detectors} \xB7 direction=${e.alert_rule.direction} \xB7 consecutive=${e.alert_rule.consecutive} (${e.alert_rule.enabled}/${e.alert_rule.configs} config(s) enabled)`:"no alerting configured";return`detectors: ${e.detectors.join(", ")||"\u2014"}
alert rule: ${n}
file: ${e.file}`}function et(e,n,r,t){let o=document.createElement("tr");o.className="dtk-ui-row"+(e.enabled?"":" disabled")+(e.error?" errored":"")+(e.pending?" pending":"");let a=Je(e),c=document.createElement("td");c.className="dtk-ui-dotcell",c.innerHTML=`<span class="dtk-ui-dot" style="background:${a.color}" title="${k(a.title)}"></span>`,o.appendChild(c);let h=document.createElement("td");h.className="dtk-ui-namecell";let w=e.error?`<span class="dtk-ui-err-badge" title="${k(e.error)}">!</span>`:"";h.title=Ze(e),h.innerHTML=`<span class="dtk-ui-name">${k(e.name)}</span>${w}${Qe(e.tags)}`,o.appendChild(h);let p=document.createElement("td");p.innerHTML=`<span class="dtk-ui-interval">${k(ke(e.interval_seconds))}</span>`,o.appendChild(p);let m=document.createElement("td");if(m.className="dtk-ui-sparkcell",e.pending)m.innerHTML='<span class="dtk-ui-spark-loading">loading\u2026</span>';else if(e.spark.length===0)m.innerHTML='<span class="dtk-ui-spark-empty">no data yet</span>';else{let f=document.createElement("canvas");f.className="dtk-spark",m.appendChild(f),t.push({canvas:f,points:e.spark.map(([S,E])=>({t:S,v:E})),anoms:e.spark_anoms})}o.appendChild(m);let x=document.createElement("td");if(x.className="dtk-ui-alertscell",e.pending)x.innerHTML=ue;else{let f=e.quality!==null&&e.quality.fdr!==null&&e.quality.fdr>e.budget,S="dtk-ui-alerts-n"+(e.alerts.anomaly>0?" hasany":"")+(f?" overbudget":""),E=e.alerts.per_day!==null?`<span class="dtk-ui-alerts-sub">\xB7 ${k(V(e.alerts.per_day))}</span>`:"";x.innerHTML=`<span class="${S}">${e.alerts.anomaly}</span>${E}`}o.appendChild(x);let b=document.createElement("td");e.pending?b.innerHTML=ue:e.alerts.last_ts!==null?b.innerHTML=`<span class="dtk-ui-lastalert" title="${k(me(e.alerts.last_ts))} UTC">${k(le(n,e.alerts.last_ts))}</span>`:b.innerHTML='<span class="dtk-ui-lastalert">\u2014</span>',o.appendChild(b);let s=document.createElement("td");s.innerHTML=e.pending?ue:`<span class="dtk-ui-rate">${k(F(e.anomaly_rate))}</span>`,o.appendChild(s);let g=document.createElement("td");g.innerHTML=e.pending?ue:Ve(e),o.appendChild(g);let v=document.createElement("td");v.innerHTML=e.locked?'<span class="dtk-ui-lock" title="pipeline lock currently held for this metric">LOCK</span>':"",o.appendChild(v);let T=document.createElement("td");T.className="dtk-ui-actionscell";let u=document.createElement("button");u.type="button",u.className="dtk-ui-actionbtn",u.textContent="Open",u.onclick=()=>r.onOpen(e.name);let L=document.createElement("button");L.type="button",L.className="dtk-ui-actionbtn",L.textContent="Tune",L.onclick=()=>r.onTune(e.name);let l=document.createElement("button");return l.type="button",l.className="dtk-ui-actionbtn",l.textContent="Run",l.onclick=()=>r.onRun(e.name),T.append(u,L,l),o.appendChild(T),o}function Ae(e,n){var r;switch(n){case"alerts":return e.alerts.anomaly;case"name":return e.name.toLowerCase();case"rate":return(r=e.anomaly_rate)!=null?r:-1;case"freshness":return Je(e).rank}}function tt(e,n){let r=e.filter(a=>a.enabled),t=e.filter(a=>!a.enabled),o=n.dir==="asc"?1:-1;return r.sort((a,c)=>{let h=Ae(a,n.key),w=Ae(c,n.key);return h<w?-1*o:h>w?1*o:a.name.localeCompare(c.name)}),t.sort((a,c)=>a.name.localeCompare(c.name)),[...r,...t]}var nt=[{label:"\u25CF",key:"freshness"},{label:"Name",key:"name"},{label:"Interval",key:null},{label:"Trend",key:null},{label:"Alerts",key:"alerts"},{label:"Last alert",key:null},{label:"Rate",key:"rate"},{label:"Quality",key:null},{label:"",key:null},{label:"",key:null}];function ot(e,n){let r=document.createElement("tr");for(let t of nt){let o=document.createElement("th");if(t.key){o.className="dtk-ui-th";let a=e.key===t.key?`<span class="dtk-ui-th-arrow">${e.dir==="asc"?"\u25B5":"\u25BE"}</span>`:"";o.innerHTML=`${k(t.label)}${a}`,o.onclick=()=>n.onSortChange(t.key)}else o.textContent=t.label;r.appendChild(o)}return r}function rt(e){return e===""?"metrics/":`metrics/${e}/`}function Be(e,n,r,t){var w;let o=[],a=document.createElement("div");if(a.className="dtk-ui-table-wrap",e.length===0)return a.innerHTML='<div class="dtk-ui-empty">No metrics match the current filter.</div>',{el:a,paint:()=>{}};let c=xe(e,p=>p.dir),h=[...c.keys()].sort((p,m)=>p===m?0:p===""?-1:m===""?1:p.localeCompare(m));for(let p of h){let m=(w=c.get(p))!=null?w:[],x=document.createElement("div");x.className="dtk-ui-group";let b=m.reduce((u,L)=>u+L.alerts.anomaly,0),s=document.createElement("div");s.className="dtk-ui-group-head",s.innerHTML=`<span class="dtk-ui-group-name">${k(rt(p))}</span><span class="dtk-ui-group-sub">${m.length} metric${m.length===1?"":"s"} \xB7 ${b} alert${b===1?"":"s"}</span>`,x.appendChild(s);let g=document.createElement("table");g.className="dtk-ui-table";let v=document.createElement("thead");v.appendChild(ot(n,t)),g.appendChild(v);let T=document.createElement("tbody");for(let u of tt(m,n))T.appendChild(et(u,r,t,o));g.appendChild(T),x.appendChild(g),a.appendChild(x)}return{el:a,paint:()=>{for(let p of o)Oe(p.canvas,p.points,p.anoms)}}}function Ie(e,n,r,t){let o=document.createElement("div");o.className="dtk-ui-overlay";let a=document.createElement("div");a.className="dtk-ui-overlay-modal",o.appendChild(a);let c=document.createElement("div");c.className="dtk-ui-overlay-head",c.innerHTML=`<span><span class="dtk-ui-overlay-title">${k(n)}</span><span class="dtk-ui-overlay-sub">window: ${k(r)}</span></span>`;let h=document.createElement("div");h.className="dtk-ui-overlay-actions";let w=document.createElement("button");w.type="button",w.className="dtk-ui-btn",w.textContent="Tune",w.onclick=()=>t.onTune(n);let p=document.createElement("button");p.type="button",p.className="dtk-ui-overlay-close",p.textContent="\u2715",p.title="Close (Esc)",h.append(w,p),c.appendChild(h),a.appendChild(c);let m=document.createElement("div");m.className="dtk-ui-overlay-body";let x=document.createElement("div");x.className="dtk-ui-overlay-loading",x.innerHTML=`<span class="dtk-ui-overlay-spinner"></span><span>Building the report for <b>${k(n)}</b>\u2026</span>`,m.appendChild(x);let b=document.createElement("iframe");b.title=`detectkit report \u2014 ${n}`,b.style.visibility="hidden",b.addEventListener("load",()=>{x.style.display="none",b.style.visibility="visible"}),b.src=be(n,r),m.appendChild(b),a.appendChild(m),e.appendChild(o);function s(){document.removeEventListener("keydown",g),o.remove(),t.onClose()}function g(v){v.key==="Escape"&&s()}return o.addEventListener("click",v=>{v.target===o&&s()}),p.onclick=s,document.addEventListener("keydown",g),{setWindow(v){let T=c.querySelector(".dtk-ui-overlay-sub");T&&(T.textContent=`window: ${v}`),x.style.display="",b.style.visibility="hidden",b.src=be(n,v)},close:s}}var ze=/^\d{4}-\d{2}-\d{2}( \d{2}:\d{2}:\d{2})?$/,Fe="dtk-ui-run-select-options";function qe(e,n){let r=document.createElement("div");r.className="dtk-ui-drawer-backdrop";let t=document.createElement("div");t.className="dtk-ui-drawer";let o=document.createElement("div");o.className="dtk-ui-drawer-head",o.innerHTML='<span class="dtk-ui-drawer-title">Run pipeline</span>';let a=document.createElement("button");a.type="button",a.className="dtk-ui-drawer-close",a.textContent="\u2715",o.appendChild(a),t.appendChild(o);let c=document.createElement("div");c.className="dtk-ui-drawer-body",t.appendChild(c);let h=document.createElement("div");h.className="dtk-ui-field";let w=document.createElement("datalist");w.id=Fe;let p=document.createElement("input");p.type="text",p.className="dtk-ui-input",p.placeholder="metric name, tag:x, glob, or *",p.value="*",p.setAttribute("list",Fe),h.innerHTML='<span class="dtk-ui-field-label">Select</span>',h.append(p,w),c.appendChild(h);let m=document.createElement("div");m.className="dtk-ui-field",m.innerHTML='<span class="dtk-ui-field-label">Steps</span>';let x=document.createElement("div");x.className="dtk-ui-checks";let b={};for(let C of["load","detect","alert"]){let $=document.createElement("label");$.className="dtk-ui-check";let N=document.createElement("input");N.type="checkbox",N.checked=!0,N.onchange=H,$.append(N,document.createTextNode(C)),x.appendChild($),b[C]=N}m.appendChild(x),c.appendChild(m);let s=document.createElement("div");s.className="dtk-ui-row2";let g=document.createElement("div");g.className="dtk-ui-field",g.innerHTML='<span class="dtk-ui-field-label">From</span>';let v=document.createElement("input");v.type="text",v.className="dtk-ui-input",v.placeholder="YYYY-MM-DD [HH:MM:SS]",v.oninput=H,g.appendChild(v);let T=document.createElement("div");T.className="dtk-ui-field",T.innerHTML='<span class="dtk-ui-field-label">To</span>';let u=document.createElement("input");u.type="text",u.className="dtk-ui-input",u.placeholder="YYYY-MM-DD [HH:MM:SS]",u.oninput=H,T.appendChild(u),s.append(g,T),c.appendChild(s);let L=document.createElement("div");L.className="dtk-ui-checks";let l=document.createElement("label");l.className="dtk-ui-check";let f=document.createElement("input");f.type="checkbox",l.append(f,document.createTextNode("force (skip lock check)"));let S=document.createElement("label");S.className="dtk-ui-check";let E=document.createElement("input");E.type="checkbox",S.append(E,document.createTextNode("full refresh")),L.append(l,S),c.appendChild(L);let R=document.createElement("div");R.className="dtk-ui-btnrow";let P=document.createElement("button");P.type="button",P.className="dtk-ui-btn primary",P.textContent="Run";let O=document.createElement("button");O.type="button",O.className="dtk-ui-btn",O.textContent="Autotune";let _=document.createElement("button");_.type="button",_.className="dtk-ui-btn danger",_.textContent="Unlock",R.append(P,O,_),c.appendChild(R);let D=document.createElement("div");D.className="dtk-ui-reason",c.appendChild(D);let I=document.createElement("div");I.className="dtk-ui-field",I.innerHTML='<span class="dtk-ui-field-label">Log</span>';let A=document.createElement("div");A.className="dtk-ui-log";let Z=document.createElement("div");Z.className="dtk-ui-log-body";let z=document.createElement("div");z.className="dtk-ui-log-line",A.append(Z,z),I.appendChild(A),c.appendChild(I);let q=[];function ee(){Z.innerHTML=q.length===0?'<span class="dtk-ui-log-empty">no output yet</span>':q.map(k).join("<br>")}ee();function G(){return A.scrollTop+A.clientHeight>=A.scrollHeight-24}function te(){return Object.keys(b).filter(C=>b[C].checked)}function H(){let C=n.isPipelineBusy(),$=p.value.trim(),N=v.value.trim()===""||ze.test(v.value.trim()),i=u.value.trim()===""||ze.test(u.value.trim()),d="";C.busy?d=C.reason:$===""?d="select is required":!N||!i?d="from/to must be YYYY-MM-DD or YYYY-MM-DD HH:MM:SS":te().length===0&&(d="pick at least one step to run"),D.textContent=d,P.disabled=d!=="",O.disabled=C.busy||$===""||!N||!i,_.disabled=C.busy||$===""}function ie(){return{select:p.value.trim(),steps:te(),from:v.value.trim()||null,to:u.value.trim()||null,full_refresh:E.checked,force:f.checked}}P.onclick=()=>n.submitRun(ie()),O.onclick=()=>n.submitAutotune({select:p.value.trim(),from:v.value.trim()||null,to:u.value.trim()||null}),_.onclick=()=>{let C=p.value.trim();window.confirm(`Unlock the pipeline lock for "${C}"? Only do this if you're sure no dtk process is actually running against it.`)&&n.submitUnlock({select:C})};function ne(){r.classList.remove("open"),t.classList.remove("open")}return a.onclick=ne,r.onclick=ne,e.append(r,t),{el:t,open(C){C&&(p.value=C),r.classList.add("open"),t.classList.add("open"),H()},close:ne,isOpen(){return t.classList.contains("open")},refreshOptions(){w.innerHTML=["*",...n.getSelectOptions()].map(C=>`<option value="${k(C)}"></option>`).join("")},refreshBusyState:H,resetLog(){q=[],ee(),z.textContent="",z.className="dtk-ui-log-line"},appendLog(C){if(C.length===0)return;let $=G();q.push(...C),ee(),$&&(A.scrollTop=A.scrollHeight)},setLogStatus(C,$){if(C==="running")return;let N=C==="done"&&$===0?"exit-ok":C==="stopped"?"exit-stop":"exit-fail";z.className=`dtk-ui-log-line ${N}`,z.textContent=`\u2500\u2500 ${C} (exit ${$!=null?$:"?"}) \u2500\u2500`}}}function at(e){return e==="done"?"var(--st-recovery)":e==="failed"?"var(--st-anomaly)":e==="running"?"var(--clay)":"var(--faint)"}function Ue(e,n){let r=document.createElement("div");r.className="dtk-ui-drawer-backdrop";let t=document.createElement("div");t.className="dtk-ui-drawer";let o=document.createElement("div");o.className="dtk-ui-drawer-head",o.innerHTML='<span class="dtk-ui-drawer-title">Jobs</span>';let a=document.createElement("button");a.type="button",a.className="dtk-ui-drawer-close",a.textContent="\u2715",o.appendChild(a),t.appendChild(o);let c=document.createElement("div");c.className="dtk-ui-drawer-body",t.appendChild(c);let h=document.createElement("div");h.className="dtk-ui-joblist",c.appendChild(h);function w(){r.classList.remove("open"),t.classList.remove("open")}return a.onclick=w,r.onclick=w,e.append(r,t),{el:t,open(){r.classList.add("open"),t.classList.add("open")},close:w,isOpen(){return t.classList.contains("open")},render(p,m,x){var b;if(p.length===0){h.innerHTML='<div class="dtk-ui-empty">No jobs yet.</div>';return}h.innerHTML="";for(let s of p){let g=document.createElement("div");g.className="dtk-ui-jobrow"+(s.id===x?" active":"");let v=s.status==="running"?" pulse":"",T=he(s.started_at,(b=s.finished_at)!=null?b:m),u=document.createElement("div");u.className="dtk-ui-jobrow-top",u.innerHTML=`<span class="dtk-ui-jobrow-status"><span class="dtk-ui-jobrow-dot${v}" style="background:${at(s.status)}"></span>${k(s.kind)} \xB7 ${k(s.status)}</span><span class="dtk-ui-jobrow-meta">${k(le(m,s.started_at))} \xB7 ${k(T)}</span>`,g.appendChild(u);let L=document.createElement("div");L.className="dtk-ui-jobrow-label",L.textContent=s.label,g.appendChild(L);let l=document.createElement("div");if(l.className="dtk-ui-jobrow-actions",s.status==="running"){let f=document.createElement("button");f.type="button",f.className="dtk-ui-actionbtn",f.textContent="Stop",f.onclick=S=>{S.stopPropagation(),n.onStop(s.id)},l.appendChild(f)}if(s.kind==="tune"&&s.url){let f=document.createElement("a");f.className="dtk-ui-joblink",f.href=s.url,f.target="_blank",f.rel="noopener",f.textContent="Open tuner",f.onclick=S=>S.stopPropagation(),l.appendChild(f)}l.childElementCount>0&&g.appendChild(l),g.onclick=()=>n.onFollow(s.id),h.appendChild(g)}}}}var it=3,st=[{value:"24h",label:"24h"},{value:"7d",label:"7d"},{value:"30d",label:"30d"},{value:"90d",label:"90d"},{value:"all",label:"All"}];function lt(e,n){Ne(),n.classList.add(Y),n.innerHTML="";let r=document.createElement("div");r.className=`${Y}-root`,n.appendChild(r);let t={windowPreset:e.initial_window||"30d",metrics:e.metrics.map(pe),jobs:[],followedJobId:null,followOffset:0,tagFilter:null,sort:{key:"alerts",dir:ve.alerts}},o=null,a,c;function h(){let i=new Set,d=new Set;for(let M of e.metrics){i.add(M.name);for(let j of M.tags)d.add(j)}return[...i,...[...d].map(M=>`tag:${M}`)]}function w(){let i=t.jobs.find(d=>d.status==="running"&&d.kind!=="tune");return i?{busy:!0,reason:`a pipeline job is already running (${i.label})`}:{busy:!1,reason:""}}let p=document.createElement("div");p.className="dtk-ui-header",r.appendChild(p);let m=document.createElement("div");m.className="dtk-ui-brand",m.innerHTML=`<span class="dtk-ui-brand-dot"></span><span class="dtk-ui-brand-name">detectkit \xB7 <b>${k(e.project)}</b></span>`,p.appendChild(m);let x=document.createElement("div");x.className="dtk-ui-header-right",p.appendChild(x);let b=document.createElement("div");b.className="dtk-ui-seg";for(let i of st){let d=document.createElement("button");d.type="button",d.className="dtk-ui-seg-btn"+(t.windowPreset===i.value?" on":""),d.textContent=i.label,d.onclick=()=>{t.windowPreset!==i.value&&(t.windowPreset=i.value,b.querySelectorAll(".dtk-ui-seg-btn").forEach(M=>M.classList.remove("on")),d.classList.add("on"),o&&o.setWindow(i.value),N())},b.appendChild(d)}x.appendChild(b);let s=document.createElement("button");s.type="button",s.className="dtk-ui-iconbtn",s.title="Refresh overview",s.textContent="\u27F3",s.onclick=()=>{N()},x.appendChild(s);let g=document.createElement("button");g.type="button",g.className="dtk-ui-runbtn",g.textContent="Run pipeline",g.onclick=()=>P(),x.appendChild(g);let v=document.createElement("span");v.className="dtk-ui-progresschip",v.style.display="none",x.appendChild(v);function T(i,d){if(d===0||i>=d){v.style.display="none";return}v.textContent=`${i}/${d}`,v.style.display=""}let u=document.createElement("button");u.type="button",u.className="dtk-ui-jobschip",u.innerHTML='<span class="dtk-ui-jobschip-dot"></span><span>idle</span>',u.onclick=()=>{R.isOpen()?R.close():O()},x.appendChild(u);function L(){let i=t.jobs.find(j=>j.status==="running");u.classList.toggle("running",!!i);let d=i?`${i.kind} ${i.label}`:"idle",M=u.querySelector("span:last-child");M&&(M.textContent=d),u.title=i?`Started ${new Date(i.started_at).toLocaleString()}`:"No jobs running"}let l=document.createElement("div");l.className="dtk-ui-content",r.appendChild(l);function f(){var Q,U;l.innerHTML="";let i=e.metrics.length;if(i===0){let y=document.createElement("div");y.className="dtk-ui-empty",y.textContent="No metrics found for this project/selector.",l.appendChild(y);return}let d=t.metrics.filter(y=>!y.pending),M=d.filter(y=>y.error!==null);if(d.length===i&&M.length===i){let y=document.createElement("div");y.className="dtk-ui-banner";let se=(U=(Q=M[0])==null?void 0:Q.error)!=null?U:"unknown error";y.innerHTML=`<span>Failed to load overview: every metric failed (${k(se)}).</span>`;let J=document.createElement("button");J.type="button",J.className="dtk-ui-banner-retry",J.textContent="Retry",J.onclick=()=>{N()},y.appendChild(J),l.appendChild(y)}l.appendChild(Pe(t.metrics)),l.appendChild(De(d,t.tagFilter,y=>{t.tagFilter=y,f()}));let j=t.tagFilter===null?t.metrics:t.metrics.filter(y=>t.tagFilter===ae?y.tags.length===0:y.tags.includes(t.tagFilter)),X=Be(j,t.sort,Date.now(),{onOpen:S,onTune:y=>{q(y)},onRun:y=>P(y),onSortChange:y=>{t.sort=t.sort.key===y?{key:y,dir:t.sort.dir==="asc"?"desc":"asc"}:{key:y,dir:ve[y]},f()}});l.appendChild(X.el),X.paint()}function S(i){o&&o.close(),o=Ie(r,i,t.windowPreset,{onTune:d=>{q(d)},onClose:()=>{o=null}})}let E=qe(r,{submitRun:i=>{A(i)},submitAutotune:i=>{Z(i)},submitUnlock:i=>{z(i)},getSelectOptions:h,isPipelineBusy:w}),R=Ue(r,{onFollow:i=>G(i),onStop:i=>{ee(i)}});function P(i){R.close(),E.refreshOptions(),E.refreshBusyState(),E.open(i)}function O(){E.close(),R.render(t.jobs,Date.now(),t.followedJobId),R.open(),ie()}function _(i,d,M,j){let X={id:M,kind:i,label:d,status:"running",returncode:null,url:j,started_at:Date.now(),finished_at:null};t.jobs=[X,...t.jobs.filter(Q=>Q.id!==M)],te(),ie(),H()}let D=!1,I=new Set;async function A(i){if(!D){D=!0;try{let d=await Me(i);_("run",`run --select ${i.select}`,d.job_id,null),G(d.job_id)}catch(d){B(r,"error",d.message)}finally{D=!1}}}async function Z(i){if(!D){D=!0;try{let d=await Se(i);_("autotune",`autotune --select ${i.select}`,d.job_id,null),G(d.job_id)}catch(d){B(r,"error",d.message)}finally{D=!1}}}async function z(i){if(!D){D=!0;try{let d=await Ee(i);_("unlock",`unlock --select ${i.select}`,d.job_id,null),G(d.job_id)}catch(d){B(r,"error",d.message)}finally{D=!1}}}async function q(i){if(!I.has(i)){I.add(i),B(r,"info",`Opening tuner for ${i}\u2026`);try{let d=await Le({metric:i});_("tune",`tune --select ${i}`,d.job_id,d.url),window.open(d.url,"_blank")}catch(d){B(r,"error",d.message)}finally{I.delete(i)}}}async function ee(i){try{await $e(i),B(r,"info","Stop requested."),H()}catch(d){B(r,"error",d.message)}}function G(i){t.followedJobId=i,t.followOffset=0,P(),E.resetLog(),C(i)}function te(){L(),R.render(t.jobs,Date.now(),t.followedJobId),E.refreshBusyState()}async function H(){try{let i=await Te();t.jobs=i.jobs}catch{}te()}function ie(){if(a!==void 0)return;let i=()=>{H().then(()=>{a=R.isOpen()||t.jobs.some(M=>M.status==="running")?window.setTimeout(i,2e3):void 0})};a=window.setTimeout(i,2e3)}function ne(){c!==void 0&&(window.clearTimeout(c),c=void 0)}function C(i){ne();let d=()=>{Ce(i,t.followOffset).then(M=>{if(t.followedJobId===i){if(E.appendLog(M.lines),t.followOffset=M.next_offset,M.status!=="running"){E.setLogStatus(M.status,M.returncode),c=void 0,H();return}c=window.setTimeout(d,1e3)}}).catch(M=>{B(r,"error",`job ${i}: ${M.message}`),c=void 0})};c=window.setTimeout(d,0)}let $=0;async function N(){let i=++$,d=t.windowPreset;if(t.metrics=e.metrics.map(pe),s.classList.add("spinning"),T(0,e.metrics.length),f(),e.metrics.length===0){s.classList.remove("spinning"),T(0,0);return}let M=[...e.metrics],j=0;async function X(){for(;;){if(i!==$)return;let U=M.shift();if(!U)return;let y;try{y=await we(U.name,d),y.pending=!1}catch(J){y={...pe(U),pending:!1,error:J.message}}if(i!==$)return;let se=t.metrics.findIndex(J=>J.name===U.name);se!==-1&&(t.metrics[se]=y),j++,T(j,e.metrics.length),f()}}let Q=Math.min(it,e.metrics.length);await Promise.all(Array.from({length:Q},()=>X())),i===$&&(s.classList.remove("spinning"),T(j,e.metrics.length),E.refreshOptions())}f(),E.refreshOptions(),N(),H()}window.__DTK_UI__={render:lt};})();
