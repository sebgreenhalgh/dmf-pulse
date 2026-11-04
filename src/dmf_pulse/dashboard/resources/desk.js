'use strict';
// All live state is memory/DOM only. Never use browser storage or external resources.
const $ = id => document.getElementById(id);
let view = null, page = 'team', polling = null, expiry = null, paired = false, demo = false;
let epoch = 0, expiresPerf = 0;
let syntheticSources = false, providerEligibility = null;
let diagnosticReport = null;
let persistent = false, historyRows = [], analysisStatus = null;
const diagnosticExport = document.createElement('button');
diagnosticExport.textContent='Download safe diagnostics';
diagnosticExport.hidden=true;
$('progress').append(diagnosticExport);
diagnosticExport.onclick=()=>{
  if(!diagnosticReport)return;
  const body=new Blob([JSON.stringify(diagnosticReport,null,2)],{type:'application/json'});
  const url=URL.createObjectURL(body), link=document.createElement('a');
  link.href=url;link.download='dmf-safe-diagnostics.json';link.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
};
function applyContext(context) {
  persistent = context.persistent_history === true;
  if (persistent) setupPersistent();
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
  const actual=providerEligibility.actual_market_quota;
  if(actual){table(c,['Latest charged response','Actual provider header'],[['Remaining credits',actual.remaining_credits],['Used credits',actual.used_credits],['Last request cost',actual.last_request_cost],['Reserved credits',actual.reserved_credits],['Received UTC',actual.received_at],['Reconciles with ledger',actual.consistent_with_ledger?'Yes':'No - further acquisition blocked']]);c.append(text('p','Actual response quota is retained even if the forecast later fails. Reserved credits are a separate budget.'));}
}
const requests = new Set();
const fmt = (x, n = 2) => x === null || x === undefined ? 'Unavailable' : Number(x).toFixed(n);
const moneyTenths = value => value === null || value === undefined ? 'Unavailable' : fmt(value / 10);
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
function fail(error) { if (error.name === 'AbortError') return; if (!persistent) clearPresentation(); $('notice').textContent = error.message || 'REQUEST_FAILED'; }
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
  metric(grid,'CURRENT BANK · £',moneyTenths(view.team.current_bank_tenths));
  metric(grid,'FPL TEAM VALUE · £',moneyTenths(view.team.current_team_value_tenths));
  metric(grid,d.do_now ? '3GW EXPECTED UTILITY' : 'EXPECTED POINTS AFTER HITS',fmt(comparison.plan_expected_horizon_utility ?? comparison.recommended_expected_points_after_hit));
  metric(grid,'GAIN VS HOLD',fmt(comparison.expected_uplift ?? comparison.net_expected_uplift));
  metric(grid,'HIT POINTS',root.hit_points ?? comparison.transfer_hit_points);
  const selected=d.transfer_frontier?.points.find(p=>p.transfer_count===root.transfers.length),ft=root.free_transfer_state || selected?.free_transfer_state;
  metric(grid,'FREE TRANSFERS NOW',ft?.effective_before_action ?? 'Unavailable');
  metric(grid,'BANK AFTER · £',moneyTenths(root.bank_after_tenths ?? selected?.bank_after_tenths));
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
  area.append(text('p',`${demo || syntheticSources ? 'These current values are synthetic demonstration inputs.' : 'Current bank and team value are reported by FPL for this snapshot.'} Team value is not recomputed from selling prices; bank after describes the evaluated transfer plan.`));
  const quality=card('Range, confidence & scope');
  quality.append(text('p',`Paired gain p10 / median / p90: ${comparison.gain_p10} / ${comparison.gain_median} / ${comparison.gain_p90}. Probability of improvement: ${fmt(100*(comparison.probability_plan_beats_baseline ?? comparison.probability_recommended_beats_baseline))}%.`));
  quality.append(text('p',d.action_space_disclosure));
  quality.append(text('p','Simulation percentiles describe possible points. Monte Carlo mean SE measures simulation precision. Forecasts remain unvalidated.'));
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
  showOptimizerEvidence(c);
}
function showPlayers() {
  const grid=text('div','','grid'); $('content').append(grid); metric(grid,'CATALOGUE',view.catalogue_count);metric(grid,'VALID PROJECTIONS',view.projected_count);metric(grid,'UNAVAILABLE',view.blocked_count);
  const c=card('Player Lab'), controls=text('div','','toolbar'), search=document.createElement('input'), sort=document.createElement('select'); search.placeholder='Search player, team or position';search.setAttribute('aria-label','Search players');
  [['expected_points','Current GW xPts'],['three_gameweek_expected_points','Three-GW xPts'],['points_per_price','xPts per £'],['expected_minutes','Expected minutes'],['p_start','Start probability'],['p_60_plus','60+ probability'],['goals_contribution','Goal xPts'],['assists_contribution','Assist xPts'],['clean_sheet_contribution','Clean-sheet xPts'],['bonus_contribution','Bonus xPts'],['price','Price'],['name','Player name']].forEach(([value,label])=>{const o=text('option',label);o.value=value;sort.append(o);});sort.setAttribute('aria-label','Sort players');add(controls,search,sort);c.append(controls);
  const selectA=document.createElement('select'),selectB=document.createElement('select');selectA.setAttribute('aria-label','First player');selectB.setAttribute('aria-label','Second player');
  view.players.filter(p=>p.expected_points!==null).forEach(p=>{[selectA,selectB].forEach(s=>{const o=text('option',p.catalogue.name);o.value=p.catalogue.official_id;s.append(o);});}); selectB.selectedIndex=1;
  const compare=text('button','Compare players'); compare.onclick=async()=>{try{const result=await api(`/api/compare/${selectA.value}/${selectB.value}`);$('content').replaceChildren();renderDetail(result.left);renderDetail(result.right);}catch(e){fail(e);}};add(controls,selectA,selectB,compare);
  const region=text('div','');c.append(region);
  if(view.dataset_mode === 'PRIVATE_RETAINED_AS_OF' && !analysisStatus?.fixture_details_available) {compare.disabled=true;selectA.disabled=true;selectB.disabled=true;c.append(text('p','Saved player means are available below. Detailed distributions belonged to the original live session.'))}
  function render() {region.replaceChildren();const query=search.value.toLowerCase();const rows=view.players.filter(p=>`${p.catalogue.name} ${p.catalogue.team} ${p.catalogue.position}`.toLowerCase().includes(query)); rows.sort((a,b)=>{if(sort.value==='name')return a.catalogue.name.localeCompare(b.catalogue.name);const av=sort.value==='price'?a.catalogue.price_tenths:a[sort.value],bv=sort.value==='price'?b.catalogue.price_tenths:b[sort.value];return (bv===null?-Infinity:Number(bv))-(av===null?-Infinity:Number(av));});table(region,['Player','Team / position','Price £','GW xPts','p10 / median / p90','Mean MC SE','3GW xPts','xPts/£','Minutes','Start %','60+ %','Goal xPts','Assist xPts','Clean-sheet xPts','Bonus xPts','Modelled fixtures','Confidence','Availability'],rows.map(p=>{const b=text('button',p.catalogue.name);b.onclick=()=>openPlayer(p.catalogue.official_id);return[b,`${p.catalogue.team} / ${p.catalogue.position}`,fmt(p.catalogue.price_tenths/10),fmt(p.expected_points),p.points_p10 == null ? 'Unavailable' : `${p.points_p10} / ${p.median_points} / ${p.points_p90}`,fmt(p.monte_carlo_mean_se,4),fmt(p.three_gameweek_expected_points),fmt(p.points_per_price),fmt(p.expected_minutes,1),p.p_start===null?'Per fixture':fmt(Number(p.p_start)*100),p.p_60_plus===null?'Per fixture':fmt(Number(p.p_60_plus)*100),fmt(p.goals_contribution),fmt(p.assists_contribution),fmt(p.clean_sheet_contribution),fmt(p.bonus_contribution),p.fixtures.join('; '),p.confidence || 'Unavailable',p.catalogue.unavailable_reason || (p.fallback?'Historical fallback':'Projected')];}));}
  search.oninput=render;sort.onchange=render;render();
}
async function openPlayer(id) {if(view?.dataset_mode === 'PRIVATE_RETAINED_AS_OF' && !analysisStatus?.fixture_details_available) {$('notice').textContent='Saved as-of player means are shown in the table. Detailed distributions are unavailable in this retained snapshot.';return;}try{const player=await api(`/api/players/${id}`);$('content').replaceChildren();renderDetail(player);}catch(e){fail(e);}}
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
function showHealth(){
  if(persistent && analysisStatus?.last_failure?.length){
    const failure=analysisStatus.last_failure[0], c=card('Last unsuccessful refresh');
    table(c,['Attempt','Recorded UTC','Reason'],[[failure.attempt_id,failure.recorded_at,failure.error_code]]);
    details(c,'Retained safe failure and last observed quota evidence',JSON.parse(failure.derived_json || '{}'));
  }
  const c=card('Information set & publication'), quota=view.market_quota_receipt;
  const retention=view.restrictions.includes('PRIVATE_DERIVED_RECEIPT_RETAINED_SOURCE_BODIES_TRANSIENT')?'Source inputs are transient. Derived recommendations and audit receipts are retained privately.':'Memory-only presentation; cleared when the session ends.';
  table(c,['Control','Observed value'],[['Source captured (UTC)',view.source_captured_at],['Information cutoff (UTC)',view.information_cutoff],['Official deadline (UTC)',view.deadline_at],['Presentation expires (UTC)',view.expires_at],['Horizon',view.gameweeks.join(', ')],['Decision identity',view.team.decision.semantic_sha256],['Dataset',view.dataset_mode],['Catalogue / valid / unavailable',`${view.catalogue_count} / ${view.projected_count} / ${view.blocked_count}`],['Retention',retention]]);
  table(c,['Source','Mode','Received UTC','Usable UTC','Requests'],view.source_vintages.map(v=>[v.source,v.source_mode,v.received_at,v.usable_at,v.requests]));
  table(c,['Market quota','Observed value'],[
    ['Remaining credits',quota?.remaining_credits ?? view.market_quota_remaining ?? 'Unavailable'],
    ['Account period used credits',quota?.used_credits ?? 'Unavailable'],
    ['Actual last request cost (credits)',quota?.last_request_cost ?? 'Unavailable'],
    ['Transport calls',quota?.transport_call_count ?? 'Unavailable'],
    ['Received (UTC)',quota?.received_at ?? 'Unavailable'],
    ['Evidence source',quota?.source ?? 'Unavailable']
  ]);
  c.append(text('p',view.dataset_mode === 'PRIVATE_TRANSIENT' ? 'Last request cost comes from the provider response header. Reserved credits are a separate budget, and account period usage includes other requests.' : 'Quota is the last recorded observation at the timestamp above, not a current live balance.'));
  c.append(text('p','Historical score priors remain reconstructed; commit time is not a claim of current match evidence.'));
  if(quota) details(c,'Complete market quota receipt',quota);
  details(c,'Exact source identities and commit times',view.source_vintages);details(c,'Source/rules/model lineage',view.team.decision.lineage);details(c,'Quality and exact engine report',view.team.report);
}
function render(){
  if (!persistent && view && performance.now() >= expiresPerf) clearPresentation();
  $('content').replaceChildren();
  $('page-title').textContent=({team:'My Squad',players:'Player Forecasts',decisions:'Transfers',captaincy:'Captaincy',history:'History',performance:'Model Performance',health:'Data Status'})[page];
  if(page==='history'){showHistory();return;}
  if(page==='performance'){showPerformance();return;}
  if(page==='health') showEligibility($('content'));
  if(!view){
    const c=card('Your next decision starts here');
    c.append(text('p',providerEligibility?.error_code || 'Click Refresh Recommendations to run the existing application stack. A blocked source is reported explicitly.'));
    return;
  }
  ({team:showTeam,players:showPlayers,decisions:showDecisions,captaincy:showCaptaincy,health:showHealth})[page]();
}
async function current(expectedJob){
  const started=performance.now(), generation=epoch;
  const value=await api('/api/desk');
  if (!paired || document.hidden || generation!==epoch || value.job_id!==expectedJob) return;
  const remaining=Math.max(0,value.expires_in_seconds*1000-(performance.now()-started));
  if (remaining<=0) {clearPresentation();return;}
  view=value;expiresPerf=performance.now()+remaining;
  $('mode').textContent=value.dataset_mode;$('notice').textContent=`Ready · Unvalidated forecasts · GW ${value.gameweeks.join(' / ')} · Expires ${value.expires_at}`;
  if(value.dataset_mode === 'PRIVATE_RETAINED_AS_OF') $('notice').textContent=`Saved as-of ${value.generated_at}. Unvalidated GW ${value.gameweeks.join(' / ')} snapshot; no new paid acquisition. This is not current data.`;
  if(expiry)clearTimeout(expiry);expiry=setTimeout(()=>{clearPresentation();$('notice').textContent='Presentation lifetime ended. Refresh again.';},remaining);render();
}
async function poll(){
  if(persistent) {await pollPersistent();return;}
  if(!paired||document.hidden)return;
  try{
    const state=await api('/api/status');
    diagnosticReport=state.diagnostics || null;
    diagnosticExport.hidden=diagnosticReport===null;
    providerEligibility=await api('/api/eligibility');
    $('stages').replaceChildren(...state.stages.map(s=>text('li',s)));
    const reason=state.error_code || providerEligibility?.error_code;
    if(state.status!=='COMPLETE'||!view)$('notice').textContent=({'RIGHTS_BLOCKED_MARKET_REFRESH_NOT_APPROVED':'Live refresh requires a separately eligible source approval. No provider acquisition occurred.','RUN_TIMEOUT':'Refresh timed out and the worker was cleared.','WORKER_CLEANUP_FAILED':'Worker cleanup failed. This runtime is closed; restart the application.','PRESENTATION_LIFETIME_ENDED':'Presentation expired and was cleared.','DECISION_DEADLINE_PASSED':'The official deadline has passed. This recommendation is withheld.','AUTHORIZATION_REVOKED':'Refresh authorization was revoked. The recommendation was cleared.'})[reason] || state.error_action || reason || state.status;
    if(state.diagnostics?.failure && state.status!=='COMPLETE') {
      const failure=state.diagnostics.failure;
      const stage=failure.stage.replaceAll('_',' ').toLowerCase();
      const category=failure.category.replaceAll('_',' ').toLowerCase();
      const counts=['FPL','ODDS','OPENFOOTBALL'].map(provider=>{
        const rows=state.diagnostics.requests.filter(row=>row.identity.provider===provider);
        return `${provider} ${rows.filter(row=>row.response_completed_at!==null).length}/${rows.length}`;
      }).join('; ');
      const partial=state.diagnostics.worker_terminal_received && state.diagnostics.chronology_complete?'':' Partial worker record.';
      const integrity=failure.integrity_reason?` Integrity reason: ${failure.integrity_reason}.`:'';
      $('notice').textContent=`${reason}: blocked during ${stage} (${category}).${integrity} Observed completed responses / admissions: ${counts}.${partial} ${state.error_action||''}`;
    }
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
$('refresh').onclick=async()=>{if(persistent){await refreshPersistent();return;}clearPresentation();$('refresh').disabled=true;$('progress').open=true;try{await api('/api/refresh',{horizon:Number($('horizon').value)});await poll();}catch(e){fail(e);$('refresh').disabled=false;}};
$('cancel').onclick=async()=>{if(!persistent)clearPresentation();try{await api('/api/cancel',{});$('notice').textContent='Cancelled and cleared';$('refresh').disabled=false;}catch(e){fail(e);}};
$('logout').onclick=async()=>{clearPresentation();providerEligibility=null;if(polling)clearInterval(polling);paired=false;try{await api('/api/logout',{});}catch(e){fail(e);}$('workspace').hidden=true;$('pair-panel').hidden=false;$('pair-panel').replaceChildren(text('h2','Signed out'),text('p','Restart dmf dashboard to create a new private session.'));};
document.querySelectorAll('[data-page]').forEach(b=>b.onclick=()=>{page=b.dataset.page;document.querySelectorAll('[data-page]').forEach(n=>n.classList.toggle('selected',n===b));render();});
document.addEventListener('visibilitychange',()=>{if(document.hidden){if(!persistent)clearPresentation();providerEligibility=null;$('stages').replaceChildren();}else if(paired){poll();}});
window.addEventListener('pagehide',()=>{clearPresentation();providerEligibility=null;});window.addEventListener('pageshow',()=>{if(paired)poll();});

// A reload resumes only a server-authenticated session; no private view is restored locally.
// A deferred script installs both handlers before session bootstrap. Browser
// controllers must wait for document completion and this readiness marker.
document.documentElement.dataset.dmfReady = 'true';
api('/api/context').then(context=>{
  if(document.hidden||paired)return;
  applyContext(context);paired=true;$('pair-panel').hidden=true;$('workspace').hidden=false;
  render();polling=setInterval(poll,700);poll();
}).catch(error=>{if(error.name!=='AbortError'&&error.message!=='SESSION_REQUIRED')fail(error);});

// Persistent operation reads SQLite history; only the explicit action below acquires.
let persistentSetup = false, persistentPolling = false, refreshChallenge = null;
function setupPersistent() {
  if(persistentSetup)return;
  persistentSetup=true;
  $('refresh').textContent='Refresh Data & Recommendations';
  $('horizon').closest('label').hidden=true;
  $('cancel').textContent='Cancel refresh';
  document.querySelector('.aside-note').textContent='Private workspace ? Saved local history';
  const nav=document.querySelector('nav');
  [['team','MY SQUAD'],['players','PLAYER FORECASTS'],['decisions','TRANSFERS'],['captaincy','CAPTAINCY'],['history','HISTORY'],['health','DATA STATUS']].forEach(([id,label])=>{
    let button=nav.querySelector(`[data-page="${id}"]`);
    if(!button){button=text('button',label);button.dataset.page=id;nav.append(button);}
    button.textContent=label;
    button.onclick=()=>{page=id;nav.querySelectorAll('button').forEach(b=>b.classList.toggle('selected',b===button));render();};
  });
  const modal=document.createElement('dialog');modal.id='fpl-dialog';modal.setAttribute('aria-labelledby','fpl-title');
  const title=text('h2','Fresh FPL credential');title.id='fpl-title';modal.append(title);
  modal.append(text('p','Enter a newly issued FPL JWT here only. Expiry is read automatically. The saved result remains available.'));
  const form=document.createElement('form'), label=text('label','FPL JWT'), input=document.createElement('input');
  input.id='fresh-fpl-jwt';input.type='password';input.autocomplete='off';input.spellcheck=false;input.maxLength=3800;input.required=true;label.htmlFor=input.id;
  const submit=text('button','Register & refresh','primary');submit.type='submit';
  const dismiss=text('button','Cancel');dismiss.type='button';dismiss.onclick=()=>modal.close();
  form.append(label,input,submit,dismiss);modal.append(form);document.body.append(modal);
  modal.addEventListener('close',()=>{input.value='';refreshChallenge=null;$('refresh').disabled=false;});
  form.onsubmit=async event=>{
    event.preventDefault();
    let value=input.value;input.value='';
    const payload={token:value,challenge:refreshChallenge};value='';refreshChallenge=null;
    submit.disabled=true;modal.close();$('refresh').disabled=true;
    try{await api('/api/credentials/fpl',payload);$('progress').open=true;await pollPersistent();}
    catch(error){fail(error);}finally{payload.token='';submit.disabled=false;}
  };
}
async function refreshPersistent(){
  $('refresh').disabled=true;
  try{
    const state=await api('/api/refresh',{horizon:1});
    if(state.credential_challenge){refreshChallenge=state.credential_challenge;$('fpl-dialog').showModal();$('fresh-fpl-jwt').focus();}
    else {$('notice').textContent=state.error_code || state.status;await pollPersistent();}
  }catch(error){fail(error);$('refresh').disabled=false;}
}
async function pollPersistent(){
  if(!paired||document.hidden||persistentPolling)return;
  persistentPolling=true;
  try{
    const state=await api('/api/status');
    diagnosticReport=state.diagnostics || null;diagnosticExport.hidden=diagnosticReport===null;
    $('stages').replaceChildren(...state.stages.map(s=>text('li',s)));
    $('refresh').disabled=state.status==='RUNNING' || $('fpl-dialog').open;
    providerEligibility=await api('/api/eligibility');
    analysisStatus=await api('/api/analysis/status');
    if(!view||view.job_id!==analysisStatus.selected_run){
      try{view=await api('/api/desk');expiresPerf=Infinity;render();}catch(error){if(error.message!=='NO_CURRENT_RECOMMENDATION')throw error;}
    }
    const provenance=analysisStatus.provenance_class==='GW10_DIAGNOSTIC'?'GW10 DIAGNOSTIC | REAL-DATA-DERIVED':analysisStatus.provenance_class==='OWNED_SYNTHETIC'?'OWNED SYNTHETIC | ENGINEERING ONLY':'NORMAL STANDING | REAL-DATA-DERIVED';
    $('mode').textContent=`${provenance} | UNVALIDATED | HISTORICAL AS-OF`;
    $('notice').textContent=(state.status==='RUNNING'?'Refreshing - saved result remains visible. ':state.error_code?`${state.error_code}. Saved result retained. `:'')+(view?`Forecast generated ${view.generated_at}; information cutoff ${view.information_cutoff}. Historical as-of, not current data.`:'No successful snapshot is saved.');
    if(page==='health')render();
  }catch(error){fail(error);}finally{persistentPolling=false;}
}
function showCaptaincy(){
  const d=view.team.decision, root=d.do_now || d, c=card('Captain and vice-captain');
  c.append(text('p',`Captain: ${names(root.tactics.captain)} | Vice-captain: ${names(root.tactics.vice_captain)}`));
  table(c,['Player','Standalone xPts','Role'],view.players.filter(p=>[root.tactics.captain,root.tactics.vice_captain].includes(p.catalogue.player_id)).map(p=>[p.catalogue.name,fmt(p.expected_points),p.catalogue.player_id===root.tactics.captain?'Captain':'Vice-captain']));
  c.append(text('p','Standalone player means do not establish why this pair was selected. The exact captaincy comparison, joint counterfactuals and explanation are unavailable in the retained engine output. No explanation has been reconstructed.'));
  details(c,'Actual recommended tactical evidence',root.tactics);
  if(d.no_transfer_tactics)details(c,'Actual hold tactical evidence',d.no_transfer_tactics);
  details(c,'Actual optimizer objective and action space',d.action_space_disclosure || d);
  details(c,'Actual paired plan outcome (not a captain-only counterfactual)',d.paired_comparison || d.horizon_comparison);
  showOptimizerEvidence(c);
}
async function showOptimizerEvidence(parent){
  if(!persistent)return;
  const expected=view?.job_id;
  try{
    const evidence=await api('/api/analysis/optimizer');
    if(!paired||view?.job_id!==expected||evidence.run_id!==expected)return;
    if(evidence.optimizer_evidence){
      parent.append(text('p','The actual optimizer result is retained below, including evaluated alternatives, plan outcomes and move interactions. It does not establish a captain-only explanation.'));
      details(parent,'Actual typed optimizer evidence',evidence.optimizer_evidence.optimiser_result);
    }else parent.append(text('p','The full optimizer object was unavailable in the original retained snapshot.'));
  }catch(error){parent.append(text('p',error.message));}
}
async function showHistory(){
  const c=card('Immutable saved runs');
  try{
    historyRows=await api('/api/history');
    const controls=text('div','','toolbar'), first=document.createElement('select'), second=document.createElement('select');
    first.setAttribute('aria-label','First saved run');second.setAttribute('aria-label','Second saved run');
    historyRows.forEach(row=>[first,second].forEach(select=>{const option=text('option',`GW ${row.gameweek} | ${row.generated_at} | ${row.run_id.slice(0,12)}`);option.value=row.run_id;select.append(option);}));
    second.selectedIndex=historyRows.length>1?1:0;
    const compare=text('button','Compare saved runs'), comparison=text('div','');compare.disabled=historyRows.length<2;
    compare.onclick=async()=>{try{
      const value=await api('/api/history/compare',{first_run_id:first.value,second_run_id:second.value});
      comparison.replaceChildren();const result=card('Saved run comparison',comparison);
      result.append(text('p','Observed differences across retained inputs and Gameweeks. These are not causal explanations, measured accuracy or evidence of improved model skill.'));
      table(result,['Run','GW','Generated UTC','Provenance','Validation'],[value.first,value.second].map(r=>[r.run_id.slice(0,16),r.gameweeks.join(' / '),r.generated_at,r.provenance_class,r.validation]));
      table(result,['Player (old / new)','Old xPts','New xPts','Observed delta'],value.players.map(p=>[p.old_name===p.new_name?p.new_name:`${p.old_name || 'Unavailable'} / ${p.new_name || 'Unavailable'}`,fmt(p.old_expected_points),fmt(p.new_expected_points),fmt(p.expected_points_delta)]));
      details(result,'First saved squad, transfers and captaincy',value.first.team);
      details(result,'Second saved squad, transfers and captaincy',value.second.team);
      details(result,'Exact computation versions and comparison restriction', {first:value.first.implementation_sha,second:value.second.implementation_sha,restriction:value.attribution});
    }catch(error){comparison.replaceChildren(text('p',error.message));}};
    controls.append(first,second,compare);c.append(controls,comparison);
    table(c,['Run','GW','Generated UTC','Information cutoff','Provenance','Validation'],historyRows.map(row=>{
      const button=text('button',row.run_id.slice(0,16));
      button.onclick=async()=>{try{view=await api('/api/history/select',{run_id:row.run_id});expiresPerf=Infinity;page='team';render();await pollPersistent();}catch(error){fail(error);}};
      return [button,row.gameweek,row.generated_at,row.information_cutoff,row.provenance_class,row.validation];
    }));
    c.append(text('p','Selecting a run reads the local warehouse only. Numerical differences between runs are observable changes, not causal explanations. Read-only SQL and private exports are available through dmf analysis.'));
  }catch(error){c.append(text('p',error.message));}
}
