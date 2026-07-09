"use strict";(()=>{var h=e=>String(e).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");function de(e){let n=e/60;return e>=86400&&e%86400===0?e/86400+"d":e>=3600&&e%3600===0?e/3600+"h":n>=1&&e%60===0?n+"min":e+"s"}function A(e){return e==null||!Number.isFinite(e)?"\u2014":(e*100).toFixed(1)+"%"}function X(e){return e==null||!Number.isFinite(e)?"\u2014":Math.round(e).toLocaleString("en-US")}function Y(e){return e==null||!Number.isFinite(e)?"\u2014":`\u2248${e>=9.5?e.toFixed(0):e.toFixed(1)}/day`}function Z(e,n){let r=Math.max(0,e-n),t=Math.round(r/6e4);if(t<1)return"just now";if(t<60)return`${t}m ago`;let o=Math.floor(t/60);if(o<24)return`${o}h ago`;let i=Math.floor(o/24);return i<30?`${i}d ago`:`${Math.floor(i/30)}mo ago`}function ce(e,n){let r=Math.max(0,Math.round((n-e)/1e3));if(r<60)return`${r}s`;let t=Math.floor(r/60),o=r%60;if(t<60)return o?`${t}m ${o}s`:`${t}m`;let i=Math.floor(t/60),d=t%60;return`${i}h ${String(d).padStart(2,"0")}m`}function re(e){return new Date(e).toISOString().slice(0,19).replace("T"," ")}function ee(e){let n=Math.round(e/60);if(n<60)return`${n}m`;let r=Math.floor(n/60),t=n%60;if(r<24)return r+"h"+(t?` ${t}m`:"");let o=Math.floor(r/24),i=r%24;return o+"d"+(i?` ${i}h`:"")}function ue(e,n){let r=new Map;for(let t of e){let o=n(t),i=r.get(o);i?i.push(t):r.set(o,[t])}return r}var Oe=new URLSearchParams(location.search).get("token")||"";function ae(e,n){let r=new URL(e,location.origin);if(r.searchParams.set("token",Oe),n)for(let[t,o]of Object.entries(n))r.searchParams.set(t,o);return r.toString()}function ie(e,n){return ae(`/metric/${encodeURIComponent(e)}`,{window:n})}async function pe(e){let n=await e.text().catch(()=>"");return new Error(n||`HTTP ${e.status}`)}async function se(e,n){let r=await fetch(ae(e,n));if(!r.ok)throw await pe(r);return r.json()}async function Q(e,n){let r=await fetch(ae(e),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(n)});if(!r.ok)throw await pe(r);return r.json()}function me(e){return se("/api/overview",{window:e})}function fe(){return se("/api/jobs")}function be(e,n){return se(`/api/job/${encodeURIComponent(e)}`,{offset:String(n)})}function ve(e){return Q("/api/run",e)}function ge(e){return Q("/api/autotune",e)}function ke(e){return Q("/api/unlock",e)}function he(e){return Q("/api/tune",e)}function xe(e){return Q(`/api/job/${encodeURIComponent(e)}/stop`,{})}var I="dtk-ui",ye=!1;function we(){if(ye)return;ye=!0;let e=`
.${I}{
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
.${I} *{box-sizing:border-box;}
.${I} a{color:var(--clay);}
.${I}-root{max-width:1400px;margin:0 auto;padding:16px 20px 56px;display:flex;
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
.dtk-ui-overlay-body{flex:1;min-height:0;}
.dtk-ui-overlay-body iframe{width:100%;height:100%;border:0;display:block;background:#fff;}

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
`,n=document.createElement("style");n.setAttribute("data-dtk-ui",""),n.textContent=e,document.head.appendChild(n)}var F=null;function Ae(e){return F&&F.isConnected||(F=document.createElement("div"),F.className="dtk-toasts",e.appendChild(F)),F}function _(e,n,r){let t=Ae(e),o=document.createElement("div");o.className=`dtk-toast dtk-toast-${n}`,o.textContent=r,t.appendChild(o),window.setTimeout(()=>{o.classList.add("dtk-toast-out"),window.setTimeout(()=>o.remove(),220)},5e3)}function z(e,n,r,t){let o="dtk-ui-tile"+(t!=null&&t.err?" err":""),i=t!=null&&t.warn?"dtk-ui-tile-sub warn":"dtk-ui-tile-sub";return`<div class="${o}"><div class="dtk-ui-tile-val">${h(e)}</div><div class="dtk-ui-tile-label">${h(n)}</div>`+(r?`<div class="${i}">${h(r)}</div>`:"")+"</div>"}function Te(e){let n=document.createElement("div");n.className="dtk-ui-tiles";let r=e.metrics,t=r.length,o=r.filter(s=>s.enabled).length,i=0,d=0,g=0,C=0,p=!1;for(let s of r)i+=s.alerts.anomaly,d+=s.alerts.no_data,s.alerts.anomaly>0&&g++,s.alerts.per_day!==null&&(C+=s.alerts.per_day,p=!0);let f=[];for(let s of r)if(s.enabled){if(s.last_point===null){f.push({m:s,lag:1/0});continue}s.lag_seconds!==null&&s.interval_seconds>0&&s.lag_seconds>2*s.interval_seconds&&f.push({m:s,lag:s.lag_seconds})}f.sort((s,b)=>b.lag-s.lag);let T=f.length===0?void 0:`worst: ${f[0].m.name}${Number.isFinite(f[0].lag)?` (${ee(f[0].lag)})`:" (no data)"}`;n.innerHTML=z(`${o}/${t}`,"Metrics","enabled / total")+z(X(i),"Alerts in window",p?Y(C):void 0)+z(X(d),"No-data events")+z(X(g),"Metrics alerting")+z(X(f.length),"Stale metrics",T,{warn:f.length>0,err:f.length>0});let x=r.filter(s=>s.quality!==null);if(x.length>0){let s=0,b=0,k=0,E=0,u=0;for(let w of x){let M=w.quality;M&&(s+=M.caught,b+=M.incidents_in_window,k+=M.false_alerts,E+=w.alerts.anomaly,w.budget>u&&(u=w.budget))}let S=b>0?s/b:null,c=E>0?k/E:null,m=c!==null&&u>0&&c>u;n.innerHTML+=z(A(S),"Labeled recall",`${x.length} metric(s) labeled`)+z(A(c),"False-alert rate",m?`\u25B2 over ${A(u)} budget`:void 0,{warn:m})}return n}var V="untagged";function Je(e){let n=new Map,r=(t,o)=>{let i=n.get(t);i||(i={tag:t,count:0,alerts:0,perDaySum:0,havePerDay:!1},n.set(t,i)),i.count++,i.alerts+=o.alerts.anomaly,o.alerts.per_day!==null&&(i.perDaySum+=o.alerts.per_day,i.havePerDay=!0)};for(let t of e)if(t.tags.length===0)r(V,t);else for(let o of t.tags)r(o,t);return[...n.values()].sort((t,o)=>o.count-t.count||t.tag.localeCompare(o.tag))}function Ce(e,n,r){let t=document.createElement("div");t.className="dtk-ui-tags";let o=document.createElement("button");o.type="button",o.className="dtk-ui-tag"+(n===null?" on":""),o.innerHTML=`<span class="dtk-ui-tag-name">All</span><span class="dtk-ui-tag-n">${e.length}</span>`,o.onclick=()=>r(null),t.appendChild(o);for(let i of Je(e)){let d=document.createElement("button");d.type="button",d.className="dtk-ui-tag"+(n===i.tag?" on":"");let g=i.havePerDay?` \xB7 ${Y(i.perDaySum)}`:"";d.innerHTML=`<span class="dtk-ui-tag-name">${h(i.tag===V?V:`#${i.tag}`)}</span><span class="dtk-ui-tag-n">${i.count} metric${i.count===1?"":"s"}</span><span class="dtk-ui-tag-n">${i.alerts} alert${i.alerts===1?"":"s"}</span>`+(g?`<span class="dtk-ui-tag-sub">${h(g)}</span>`:""),d.onclick=()=>r(i.tag),t.appendChild(d)}return t}var Be={"--term-bg":"#211e1a","--clay":"#d15b36","--st-anomaly":"#d63232","--st-recovery":"#36a64f","--st-nodata":"#f0ad4e","--st-error":"#5a7a8c","--faint":"#9a9384","--muted":"#6e675b","--border":"#332f29","--term-border":"#332f29"};function te(e){return getComputedStyle(document.documentElement).getPropertyValue(e).trim()||Be[e]||"#888"}function Ie(e){let n=e.replace("#","").trim();n.length===3&&(n=n[0]+n[0]+n[1]+n[1]+n[2]+n[2]);let r=parseInt(n,16);return n.length!==6||Number.isNaN(r)?[209,91,54]:[r>>16&255,r>>8&255,r&255]}function Ee(e,n){let[r,t,o]=Ie(e);return`rgba(${r},${t},${o},${n})`}var st=Number.isFinite;var Se=140,Me=30;function $e(e,n,r){let t=Math.max(1,window.devicePixelRatio||1);e.style.width=`${Se}px`,e.style.height=`${Me}px`,e.width=Math.round(Se*t),e.height=Math.round(Me*t);let o=e.getContext("2d");if(!o||(o.clearRect(0,0,e.width,e.height),n.length===0))return;let i=3*t,d=e.width,g=e.height,C=n[0].t,p=n[n.length-1].t,f=p-C||1,T=c=>i+(c-C)/f*Math.max(1,d-2*i),x=1/0,s=-1/0;for(let c of n)c.v!==null&&Number.isFinite(c.v)&&(c.v<x&&(x=c.v),c.v>s&&(s=c.v));let b=!Number.isFinite(x)||!Number.isFinite(s);b&&(x=0,s=1),s<=x&&(s=x+1);let k=c=>g-i-(c-x)/(s-x)*Math.max(1,g-2*i);if(b){let c=g/2;o.strokeStyle=Ee(te("--faint"),.5),o.lineWidth=1*t,o.setLineDash([2*t,2*t]),o.beginPath(),o.moveTo(i,c),o.lineTo(d-i,c),o.stroke(),o.setLineDash([]);return}o.strokeStyle=te("--term-text"),o.lineWidth=1*t,o.lineJoin="round",o.beginPath();let E=!1;for(let c of n){if(c.v===null||!Number.isFinite(c.v)){E=!1;continue}let m=T(c.t),w=k(c.v);E?o.lineTo(m,w):(o.moveTo(m,w),E=!0)}if(o.stroke(),r.length===0)return;let u=[];for(let c of n)c.v!==null&&Number.isFinite(c.v)&&u.push([c.t,c.v]);let S=c=>{if(u.length===0)return null;if(c<=u[0][0])return u[0][1];if(c>=u[u.length-1][0])return u[u.length-1][1];for(let m=1;m<u.length;m++){let[w,M]=u[m];if(c<=w){let[N,R]=u[m-1],$=w===N?0:(c-N)/(w-N);return R+(M-R)*$}}return u[u.length-1][1]};o.fillStyle=te("--st-anomaly");for(let c of r){if(c<C||c>p)continue;let m=S(c);m!==null&&(o.beginPath(),o.arc(T(c),k(m),2*t,0,Math.PI*2),o.fill())}}var le={alerts:"desc",name:"asc",rate:"desc",freshness:"desc"};function Re(e){var o;if(!e.enabled)return{color:"var(--faint)",title:"disabled",rank:-1};if(e.last_point===null)return{color:"var(--st-anomaly)",title:"no datapoints loaded yet",rank:1/0};let n=(o=e.lag_seconds)!=null?o:0,r=e.interval_seconds>0?n/e.interval_seconds:0,t=`lag ${ee(Math.max(0,n))} (${r.toFixed(1)}\xD7 interval) \xB7 last point ${re(e.last_point)} UTC`;return r<2?{color:"var(--st-recovery)",title:t,rank:n}:r<6?{color:"var(--st-nodata)",title:t,rank:n}:{color:"var(--st-anomaly)",title:t,rank:n}}function Fe(e){return e.length===0?"":`<div class="dtk-ui-tagchips">${e.map(n=>`<span class="dtk-ui-tagchip">${h(n)}</span>`).join("")}</div>`}function ze(e){let n=e.quality;if(!n)return'<span class="dtk-ui-quality empty">\u2014</span>';let r=`Incidents: ${n.incidents} (${n.incidents_in_window} in window) \xB7 caught ${n.caught} \xB7 false alerts ${n.false_alerts} \xB7 reviewed ${n.reviewed} (valid ${n.reviewed_valid}, false ${n.reviewed_false}) \xB7 ${n.labels_file}`;return`<span class="dtk-ui-quality" title="${h(r)}"><span class="dtk-ui-quality-chip">R <b>${h(A(n.recall))}</b></span> \xB7 <span class="dtk-ui-quality-chip">FDR <b>${h(A(n.fdr))}</b></span> \xB7 <span class="dtk-ui-quality-chip">\u2713${n.reviewed_valid}</span></span>`}function qe(e){let n=e.alert_rule?`min_detectors=${e.alert_rule.min_detectors} \xB7 direction=${e.alert_rule.direction} \xB7 consecutive=${e.alert_rule.consecutive} (${e.alert_rule.enabled}/${e.alert_rule.configs} config(s) enabled)`:"no alerting configured";return`detectors: ${e.detectors.join(", ")||"\u2014"}
alert rule: ${n}
file: ${e.file}`}function Ue(e,n,r,t){let o=document.createElement("tr");o.className="dtk-ui-row"+(e.enabled?"":" disabled")+(e.error?" errored":"");let i=Re(e),d=document.createElement("td");d.className="dtk-ui-dotcell",d.innerHTML=`<span class="dtk-ui-dot" style="background:${i.color}" title="${h(i.title)}"></span>`,o.appendChild(d);let g=document.createElement("td");g.className="dtk-ui-namecell";let C=e.error?`<span class="dtk-ui-err-badge" title="${h(e.error)}">!</span>`:"";g.title=qe(e),g.innerHTML=`<span class="dtk-ui-name">${h(e.name)}</span>${C}${Fe(e.tags)}`,o.appendChild(g);let p=document.createElement("td");p.innerHTML=`<span class="dtk-ui-interval">${h(de(e.interval_seconds))}</span>`,o.appendChild(p);let f=document.createElement("td");if(f.className="dtk-ui-sparkcell",e.spark.length===0)f.innerHTML='<span class="dtk-ui-spark-empty">no data yet</span>';else{let N=document.createElement("canvas");N.className="dtk-spark",f.appendChild(N),t.push({canvas:N,points:e.spark.map(([R,$])=>({t:R,v:$})),anoms:e.spark_anoms})}o.appendChild(f);let T=document.createElement("td");T.className="dtk-ui-alertscell";let x=e.quality!==null&&e.quality.fdr!==null&&e.quality.fdr>e.budget,s="dtk-ui-alerts-n"+(e.alerts.anomaly>0?" hasany":"")+(x?" overbudget":""),b=e.alerts.per_day!==null?`<span class="dtk-ui-alerts-sub">\xB7 ${h(Y(e.alerts.per_day))}</span>`:"";T.innerHTML=`<span class="${s}">${e.alerts.anomaly}</span>${b}`,o.appendChild(T);let k=document.createElement("td");e.alerts.last_ts!==null?k.innerHTML=`<span class="dtk-ui-lastalert" title="${h(re(e.alerts.last_ts))} UTC">${h(Z(n,e.alerts.last_ts))}</span>`:k.innerHTML='<span class="dtk-ui-lastalert">\u2014</span>',o.appendChild(k);let E=document.createElement("td");E.innerHTML=`<span class="dtk-ui-rate">${h(A(e.anomaly_rate))}</span>`,o.appendChild(E);let u=document.createElement("td");u.innerHTML=ze(e),o.appendChild(u);let S=document.createElement("td");S.innerHTML=e.locked?'<span class="dtk-ui-lock" title="pipeline lock currently held for this metric">LOCK</span>':"",o.appendChild(S);let c=document.createElement("td");c.className="dtk-ui-actionscell";let m=document.createElement("button");m.type="button",m.className="dtk-ui-actionbtn",m.textContent="Open",m.onclick=()=>r.onOpen(e.name);let w=document.createElement("button");w.type="button",w.className="dtk-ui-actionbtn",w.textContent="Tune",w.onclick=()=>r.onTune(e.name);let M=document.createElement("button");return M.type="button",M.className="dtk-ui-actionbtn",M.textContent="Run",M.onclick=()=>r.onRun(e.name),c.append(m,w,M),o.appendChild(c),o}function Le(e,n){var r;switch(n){case"alerts":return e.alerts.anomaly;case"name":return e.name.toLowerCase();case"rate":return(r=e.anomaly_rate)!=null?r:-1;case"freshness":return Re(e).rank}}function Ke(e,n){let r=e.filter(i=>i.enabled),t=e.filter(i=>!i.enabled),o=n.dir==="asc"?1:-1;return r.sort((i,d)=>{let g=Le(i,n.key),C=Le(d,n.key);return g<C?-1*o:g>C?1*o:i.name.localeCompare(d.name)}),t.sort((i,d)=>i.name.localeCompare(d.name)),[...r,...t]}var Ye=[{label:"\u25CF",key:"freshness"},{label:"Name",key:"name"},{label:"Interval",key:null},{label:"Trend",key:null},{label:"Alerts",key:"alerts"},{label:"Last alert",key:null},{label:"Rate",key:"rate"},{label:"Quality",key:null},{label:"",key:null},{label:"",key:null}];function We(e,n){let r=document.createElement("tr");for(let t of Ye){let o=document.createElement("th");if(t.key){o.className="dtk-ui-th";let i=e.key===t.key?`<span class="dtk-ui-th-arrow">${e.dir==="asc"?"\u25B5":"\u25BE"}</span>`:"";o.innerHTML=`${h(t.label)}${i}`,o.onclick=()=>n.onSortChange(t.key)}else o.textContent=t.label;r.appendChild(o)}return r}function Ge(e){return e===""?"metrics/":`metrics/${e}/`}function Ne(e,n,r,t){var C;let o=[],i=document.createElement("div");if(i.className="dtk-ui-table-wrap",e.length===0)return i.innerHTML='<div class="dtk-ui-empty">No metrics match the current filter.</div>',{el:i,paint:()=>{}};let d=ue(e,p=>p.dir),g=[...d.keys()].sort((p,f)=>p===f?0:p===""?-1:f===""?1:p.localeCompare(f));for(let p of g){let f=(C=d.get(p))!=null?C:[],T=document.createElement("div");T.className="dtk-ui-group";let x=f.reduce((u,S)=>u+S.alerts.anomaly,0),s=document.createElement("div");s.className="dtk-ui-group-head",s.innerHTML=`<span class="dtk-ui-group-name">${h(Ge(p))}</span><span class="dtk-ui-group-sub">${f.length} metric${f.length===1?"":"s"} \xB7 ${x} alert${x===1?"":"s"}</span>`,T.appendChild(s);let b=document.createElement("table");b.className="dtk-ui-table";let k=document.createElement("thead");k.appendChild(We(n,t)),b.appendChild(k);let E=document.createElement("tbody");for(let u of Ke(f,n))E.appendChild(Ue(u,r,t,o));b.appendChild(E),T.appendChild(b),i.appendChild(T)}return{el:i,paint:()=>{for(let p of o)$e(p.canvas,p.points,p.anoms)}}}function Pe(e,n,r,t){let o=document.createElement("div");o.className="dtk-ui-overlay";let i=document.createElement("div");i.className="dtk-ui-overlay-modal",o.appendChild(i);let d=document.createElement("div");d.className="dtk-ui-overlay-head",d.innerHTML=`<span><span class="dtk-ui-overlay-title">${h(n)}</span><span class="dtk-ui-overlay-sub">window: ${h(r)}</span></span>`;let g=document.createElement("div");g.className="dtk-ui-overlay-actions";let C=document.createElement("button");C.type="button",C.className="dtk-ui-btn",C.textContent="Tune",C.onclick=()=>t.onTune(n);let p=document.createElement("button");p.type="button",p.className="dtk-ui-overlay-close",p.textContent="\u2715",p.title="Close (Esc)",g.append(C,p),d.appendChild(g),i.appendChild(d);let f=document.createElement("div");f.className="dtk-ui-overlay-body";let T=document.createElement("iframe");T.src=ie(n,r),T.title=`detectkit report \u2014 ${n}`,f.appendChild(T),i.appendChild(f),e.appendChild(o);function x(){document.removeEventListener("keydown",s),o.remove(),t.onClose()}function s(b){b.key==="Escape"&&x()}return o.addEventListener("click",b=>{b.target===o&&x()}),p.onclick=x,document.addEventListener("keydown",s),{setWindow(b){let k=d.querySelector(".dtk-ui-overlay-sub");k&&(k.textContent=`window: ${b}`),T.src=ie(n,b)},close:x}}var De=/^\d{4}-\d{2}-\d{2}( \d{2}:\d{2}:\d{2})?$/,He="dtk-ui-run-select-options";function _e(e,n){let r=document.createElement("div");r.className="dtk-ui-drawer-backdrop";let t=document.createElement("div");t.className="dtk-ui-drawer";let o=document.createElement("div");o.className="dtk-ui-drawer-head",o.innerHTML='<span class="dtk-ui-drawer-title">Run pipeline</span>';let i=document.createElement("button");i.type="button",i.className="dtk-ui-drawer-close",i.textContent="\u2715",o.appendChild(i),t.appendChild(o);let d=document.createElement("div");d.className="dtk-ui-drawer-body",t.appendChild(d);let g=document.createElement("div");g.className="dtk-ui-field";let C=document.createElement("datalist");C.id=He;let p=document.createElement("input");p.type="text",p.className="dtk-ui-input",p.placeholder="metric name, tag:x, glob, or *",p.value="*",p.setAttribute("list",He),g.innerHTML='<span class="dtk-ui-field-label">Select</span>',g.append(p,C),d.appendChild(g);let f=document.createElement("div");f.className="dtk-ui-field",f.innerHTML='<span class="dtk-ui-field-label">Steps</span>';let T=document.createElement("div");T.className="dtk-ui-checks";let x={};for(let a of["load","detect","alert"]){let l=document.createElement("label");l.className="dtk-ui-check";let y=document.createElement("input");y.type="checkbox",y.checked=!0,y.onchange=B,l.append(y,document.createTextNode(a)),T.appendChild(l),x[a]=y}f.appendChild(T),d.appendChild(f);let s=document.createElement("div");s.className="dtk-ui-row2";let b=document.createElement("div");b.className="dtk-ui-field",b.innerHTML='<span class="dtk-ui-field-label">From</span>';let k=document.createElement("input");k.type="text",k.className="dtk-ui-input",k.placeholder="YYYY-MM-DD [HH:MM:SS]",k.oninput=B,b.appendChild(k);let E=document.createElement("div");E.className="dtk-ui-field",E.innerHTML='<span class="dtk-ui-field-label">To</span>';let u=document.createElement("input");u.type="text",u.className="dtk-ui-input",u.placeholder="YYYY-MM-DD [HH:MM:SS]",u.oninput=B,E.appendChild(u),s.append(b,E),d.appendChild(s);let S=document.createElement("div");S.className="dtk-ui-checks";let c=document.createElement("label");c.className="dtk-ui-check";let m=document.createElement("input");m.type="checkbox",c.append(m,document.createTextNode("force (skip lock check)"));let w=document.createElement("label");w.className="dtk-ui-check";let M=document.createElement("input");M.type="checkbox",w.append(M,document.createTextNode("full refresh")),S.append(c,w),d.appendChild(S);let N=document.createElement("div");N.className="dtk-ui-btnrow";let R=document.createElement("button");R.type="button",R.className="dtk-ui-btn primary",R.textContent="Run";let $=document.createElement("button");$.type="button",$.className="dtk-ui-btn",$.textContent="Autotune";let P=document.createElement("button");P.type="button",P.className="dtk-ui-btn danger",P.textContent="Unlock",N.append(R,$,P),d.appendChild(N);let W=document.createElement("div");W.className="dtk-ui-reason",d.appendChild(W);let q=document.createElement("div");q.className="dtk-ui-field",q.innerHTML='<span class="dtk-ui-field-label">Log</span>';let D=document.createElement("div");D.className="dtk-ui-log";let U=document.createElement("div");U.className="dtk-ui-log-body";let j=document.createElement("div");j.className="dtk-ui-log-line",D.append(U,j),q.appendChild(D),d.appendChild(q);let H=[];function K(){U.innerHTML=H.length===0?'<span class="dtk-ui-log-empty">no output yet</span>':H.map(h).join("<br>")}K();function J(){return D.scrollTop+D.clientHeight>=D.scrollHeight-24}function G(){return Object.keys(x).filter(a=>x[a].checked)}function B(){let a=n.isPipelineBusy(),l=p.value.trim(),y=k.value.trim()===""||De.test(k.value.trim()),v=u.value.trim()===""||De.test(u.value.trim()),L="";a.busy?L=a.reason:l===""?L="select is required":!y||!v?L="from/to must be YYYY-MM-DD or YYYY-MM-DD HH:MM:SS":G().length===0&&(L="pick at least one step to run"),W.textContent=L,R.disabled=L!=="",$.disabled=a.busy||l===""||!y||!v,P.disabled=a.busy||l===""}function ne(){return{select:p.value.trim(),steps:G(),from:k.value.trim()||null,to:u.value.trim()||null,full_refresh:M.checked,force:m.checked}}R.onclick=()=>n.submitRun(ne()),$.onclick=()=>n.submitAutotune({select:p.value.trim(),from:k.value.trim()||null,to:u.value.trim()||null}),P.onclick=()=>{let a=p.value.trim();window.confirm(`Unlock the pipeline lock for "${a}"? Only do this if you're sure no dtk process is actually running against it.`)&&n.submitUnlock({select:a})};function O(){r.classList.remove("open"),t.classList.remove("open")}return i.onclick=O,r.onclick=O,e.append(r,t),{el:t,open(a){a&&(p.value=a),r.classList.add("open"),t.classList.add("open"),B()},close:O,isOpen(){return t.classList.contains("open")},refreshOptions(){C.innerHTML=["*",...n.getSelectOptions()].map(a=>`<option value="${h(a)}"></option>`).join("")},refreshBusyState:B,resetLog(){H=[],K(),j.textContent="",j.className="dtk-ui-log-line"},appendLog(a){if(a.length===0)return;let l=J();H.push(...a),K(),l&&(D.scrollTop=D.scrollHeight)},setLogStatus(a,l){if(a==="running")return;let y=a==="done"&&l===0?"exit-ok":a==="stopped"?"exit-stop":"exit-fail";j.className=`dtk-ui-log-line ${y}`,j.textContent=`\u2500\u2500 ${a} (exit ${l!=null?l:"?"}) \u2500\u2500`}}}function Xe(e){return e==="done"?"var(--st-recovery)":e==="failed"?"var(--st-anomaly)":e==="running"?"var(--clay)":"var(--faint)"}function je(e,n){let r=document.createElement("div");r.className="dtk-ui-drawer-backdrop";let t=document.createElement("div");t.className="dtk-ui-drawer";let o=document.createElement("div");o.className="dtk-ui-drawer-head",o.innerHTML='<span class="dtk-ui-drawer-title">Jobs</span>';let i=document.createElement("button");i.type="button",i.className="dtk-ui-drawer-close",i.textContent="\u2715",o.appendChild(i),t.appendChild(o);let d=document.createElement("div");d.className="dtk-ui-drawer-body",t.appendChild(d);let g=document.createElement("div");g.className="dtk-ui-joblist",d.appendChild(g);function C(){r.classList.remove("open"),t.classList.remove("open")}return i.onclick=C,r.onclick=C,e.append(r,t),{el:t,open(){r.classList.add("open"),t.classList.add("open")},close:C,isOpen(){return t.classList.contains("open")},render(p,f,T){var x;if(p.length===0){g.innerHTML='<div class="dtk-ui-empty">No jobs yet.</div>';return}g.innerHTML="";for(let s of p){let b=document.createElement("div");b.className="dtk-ui-jobrow"+(s.id===T?" active":"");let k=s.status==="running"?" pulse":"",E=ce(s.started_at,(x=s.finished_at)!=null?x:f),u=document.createElement("div");u.className="dtk-ui-jobrow-top",u.innerHTML=`<span class="dtk-ui-jobrow-status"><span class="dtk-ui-jobrow-dot${k}" style="background:${Xe(s.status)}"></span>${h(s.kind)} \xB7 ${h(s.status)}</span><span class="dtk-ui-jobrow-meta">${h(Z(f,s.started_at))} \xB7 ${h(E)}</span>`,b.appendChild(u);let S=document.createElement("div");S.className="dtk-ui-jobrow-label",S.textContent=s.label,b.appendChild(S);let c=document.createElement("div");if(c.className="dtk-ui-jobrow-actions",s.status==="running"){let m=document.createElement("button");m.type="button",m.className="dtk-ui-actionbtn",m.textContent="Stop",m.onclick=w=>{w.stopPropagation(),n.onStop(s.id)},c.appendChild(m)}if(s.kind==="tune"&&s.url){let m=document.createElement("a");m.className="dtk-ui-joblink",m.href=s.url,m.target="_blank",m.rel="noopener",m.textContent="Open tuner",m.onclick=w=>w.stopPropagation(),c.appendChild(m)}c.childElementCount>0&&b.appendChild(c),b.onclick=()=>n.onFollow(s.id),g.appendChild(b)}}}}var Qe=[{value:"24h",label:"24h"},{value:"7d",label:"7d"},{value:"30d",label:"30d"},{value:"90d",label:"90d"},{value:"all",label:"All"}];function Ve(e,n){we(),n.classList.add(I),n.innerHTML="";let r=document.createElement("div");r.className=`${I}-root`,n.appendChild(r);let t={windowPreset:e.initial_window||"30d",overview:null,overviewError:null,jobs:[],followedJobId:null,followOffset:0,tagFilter:null,sort:{key:"alerts",dir:le.alerts}},o=null,i,d;function g(){let a=new Set,l=new Set,y=v=>{for(let L of v){a.add(L.name);for(let oe of L.tags)l.add(oe)}};return y(e.metrics),t.overview&&y(t.overview.metrics),[...a,...[...l].map(v=>`tag:${v}`)]}function C(){let a=t.jobs.find(l=>l.status==="running"&&l.kind!=="tune");return a?{busy:!0,reason:`a pipeline job is already running (${a.label})`}:{busy:!1,reason:""}}let p=document.createElement("div");p.className="dtk-ui-header",r.appendChild(p);let f=document.createElement("div");f.className="dtk-ui-brand",f.innerHTML=`<span class="dtk-ui-brand-dot"></span><span class="dtk-ui-brand-name">detectkit \xB7 <b>${h(e.project)}</b></span>`,p.appendChild(f);let T=document.createElement("div");T.className="dtk-ui-header-right",p.appendChild(T);let x=document.createElement("div");x.className="dtk-ui-seg";for(let a of Qe){let l=document.createElement("button");l.type="button",l.className="dtk-ui-seg-btn"+(t.windowPreset===a.value?" on":""),l.textContent=a.label,l.onclick=()=>{t.windowPreset!==a.value&&(t.windowPreset=a.value,x.querySelectorAll(".dtk-ui-seg-btn").forEach(y=>y.classList.remove("on")),l.classList.add("on"),o&&o.setWindow(a.value),O())},x.appendChild(l)}T.appendChild(x);let s=document.createElement("button");s.type="button",s.className="dtk-ui-iconbtn",s.title="Refresh overview",s.textContent="\u27F3",s.onclick=()=>{O()},T.appendChild(s);let b=document.createElement("button");b.type="button",b.className="dtk-ui-runbtn",b.textContent="Run pipeline",b.onclick=()=>M(),T.appendChild(b);let k=document.createElement("button");k.type="button",k.className="dtk-ui-jobschip",k.innerHTML='<span class="dtk-ui-jobschip-dot"></span><span>idle</span>',k.onclick=()=>{w.isOpen()?w.close():N()},T.appendChild(k);function E(){let a=t.jobs.find(v=>v.status==="running");k.classList.toggle("running",!!a);let l=a?`${a.kind} ${a.label}`:"idle",y=k.querySelector("span:last-child");y&&(y.textContent=l),k.title=a?`Started ${new Date(a.started_at).toLocaleString()}`:"No jobs running"}let u=document.createElement("div");u.className="dtk-ui-content",r.appendChild(u);function S(){if(u.innerHTML="",t.overviewError){let v=document.createElement("div");v.className="dtk-ui-banner",v.innerHTML=`<span>Failed to load overview: ${h(t.overviewError)}</span>`;let L=document.createElement("button");L.type="button",L.className="dtk-ui-banner-retry",L.textContent="Retry",L.onclick=()=>{O()},v.appendChild(L),u.appendChild(v)}if(!t.overview){if(!t.overviewError){let v=document.createElement("div");v.className="dtk-ui-empty",v.textContent="Loading overview\u2026",u.appendChild(v)}return}let a=t.overview;if(a.metrics.length===0){let v=document.createElement("div");v.className="dtk-ui-empty",v.textContent=e.metrics.length===0?"No metrics found for this project/selector.":"No metrics in this window.",u.appendChild(v);return}u.appendChild(Te(a)),u.appendChild(Ce(a.metrics,t.tagFilter,v=>{t.tagFilter=v,S()}));let l=t.tagFilter===null?a.metrics:a.metrics.filter(v=>t.tagFilter===V?v.tags.length===0:v.tags.includes(t.tagFilter)),y=Ne(l,t.sort,a.now,{onOpen:c,onTune:v=>{U(v)},onRun:v=>M(v),onSortChange:v=>{t.sort=t.sort.key===v?{key:v,dir:t.sort.dir==="asc"?"desc":"asc"}:{key:v,dir:le[v]},S()}});u.appendChild(y.el),y.paint()}function c(a){o&&o.close(),o=Pe(r,a,t.windowPreset,{onTune:l=>{U(l)},onClose:()=>{o=null}})}let m=_e(r,{submitRun:a=>{W(a)},submitAutotune:a=>{q(a)},submitUnlock:a=>{D(a)},getSelectOptions:g,isPipelineBusy:C}),w=je(r,{onFollow:a=>H(a),onStop:a=>{j(a)}});function M(a){w.close(),m.refreshOptions(),m.refreshBusyState(),m.open(a)}function N(){m.close(),w.render(t.jobs,Date.now(),t.followedJobId),w.open(),G()}function R(a,l,y,v){let L={id:y,kind:a,label:l,status:"running",returncode:null,url:v,started_at:Date.now(),finished_at:null};t.jobs=[L,...t.jobs.filter(oe=>oe.id!==y)],K(),G(),J()}let $=!1,P=new Set;async function W(a){if(!$){$=!0;try{let l=await ve(a);R("run",`run --select ${a.select}`,l.job_id,null),H(l.job_id)}catch(l){_(r,"error",l.message)}finally{$=!1}}}async function q(a){if(!$){$=!0;try{let l=await ge(a);R("autotune",`autotune --select ${a.select}`,l.job_id,null),H(l.job_id)}catch(l){_(r,"error",l.message)}finally{$=!1}}}async function D(a){if(!$){$=!0;try{let l=await ke(a);R("unlock",`unlock --select ${a.select}`,l.job_id,null),H(l.job_id)}catch(l){_(r,"error",l.message)}finally{$=!1}}}async function U(a){if(!P.has(a)){P.add(a),_(r,"info",`Opening tuner for ${a}\u2026`);try{let l=await he({metric:a});R("tune",`tune --select ${a}`,l.job_id,l.url),window.open(l.url,"_blank")}catch(l){_(r,"error",l.message)}finally{P.delete(a)}}}async function j(a){try{await xe(a),_(r,"info","Stop requested."),J()}catch(l){_(r,"error",l.message)}}function H(a){t.followedJobId=a,t.followOffset=0,M(),m.resetLog(),ne(a)}function K(){E(),w.render(t.jobs,Date.now(),t.followedJobId),m.refreshBusyState()}async function J(){try{let a=await fe();t.jobs=a.jobs}catch{}K()}function G(){if(i!==void 0)return;let a=()=>{J().then(()=>{i=w.isOpen()||t.jobs.some(y=>y.status==="running")?window.setTimeout(a,2e3):void 0})};i=window.setTimeout(a,2e3)}function B(){d!==void 0&&(window.clearTimeout(d),d=void 0)}function ne(a){B();let l=()=>{be(a,t.followOffset).then(y=>{if(t.followedJobId===a){if(m.appendLog(y.lines),t.followOffset=y.next_offset,y.status!=="running"){m.setLogStatus(y.status,y.returncode),d=void 0,J();return}d=window.setTimeout(l,1e3)}}).catch(y=>{_(r,"error",`job ${a}: ${y.message}`),d=void 0})};d=window.setTimeout(l,0)}async function O(){s.classList.add("spinning");try{t.overview=await me(t.windowPreset),t.overviewError=null}catch(a){t.overviewError=a.message}finally{s.classList.remove("spinning"),S(),m.refreshOptions()}}S(),m.refreshOptions(),O(),J()}window.__DTK_UI__={render:Ve};})();
