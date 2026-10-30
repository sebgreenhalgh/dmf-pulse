'use strict';
// All live state is memory/DOM only. Never use browser storage or external resources.
const $ = id => document.getElementById(id);
let view = null, page = 'team', polling = null, expiry = null, paired = false, demo = false;
let epoch = 0, expiresPerf = 0;
let syntheticSources = false, providerEligibility = null;
function applyContext(context) {
  demo = context.demo;
  syntheticSources = context.synthetic_sources;
  providerEligibility = context.eligibility;
  $('mode').textContent = demo ? 'SYNTHETIC DEMONSTRATION' : syntheticSources ? 'SYNTHETIC CURRENT-MODE ARCHITECTURE' : 'PRIVATE CURRENT';
}
function showEligibility(parent) {
  if (!providerEligibility) return;
  const c = card('Refresh eligibility', parent);
  table(c, ['Control', 'Status'], [
    ['Engineering', providerEligibility.engineering_status],
    ['Execution architecture', providerEligibility.execution_mode],
    ['Source classification', providerEligibility.source_classification],
    ['Permission / run state', providerEligibility.state],
    ['Reason', providerEligibility.error_code || 'None'],
    ['Qualified deadline UTC', providerEligibility.deadline_at || 'No qualified current deadline observed'],
    ['Qualified quota snapshot', providerEligibility.qualified_quota_snapshot_remaining ?? 'Unavailable']
  ]);
  c.append(text('p', 'Quota above is a qualified snapshot. A completed run shows its separately observed response quota. Refresh is operator-triggered; reloading this page makes no provider acquisition.'));
}
const requests = new Set();
const fmt = (x, n = 2) => x === null || x === undefined ? 'Unavailable' : Number(x).toFixed(n);
const text = (tag, value, cls) => { const e = document.createElement(tag); e.textContent = String(value); if (cls) e.className = cls; return e; };
const add = (parent, ...children) => { children.forEach(c => parent.append(c)); return parent; };
const card = (title, parent = $('content')) => { const e = text('section', '', 'card'); add(e, text('h2', title)); parent.append(e); return e; };
const metric = (parent, label, value) => add(parent, add(text('div', '', 'metric'), text('span', label), text('strong', value)));
const names = id => view?.players.find(p => p.catalogue.player_id === id)?.catalogue.name || id;
async function api(path, body) {
  const generation = epoch, controller = new AbortController(); requests.add(controller);
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(path, {signal: controller.signal, method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store', headers: body === undefined ? {} : {'Content-Type':'application/json', 'X-DMF-Action':'operator'}, ...(body === undefined ? {} : {body: JSON.stringify(body)})});
    const result = await response.json();
    if (epoch !== generation || controller.signal.aborted) throw new DOMException('Superseded', 'AbortError');
    if (!response.ok) throw new Error(result.error_code || 'REQUEST_FAILED');
    return result;
  } catch (error) {
    if (epoch !== generation || controller.signal.aborted) throw new DOMException('Superseded', 'AbortError');
    throw error;
  } finally {clearTimeout(timeout); requests.delete(controller);}
}
function clearPresentation() { epoch++; requests.forEach(c=>c.abort()); requests.clear(); view = null; expiresPerf = 0; $('content').replaceChildren(); if (expiry) clearTimeout(expiry); expiry = null; }
function fail(error) { if (error.name === 'AbortError') return; clearPresentation(); $('notice').textContent = error.message || 'REQUEST_FAILED'; }
function table(parent, headers, rows) {
  const t = document.createElement('table');
  const head = document.createElement('thead'), tr = document.createElement('tr');
  headers.forEach(h => tr.append(text('th', h))); head.append(tr); t.append(head);
  const body = document.createElement('tbody');
  rows.forEach(row => { const r = document.createElement('tr'); row.forEach(v => {const td = document.createElement('td'); td.append(v instanceof Node ? v : document.createTextNode(String(v))); r.append(td);}); body.append(r); });
  t.append(body); parent.append(t); return body;
}
function details(parent, label, value) { const e = document.createElement('details'); add(e, text('summary', label), text('pre', typeof value === 'string' ? value : JSON.stringify(value, null, 2))); parent.append(e); }
function pmf(parent, distribution) {
  const entries = Object.entries(distribution).map(([x,p]) => [Number(x), Number(p)]).sort((a,b) => a[0]-b[0]);
  if (!entries.length) return;
  const ns = 'http://www.w3.org/2000/svg', svg = document.createElementNS(ns, 'svg'); svg.setAttribute('viewBox', '0 0 600 150'); svg.setAttribute('role', 'img'); svg.setAttribute('aria-label','Discrete points outcome probability distribution');
  const max = Math.max(...entries.map(x => x[1])), width = 560 / entries.length;
  entries.forEach(([x,p],i) => {const bar = document.createElementNS(ns,'rect'); bar.setAttribute('x',String(20+i*width)); bar.setAttribute('y',String(125-p/max*105)); bar.setAttribute('width',String(Math.max(1,width-2))); bar.setAttribute('height',String(p/max*105)); bar.setAttribute('fill','#ccf67c'); const title = document.createElementNS(ns,'title'); title.textContent = `${x} points: ${(p*100).toFixed(2)}%`; bar.append(title); svg.append(bar); if (i % Math.max(1,Math.ceil(entries.length/12)) === 0) {const tick=document.createElementNS(ns,'text');tick.setAttribute('x',String(20+i*width)); tick.setAttribute('y','145');tick.setAttribute('fill','#a4b1c1');tick.setAttribute('font-size','10');tick.textContent=String(x);svg.append(tick);}});
  parent.append(svg);
}
function squad(parent, label, ids, tactics) {
  const c = card(label, parent), pitch = text('div', '', 'pitch');
  ids.forEach(id => {const e=text('div','', 'player-chip'); add(e,text('span',names(id))); if (tactics?.captain === id) e.append(text('b',' · C')); if (tactics?.vice_captain === id) e.append(text('b',' · VC')); pitch.append(e);}); c.append(pitch);
}
function showTeam() {
  const d=view.team.decision, root=d.do_now || d, comparison=d.horizon_comparison || d.paired_comparison, area=$('content');
  const grid=text('div','','grid'); area.append(grid);
  metric(grid,'GAMEWEEK',root.gameweek || d.target_gameweek);
  metric(grid,d.do_now ? '3GW EXPECTED UTILITY' : 'EXPECTED POINTS AFTER HITS',fmt(comparison.plan_expected_horizon_utility ?? comparison.recommended_expected_points_after_hit));
  metric(grid,'GAIN VS HOLD',fmt(comparison.expected_uplift ?? comparison.net_expected_uplift));
  metric(grid,'HIT POINTS',root.hit_points ?? comparison.transfer_hit_points);
  const selected=d.transfer_frontier?.points.find(p=>p.transfer_count===root.transfers.length),ft=root.free_transfer_state || selected?.free_transfer_state;
  metric(grid,'FREE TRANSFERS NOW',ft?.effective_before_action ?? 'Unavailable');
  metric(grid,'BANK AFTER · £',fmt((root.bank_after_tenths ?? selected?.bank_after_tenths)/10));
  metric(grid,d.do_now?'HOLD · 3GW UTILITY':'HOLD · CURRENT GW xPTS',fmt(comparison.baseline_expected_horizon_utility ?? comparison.no_transfer_expected_points));
  if(d.do_now){metric(grid,'CURRENT GW xPTS',fmt(root.expected_manager_points_after_hit));metric(grid,'CURRENT GW GAIN',fmt(selected?.immediate_uplift_vs_hold));}

  const moves=card('Your move');
  if (!root.transfers.length) moves.append(text('p','Hold your squad. No transfer is the evaluated recommendation.'));
  root.transfers.forEach(t => moves.append(text('p',`${names(t.player_out_id)} → ${names(t.player_in_id)}`)));
  const recommended=d.resulting_squad || root.squad_after, tactics=root.tactics;
  squad(area,'Starting XI', tactics.starting_xi,tactics);
  const bench=card('Ordered bench'); bench.append(text('p',`Goalkeeper: ${names(tactics.bench_goalkeeper)}`)); bench.append(text('p',tactics.bench_outfield_order.map((id,i)=>`${i+1}. ${names(id)}`).join(' · ')));
  const positions=tactics.starting_xi.map(id=>view.players.find(p=>p.catalogue.player_id===id)?.catalogue.position);
  bench.append(text('p',`Formation: ${['DEF','MID','FWD'].map(p=>positions.filter(x=>x===p).length).join('–')}`));
  squad(area,'Current squad · 15',view.team.current_squad); squad(area,'Resulting squad · 15',recommended,tactics);
  const quality=card('Range, confidence & scope');
  quality.append(text('p',`Paired gain p10 / median / p90: ${comparison.gain_p10} / ${comparison.gain_median} / ${comparison.gain_p90}. Probability of improvement: ${fmt(100*(comparison.probability_plan_beats_baseline ?? comparison.probability_recommended_beats_baseline))}%.`));
  quality.append(text('p',d.action_space_disclosure));
  quality.append(text('p','Three-GW player means are sums of existing Gameweek means. Marginal percentiles and start probabilities are not combined.'));
  quality.append(text('p',view.restrictions.join(' · '),'warning'));
  details(quality,'Engine quality report, free transfers, bank and assumptions',view.team.report);
  details(quality,'Warnings',d.warnings);
}
function showDecisions() {
  const d=view.team.decision, points=d.transfer_frontier?.points || [], c=card('Evaluated transfer frontier');
  c.append(text('p','These plans were evaluated on the same declared scenarios. Extra transfers may change the whole plan; they are not necessarily incremental.'));
  table(c,['Transfers','Plan','Immediate xPts','Horizon xPts','Gain vs hold','Bank £','FT next'],points.map(p => [p.transfer_count,p.transfers.map(t=>`${names(t.player_out_id)} → ${names(t.player_in_id)}`).join('; ') || 'Hold',fmt(p.immediate_expected_points_after_hit ?? p.comparison_vs_hold?.plan_expected_points_after_hit),fmt(p.expected_horizon_utility),fmt(p.horizon_uplift_vs_hold ?? p.comparison_vs_hold?.expected_uplift),fmt(p.bank_after_tenths/10),p.free_transfers_entering_next_gameweek ?? p.free_transfer_state?.next_decision_deadline ?? 'See report']));
  points.forEach(p => {const q=card(`${p.transfer_count} transfer(s) · paired outcome`); const comparison=p.paired_horizon_comparison || p.comparison_vs_hold; pmf(q,Object.fromEntries(comparison.gain_pmf.map(x=>[x.points,x.probability]))); details(q,'Exact evaluated plan and paired downside',p);});
  if (d.future_plan) details(c,'Provisional future plans · reoptimise at each deadline',d.future_plan);
}
function showPlayers() {
  const grid=text('div','','grid'); $('content').append(grid); metric(grid,'CATALOGUE',view.catalogue_count);metric(grid,'VALID PROJECTIONS',view.projected_count);metric(grid,'UNAVAILABLE',view.blocked_count);
  const c=card('Player Lab'), controls=text('div','','toolbar'), search=document.createElement('input'), sort=document.createElement('select'); search.placeholder='Search player, team or position';search.setAttribute('aria-label','Search players');
  [['expected_points','Current GW xPts'],['three_gameweek_expected_points','Three-GW xPts'],['points_per_price','xPts per £'],['expected_minutes','Expected minutes'],['p_start','Start probability'],['p_60_plus','60+ probability'],['goals_contribution','Goal xPts'],['assists_contribution','Assist xPts'],['clean_sheet_contribution','Clean-sheet xPts'],['bonus_contribution','Bonus xPts'],['price','Price'],['name','Player name']].forEach(([value,label])=>{const o=text('option',label);o.value=value;sort.append(o);});sort.setAttribute('aria-label','Sort players');add(controls,search,sort);c.append(controls);
  const selectA=document.createElement('select'),selectB=document.createElement('select');selectA.setAttribute('aria-label','First player');selectB.setAttribute('aria-label','Second player');
  view.players.filter(p=>p.expected_points!==null).forEach(p=>{[selectA,selectB].forEach(s=>{const o=text('option',p.catalogue.name);o.value=p.catalogue.official_id;s.append(o);});}); selectB.selectedIndex=1;
  const compare=text('button','Compare players'); compare.onclick=async()=>{try{const result=await api(`/api/compare/${selectA.value}/${selectB.value}`);$('content').replaceChildren();renderDetail(result.left);renderDetail(result.right);}catch(e){fail(e);}};add(controls,selectA,selectB,compare);
  const region=text('div','');c.append(region);
  function render() {region.replaceChildren();const query=search.value.toLowerCase();const rows=view.players.filter(p=>`${p.catalogue.name} ${p.catalogue.team} ${p.catalogue.position}`.toLowerCase().includes(query)); rows.sort((a,b)=>{if(sort.value==='name')return a.catalogue.name.localeCompare(b.catalogue.name);const av=sort.value==='price'?a.catalogue.price_tenths:a[sort.value],bv=sort.value==='price'?b.catalogue.price_tenths:b[sort.value];return (bv===null?-Infinity:Number(bv))-(av===null?-Infinity:Number(av));});table(region,['Player','Team / position','Price £','GW xPts','3GW xPts','xPts/£','Minutes','Start %','60+ %','Goal xPts','Assist xPts','Clean-sheet xPts','Bonus xPts','Modelled fixtures','Confidence','Availability'],rows.map(p=>{const b=text('button',p.catalogue.name);b.onclick=()=>openPlayer(p.catalogue.official_id);return[b,`${p.catalogue.team} / ${p.catalogue.position}`,fmt(p.catalogue.price_tenths/10),fmt(p.expected_points),fmt(p.three_gameweek_expected_points),fmt(p.points_per_price),fmt(p.expected_minutes,1),p.p_start===null?'Per fixture':fmt(Number(p.p_start)*100),p.p_60_plus===null?'Per fixture':fmt(Number(p.p_60_plus)*100),fmt(p.goals_contribution),fmt(p.assists_contribution),fmt(p.clean_sheet_contribution),fmt(p.bonus_contribution),p.fixtures.join('; '),p.confidence || 'Unavailable',p.catalogue.unavailable_reason || (p.fallback?'Historical fallback':'Projected')];}));}
  search.oninput=render;sort.onchange=render;render();
}
async function openPlayer(id) {try{const player=await api(`/api/players/${id}`);$('content').replaceChildren();renderDetail(player);}catch(e){fail(e);}}
function renderDetail(player) {
  if (!paired || document.hidden || !view || player.job_id !== view.job_id || performance.now() >= expiresPerf) return;
  const back=text('button','← Player catalogue','back');back.onclick=()=>render();$('content').append(back);
  const c=card(`${player.catalogue.name} · ${player.catalogue.team} · ${player.catalogue.position}`);c.append(text('p',`${player.role} · ${player.catalogue.unavailable_reason || 'Valid Stage-9 projection'} · Evaluated transfer-count frontier: ${player.frontier_transfer_counts.join(', ') || 'No transfer move involving this player'}`));
  Object.entries(player.gameweeks).forEach(([gw,s])=>{const g=card(`Gameweek ${gw}`,c),grid=text('div','','grid');g.append(grid);metric(grid,'EXPECTED POINTS',fmt(s.expected_points));metric(grid,'OUTCOME STANDARD DEVIATION',fmt(s.points_standard_deviation));metric(grid,'MONTE CARLO MEAN SE',fmt(s.monte_carlo_mean_se,4));metric(grid,'EFFECTIVE SCENARIOS',fmt(s.scenario_effective_sample_size,0));pmf(g,s.pmf);g.append(text('p',`p10 / median / p90: ${s.selected_percentiles.p10} / ${s.median_points} / ${s.selected_percentiles.p90}. P(5+): ${fmt(s.probability_5_plus*100)}%; P(10+): ${fmt(s.probability_10_plus*100)}%. Confidence grade ${s.confidence_grade}.`));
    table(g,['Scoring component','Expected points','P(nonzero)'],Object.entries(s.component_breakdown).map(([name,v])=>[name,fmt(v.expected_points,6),`${fmt(v.probability_nonzero*100)}%`]));
    g.append(text('p','These are scoring contributions from coherent scenarios, with correlated components. They are not causal sensitivities or independent error bars.'));
    details(g,'Exact summary, covariance, PMF and numerical provenance',s);
  });
  player.fixtures.forEach(f=>{const q=card(`GW ${f.gameweek}: ${f.home} v ${f.away}`,c),id=player.catalogue.player_id,m=f.minutes[id],s=f.summaries[id];q.append(text('p',`Kickoff: ${f.kickoff_at || 'Unavailable'}. Fixture xPts: ${fmt(s.expected_points)}.`));if(m)q.append(text('p',`Expected minutes ${m.expected_minutes}; start probability ${fmt(Number(m.p_start)*100)}%; 60+ probability ${fmt(Number(m.p_60_plus)*100)}%. Minutes confidence ${m.confidence_grade}. ${m.confidence_reasons.join(', ')}`));details(q,'Fixture assumptions and source warnings',f.warnings);});
  details(c,'Historical evidence, fallback and source limitations',player.warnings);
}
async function showPerformance() {
  const c=card('Model Performance');
  try {
    const report=await api('/api/performance');
    c.append(text('p',`Player evaluation: ${report.real_cohort_status}`,'warning'));
    const recovered=report.recovery;
    if(recovered){
      const history=card('Recovered forecast evidence',c);
      history.append(text('p',`Inventory observed at ${recovered.metadata_as_of}; authority assessment and review receipts were recorded later. Existing forecasts were searched before proposing another cohort. Additional forecasts reported by the owner: ${recovered.additional_owner_report}. This bounded search does not prove absence elsewhere.`));
      table(history,['Family','Level','Temporal custody','Retention','Distinct forecast targets','Evaluation'],recovered.families.map(f=>[f.family_id,f.level,f.classification,f.retention,f.sample_count===null?'Not established':`${f.sample_count} ${f.sample_unit}`,f.evaluation_status]));
      const original=recovered.families.find(f=>f.family_id==='P01_PUBLIC_MATCH_FORECAST');
      if(original){
        const p01=card('P01: original real match forecast',history);
        p01.append(text('p',`Origin ${original.forecast_origin}; frozen ${original.frozen_at}. ${original.sample_count} fixtures with ${original.products_per_sample} products per fixture (${original.forecast_rows} product rows). The fixture outcome count is ${original.sample_count}; no statistical independence assumption is added.`));
        p01.append(text('p',original.explanation));
        p01.append(text('p',`Last authenticated local labels (${recovered.p01_labels.authenticated_at}): ${recovered.p01_labels.final_fixture_count} final, ${recovered.p01_labels.missing_fixture_count} missing or not final. Current provider availability: ${recovered.p01_labels.current_provider_availability}. Real accuracy: unavailable; missing labels are not zero.`,'warning'));
        p01.append(text('p',`Canonical scoring readiness: ${recovered.canonical_resumption}. No acquisition, source retry, scoring, tuning or promotion is enabled by this catalogue.`));
      }
      details(history,'Catalogue identity, original hashes and bounded search coverage',recovered);
    }
    if (!report.synthetic_report) {c.append(text('p','Recovered match evidence and unresolved player custody are shown separately. Real player accuracy remains unavailable until original freeze, every source right and finalized labels are qualified.'));return;}
    c.append(text('p','SYNTHETIC ACCEPTANCE ONLY · Analytic fixture forecasts, separate from the recommendation run. No real historical performance claim or model promotion.'));
    const r=report.synthetic_report, grid=text('div','','grid');c.append(grid);
    metric(grid,'FORECASTS / MISSING',`${r.count} / ${r.missing_count}`);
    metric(grid,'MAE',fmt(r.point_metrics.mae));metric(grid,'RMSE',fmt(r.point_metrics.rmse));metric(grid,'BIAS',fmt(r.point_metrics.signed_bias));
    metric(grid,'5+ BRIER SCORE',fmt(r.probability_5plus.brier_score,4));metric(grid,'RANKED PROBABILITY SCORE',fmt(r.mean_ranked_probability_score,4));metric(grid,'80% OUTCOME INTERVAL COVERAGE',`${fmt(Number(r.central_80_coverage)*100)}%`);metric(grid,'ZERO BASELINE MAE',fmt(r.zero_baseline.mae));
    c.append(text('p','The predeclared zero-points baseline is a diagnostic fixture baseline. It is not a competitive football benchmark. Accuracy does not establish decision regret or rank performance.'));
    const pairs=card('Frozen predictions vs finalized synthetic points',c);
    table(pairs,['Target','GW','Position','Minutes band','Predicted','Actual','Error'],r.pairs.map(p=>[p.target_id.slice(0,12),p.gameweek,p.position,p.minutes_band,fmt(p.predicted),p.actual,fmt(p.error)]));
    const breakdown=card('Error by cohort',c);
    for(const [label,groups] of [['Gameweek',r.by_gameweek],['Position',r.by_position],['Expected minutes',r.by_minutes_band]]) {breakdown.append(text('h3',label));table(breakdown,['Cohort','Count','MAE','RMSE','Bias'],Object.entries(groups).map(([name,m])=>[name,m.count,fmt(m.mae),fmt(m.rmse),fmt(m.signed_bias)]));}
    const calibration=card('Probability calibration · points ≥ 5',c);
    calibration.append(text('p',`Fit status: ${r.calibration_5plus.status}. Exact log-loss policy: ${r.probability_5plus.status}. Calibration is diagnostic; no recalibration is applied.`));
    table(calibration,['Bin','Count','Mean probability','Observed rate'],r.calibration_5plus.reliability.map(b=>[b.bin,b.count,fmt(b.mean_forecast,4),fmt(b.observed_rate,4)]));
    const h=report.synthetic_holdout;
    if(h){const holdout=card('Preregistered chronological paired holdout',c);holdout.append(text('p',`Development forecasts ${h.development_count}; holdout forecasts ${h.holdout_count}. Paired absolute-error delta (challenger minus champion): ${fmt(h.paired_absolute_error_delta)}. Promotion: ${h.promotion}.`));table(holdout,['Model','Holdout N','MAE','RMSE','Bias'],[h.champion,h.challenger].map(v=>[v.model_id,v.count,fmt(v.point_metrics.mae),fmt(v.point_metrics.rmse),fmt(v.point_metrics.signed_bias)]));}
    details(c,'Immutable forecast, label, metric and cohort identities',r);
    const operational = report.operational_report;
    if (operational) {
      const cohort = card('Complete registered cohort runner', c);
      cohort.append(text('p', `${operational.classification}: ${operational.population_players} owned players across ${operational.gameweek_count} synthetic Gameweeks; ${operational.scored_targets}/${operational.expected_targets} targets, attrition ${operational.attrition_count}. Real cohort size ${operational.real_cohort_size}.`));
      table(cohort, ['Component', 'Champion MAE', 'Challenger MAE'], Object.entries(operational.champion_components).map(([name, value]) => [name, fmt(value.mae), fmt(operational.challenger_components[name].mae)]));
      table(cohort, ['Model', 'Minute forecasts scored', 'Minute forecasts unavailable', 'Minutes MAE'], [['Champion', operational.champion_minutes], ['Challenger', operational.challenger_minutes]].map(([name, value]) => [name, value.scored_count, value.unavailable_forecast_count, fmt(value.mean_minutes?.mae)]));
      table(cohort, ['Benchmark', 'Availability', 'Reason'], operational.benchmarks.map(b => [b.benchmark_id, b.status, b.reason]));
      cohort.append(text('p', `${operational.uncertainty_status}. Starts and fixture-level 60+ diagnostics remain unavailable without qualified frozen probabilities and explicit labels. Promotion ${operational.promotion}.`));
      details(cohort, 'Cohort custody, labels and complete diagnostic report', operational);
    }
  } catch(e) {fail(e);}
}
function showHealth(){const c=card('Information set & publication');table(c,['Control','Observed value'],[['Source captured (UTC)',view.source_captured_at],['Information cutoff (UTC)',view.information_cutoff],['Official deadline (UTC)',view.deadline_at],['Presentation expires (UTC)',view.expires_at],['Horizon',view.gameweeks.join(', ')],['Decision identity',view.team.decision.semantic_sha256],['Dataset',view.dataset_mode],['Catalogue / valid / unavailable',`${view.catalogue_count} / ${view.projected_count} / ${view.blocked_count}`],['Retention','Memory only; cleared on supersession, failure, cancellation, expiry and shutdown']]);table(c,['Source','Mode','Received UTC','Usable UTC','Requests'],view.source_vintages.map(v=>[v.source,v.source_mode,v.received_at,v.usable_at,v.requests]));c.append(text('p',`Observed market quota remaining: ${view.market_quota_remaining ?? 'Unavailable'}. Historical score priors remain reconstructed; commit time is not a claim of current match evidence.`));details(c,'Exact source identities and commit times',view.source_vintages);details(c,'Source/rules/model lineage',view.team.decision.lineage);details(c,'Quality and exact engine report',view.team.report);}
function render(){
  if (view && performance.now() >= expiresPerf) clearPresentation();
  $('content').replaceChildren();
  $('page-title').textContent=({team:'My team',players:'Player Lab',decisions:'Decisions',performance:'Model Performance',health:'Data Health'})[page];
  if(page==='performance'){showPerformance();return;}
  if(page==='health') showEligibility($('content'));
  if(!view){
    const c=card('Your next decision starts here');
    c.append(text('p',providerEligibility?.error_code || 'Click Refresh Recommendations to run the existing application stack. A blocked source is reported explicitly.'));
    return;
  }
  ({team:showTeam,players:showPlayers,decisions:showDecisions,health:showHealth})[page]();
}
async function current(expectedJob){
  const started=performance.now(), generation=epoch;
  const value=await api('/api/desk');
  if (!paired || document.hidden || generation!==epoch || value.job_id!==expectedJob) return;
  const remaining=Math.max(0,value.expires_in_seconds*1000-(performance.now()-started));
  if (remaining<=0) {clearPresentation();return;}
  view=value;expiresPerf=performance.now()+remaining;
  $('mode').textContent=value.dataset_mode;$('notice').textContent=`Ready · GW ${value.gameweeks.join(' / ')} · Expires ${value.expires_at}`;
  if(expiry)clearTimeout(expiry);expiry=setTimeout(()=>{clearPresentation();$('notice').textContent='Presentation lifetime ended. Refresh again.';},remaining);render();
}
async function poll(){
  if(!paired||document.hidden)return;
  try{
    const state=await api('/api/status');
    providerEligibility=await api('/api/eligibility');
    $('stages').replaceChildren(...state.stages.map(s=>text('li',s)));
    const reason=state.error_code || providerEligibility?.error_code;
    if(state.status!=='COMPLETE'||!view)$('notice').textContent=({'RIGHTS_BLOCKED_MARKET_REFRESH_NOT_APPROVED':'Live refresh requires a separately eligible source approval. No provider acquisition occurred.','RUN_TIMEOUT':'Refresh timed out and the worker was cleared.','WORKER_CLEANUP_FAILED':'Worker cleanup failed. This runtime is closed; restart the application.','PRESENTATION_LIFETIME_ENDED':'Presentation expired and was cleared.','DECISION_DEADLINE_PASSED':'The official deadline has passed. This recommendation is withheld.','AUTHORIZATION_REVOKED':'Refresh authorization was revoked. The recommendation was cleared.'})[reason] || state.error_action || reason || state.status;
    $('refresh').disabled=state.status==='RUNNING';
    if(state.status==='COMPLETE'){
      if(!view||view.job_id!==state.job_id)await current(state.job_id);
      else if(page==='health')render();
    }else if(state.status!=='PENDING'){
      clearPresentation();
      if(page==='health')render();
    }
  }catch(e){fail(e);}
}
$('pair-form').onsubmit=async e=>{e.preventDefault();const code=$('pair-code').value;$('pair-code').value='';try{const r=await api('/api/session',{pairing_code:code});applyContext(r);paired=true;$('pair-panel').hidden=true;$('workspace').hidden=false;render();polling=setInterval(poll,700);}catch(error){$('pair-panel').append(text('p',error.message));}};
$('refresh').onclick=async()=>{clearPresentation();$('refresh').disabled=true;$('progress').open=true;try{await api('/api/refresh',{horizon:Number($('horizon').value)});await poll();}catch(e){fail(e);$('refresh').disabled=false;}};
$('cancel').onclick=async()=>{clearPresentation();try{await api('/api/cancel',{});$('notice').textContent='Cancelled and cleared';$('refresh').disabled=false;}catch(e){fail(e);}};
$('logout').onclick=async()=>{clearPresentation();providerEligibility=null;if(polling)clearInterval(polling);paired=false;try{await api('/api/logout',{});}catch(e){fail(e);}$('workspace').hidden=true;$('pair-panel').hidden=false;$('pair-panel').replaceChildren(text('h2','Signed out'),text('p','Restart dmf dashboard to create a new private session.'));};
document.querySelectorAll('[data-page]').forEach(b=>b.onclick=()=>{page=b.dataset.page;document.querySelectorAll('[data-page]').forEach(n=>n.classList.toggle('selected',n===b));render();});
document.addEventListener('visibilitychange',()=>{if(document.hidden){clearPresentation();providerEligibility=null;$('stages').replaceChildren();}else if(paired){poll();}});
window.addEventListener('pagehide',()=>{clearPresentation();providerEligibility=null;});window.addEventListener('pageshow',()=>{if(paired)poll();});

// A reload resumes only a server-authenticated session; no private view is restored locally.
api('/api/context').then(context=>{
  if(document.hidden||paired)return;
  applyContext(context);paired=true;$('pair-panel').hidden=true;$('workspace').hidden=false;
  render();polling=setInterval(poll,700);poll();
}).catch(error=>{if(error.name!=='AbortError'&&error.message!=='SESSION_REQUIRED')fail(error);});
