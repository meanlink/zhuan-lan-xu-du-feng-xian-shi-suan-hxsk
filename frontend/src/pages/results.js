import {jobs} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {chart} from '../components/common/chart.js';
import {table} from '../components/common/table.js';
import {status} from '../components/common/status.js';
import {ACTIVE_STATUSES,AttemptStatus} from '../constants/enums.js';
import {esc,fmt,date,notify} from '../utils/dom.js';

const canEdit=()=>session.user.role==='admin'||session.user.role==='analyst';

const ACTION_LABELS={'job.create':'创建试验','job.claimed':'领取执行','job.completed':'计算完成','job.failed':'计算失败','job.recovered':'中断恢复','job.cancelled':'编辑取消','job.approve':'批准结果','job.stale_result_ignored':'丢弃迟到结果'};
function historyPanel(history){
 const rows=(history||[]).map(a=>({at:date(a.at),action:ACTION_LABELS[a.action]||a.action,actor:a.actor,detail:JSON.stringify(a.detail||{})}));
 return '<section class="panel"><div class="section-title"><h2>操作与生效记录</h2><span>按时间顺序保留</span></div>'+table([{key:'at',label:'时间'},{key:'action',label:'动作'},{key:'actor',label:'操作者'},{key:'detail',label:'详情'}],rows,'尚无操作记录。')+'</section>';
}

function executionPanel(j,attempts){
 const rows=(attempts||[]).slice().sort((a,b)=>a.attempt_no-b.attempt_no).map(a=>({'attempt':'第 '+a.attempt_no+' 次','worker':a.worker,'state':AttemptStatus[a.status]||a.status,'effective':a.effective?'生效':'未生效','started':date(a.started_at),'finished':a.finished_at?date(a.finished_at):'—','note':a.error||''}));
 return '<section class="panel"><div class="section-title"><h2>执行与生效记录</h2><span>共 '+(attempts||[]).length+' 次领取 · 参数与样本沿用首次领取</span></div>'+table([{key:'attempt',label:'执行'},{key:'worker',label:'计算进程'},{key:'state',label:'状态'},{key:'effective',label:'结果发布'},{key:'started',label:'领取时间'},{key:'finished',label:'结束时间'},{key:'note',label:'失败原因'}],rows,'尚无执行记录，等待后台领取。')+'<p class="hint">中断后的重试沿用首次领取的数据样本与参数；只有生效的那一次结果进入复核与分发，迟到结果不会改写状态。</p></section>';
}

export async function results(id){
 workspace.jobs=await jobs.list();const j=id?await jobs.get(id):(workspace.jobs.find(j=>j.id===workspace.selectedJob)||workspace.jobs[0]);
 if(j&&!workspace.jobs.some(x=>x.id===j.id))workspace.jobs.push(j);
 if(!j)return heading('04 / REVIEW','结果复核','尚无分析结果。')+'<div class="empty">先到分析工作台，选择批次并提交一次计算。<a href="#/workbench">前往工作台 ↗</a></div>';
 workspace.selectedJob=j.id;const r=j.result||{};
 const attempts=j.id?await jobs.attempts(j.id).catch(()=>[]):[];
 const history=j.id?await jobs.history(j.id).catch(()=>[]):[];
 const active=ACTIVE_STATUSES.includes(j.status);
 const cancelButton=active&&canEdit()?'<button class="button" id="cancel-job">取消试验</button>':'';
 const note=j.status==='cancelled'?'<section class="panel empty">该试验已取消：'+esc(j.cancelled_by||'编辑')+' · '+date(j.cancelled_at)+'。取消状态不会被迟到的计算结果覆盖，也不会进入批准或简报。<a href="#/workbench">返回工作台 ↗</a></section>':'';
 const body=j.status==='completed'?'<section class="result-lead"><p class="eyebrow">COMPUTED FINDING</p><h2>'+esc(r.summary)+'</h2><div class="metrics">'+(r.metrics||[]).map(m=>'<div><span>'+esc(m.label)+'</span><strong>'+esc(fmt(m.value))+'<small>'+esc(m.unit||'')+'</small></strong></div>').join('')+'</div></section><section class="panel">'+chart(r.chart)+'</section><div class="two-columns"><section class="panel"><div class="section-title"><h2>业务解释</h2><span>由计算结果生成</span></div><ol class="questions">'+(r.findings||[]).map(v=>'<li>'+esc(v)+'</li>').join('')+'</ol>'+(r.warnings||[]).map(v=>'<p class="warning">'+esc(v)+'</p>').join('')+'</section><section class="method-sheet compact"><p class="eyebrow">REPRODUCIBILITY</p><h3>计算口径与参数</h3><p>'+esc(r.method)+'</p><pre>'+esc(JSON.stringify(j.params,null,2))+'</pre>'+(session.user.role==='admin'&&!j.approved?'<button class="primary" id="approve-job">批准此业务结论</button>':'')+'<p class="hint">仅已完成且获批准的结果可进入定时分发档案。</p></section></div><section class="panel"><div class="section-title"><h2>结果明细</h2><span>'+(r.table?.rows?.length||0)+' 行</span></div>'+table(r.table?.columns||[],r.table?.rows||[])+'</section>':note||'<section class="panel empty">'+(j.status==='failed'?'计算失败：'+esc(j.error)+'。请返回工作台调整参数或数据。':'后台正在执行计算。点击刷新结果查看最新进展。')+'<a href="#/workbench">返回工作台 ↗</a></section>';
 return heading('04 / REVIEW','结果复核与业务解释',j.name,'<div class="page-actions">'+cancelButton+'<button class="button" id="refresh-results">刷新结果 ↻</button></div>')+'<div class="result-selector"><label>分析记录<select id="select-job">'+workspace.jobs.map(x=>'<option value="'+x.id+'" '+(x.id===j.id?'selected':'')+'>'+esc(x.name)+' · '+esc(x.status)+'</option>').join('')+'</select></label>'+status(j.status)+'<span>'+date(j.created_at)+'</span><span class="approval">'+(j.status==='cancelled'?'已取消 · 不参与批准与简报':j.approved?'已获业务批准':'待负责人复核')+'</span></div>'+body+executionPanel(j,attempts)+historyPanel(history);
}
export function bindResults(refresh){document.querySelector('#refresh-results')?.addEventListener('click',refresh);document.querySelector('#select-job')?.addEventListener('change',e=>{workspace.selectedJob=Number(e.target.value);location.hash='#/results/'+e.target.value;});document.querySelector('#approve-job')?.addEventListener('click',async()=>{try{await jobs.approve(workspace.selectedJob);notify('已批准，可创建分发计划');await refresh();}catch(e){notify(e.message,true);}});document.querySelector('#cancel-job')?.addEventListener('click',async e=>{if(!confirm('取消后该试验不再参与批准或简报，且迟到结果不能覆盖取消状态。确定取消？'))return;e.target.disabled=true;try{await jobs.cancel(workspace.selectedJob);notify('试验已取消');await refresh();}catch(error){notify(error.message,true);e.target.disabled=false;}});}
