'use strict';
// Manual acceptance using an installed Playwright tool; no frontend build or provider calls.
const fs = require('fs');
const path = require('path');
const childProcess = require('child_process');
const crypto = require('crypto');
const modulePath = process.argv[2];
if (!modulePath) throw new Error('Pass the installed playwright-core module path.');
const {chromium} = require(modulePath);
const executablePath = process.argv[3] || undefined;
const root = process.cwd(), output = path.resolve(root, 'review_pack/dashboard-browser');
fs.mkdirSync(output, {recursive:true});
const command = process.platform === 'win32' ? '.venv/Scripts/dmf.exe' : '.venv/bin/dmf';
const server = childProcess.spawn(path.resolve(root,command), ['dashboard','--demo','--port','8766'], {cwd:root, stdio:['ignore','pipe','pipe'], windowsHide:true});
let startup = '', stage = 'startup', browser;
const faults = [], requests = [];
const started = Date.now();
const receipt = {classification:'REPOSITORY_OWNED_SYNTHETIC_ONLY', provider_calls:0, status:'FAIL'};
function assert(value, message) {if(!value)throw new Error(message);}
async function pairingCode() {
  return new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>reject(new Error('startup timeout')),30000);
    server.stdout.on('data',chunk=>{
      startup+=chunk.toString();
      const match=startup.match(/local page: ([A-Za-z0-9_-]+)/);
      if(match){clearTimeout(timer);const value=match[1];startup='';resolve(value);}
    });
    server.on('exit',()=>{clearTimeout(timer);reject(new Error('server stopped'));});
  });
}
(async()=>{
  try {
    const code=await pairingCode();
    browser=await chromium.launch({headless:true,executablePath,args:['--disable-background-networking','--disable-component-update','--disable-sync','--no-first-run']});
    const context=await browser.newContext({viewport:{width:1440,height:1050}});
    await context.route('**/*',route=>new URL(route.request().url()).origin==='http://127.0.0.1:8766'?route.continue():route.abort());
    const page=await context.newPage();
    page.on('pageerror',()=>faults.push('BROWSER_SCRIPT_ERROR'));
    page.on('response',response=>requests.push({path:new URL(response.url()).pathname,status:response.status()}));
    await page.goto('http://127.0.0.1:8766');
    await page.locator('#pair-code').fill(code);
    await page.getByRole('button',{name:'Connect',exact:true}).click();
    await page.locator('#workspace').waitFor({state:'visible'});
    stage='refresh_one_gameweek';
    await page.getByRole('button',{name:'Refresh Recommendations',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#notice').textContent.startsWith('Ready ·'),{},{timeout:900000});
    const view=await page.evaluate(()=>fetch('/api/desk',{cache:'no-store'}).then(r=>r.json()));
    assert(view.catalogue_count===121&&view.projected_count===120&&view.blocked_count===1,'coverage mismatch');
    assert(view.team.decision.tactics.starting_xi.length===11,'XI mismatch');
    assert(view.team.current_squad.length===15,'squad mismatch');
    receipt.one_gameweek={catalogue:view.catalogue_count,projected:view.projected_count,blocked:view.blocked_count,decision_sha256:view.team.decision.semantic_sha256};
    stage='authenticated_reload';
    await page.reload();
    await page.locator('#workspace').waitFor({state:'visible'});
    await page.waitForFunction(()=>document.querySelector('#notice').textContent.startsWith('Ready ·'));
    const resumed=await page.evaluate(()=>fetch('/api/desk',{cache:'no-store'}).then(r=>r.json()));
    assert(resumed.job_id===view.job_id,'reload did not revalidate the existing server job');
    receipt.authenticated_reload=true;
    await page.screenshot({path:path.join(output,'my-team.png'),fullPage:true});
    stage='player_lab';
    await page.locator('[data-page="players"]').click();
    await page.getByRole('textbox',{name:'Search players'}).fill('Removed synthetic');
    assert(await page.getByRole('button',{name:'Removed synthetic player',exact:true}).count()===1,'missingness absent');
    await page.getByRole('textbox',{name:'Search players'}).fill('');
    await page.screenshot({path:path.join(output,'players.png'),fullPage:true});
    const first=view.players.find(p=>p.expected_points!==null);
    await page.getByRole('button',{name:first.catalogue.name,exact:true}).click();
    await page.waitForFunction(()=>document.body.textContent.includes('Scoring component'));
    assert(await page.locator('svg').count()>0,'distribution absent');
    await page.screenshot({path:path.join(output,'player-detail.png'),fullPage:true});
    await page.locator('[data-page="players"]').click();
    await page.getByRole('button',{name:'Compare players',exact:true}).click();
    await page.waitForFunction(()=>document.querySelectorAll('#content > .card').length===2);
    stage='evaluation';
    await page.locator('[data-page="performance"]').click();
    await page.waitForFunction(()=>document.body.textContent.includes('Frozen predictions vs finalized synthetic points'));
    assert((await page.locator('#content').textContent()).includes('NO RIGHTS-QUALIFIED REAL PROSPECTIVE COHORT'),'real-cohort disclosure absent');
    await page.screenshot({path:path.join(output,'model-performance.png'),fullPage:true});
    stage='decisions_and_health';
    await page.locator('[data-page="decisions"]').click();
    assert((await page.locator('#content').textContent()).includes('Evaluated transfer frontier'),'frontier absent');
    await page.locator('[data-page="health"]').click();
    assert((await page.locator('#content').textContent()).includes('TEAM_SCORE_PRIOR'),'source vintages absent');
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:path.join(output,'mobile-data-health.png'),fullPage:true});
    receipt.mobile_viewport=true;
    stage='logout_cleanup';
    await page.getByRole('button',{name:'Sign out',exact:true}).click();
    await page.waitForFunction(()=>document.body.textContent.includes('Restart dmf dashboard'));
    assert(await page.locator('#content').count()===1&&(await page.locator('#content').textContent())==='','presentation retained');
    assert(faults.length===0,'browser errors');
    receipt.status='PASS';receipt.browser_version=browser.version();receipt.requests=requests;receipt.browser_errors=faults;receipt.elapsed_ms=Date.now()-started;
    receipt.source_js_sha256=crypto.createHash('sha256').update(fs.readFileSync('src/dmf_pulse/dashboard/resources/desk.js')).digest('hex');
  } catch(error) {
    // Never print startup output, pairing values, HTTP bodies or exception details.
    receipt.failure_stage=stage;receipt.elapsed_ms=Date.now()-started;process.exitCode=1;
  } finally {
    startup='';
    if(browser)await browser.close();
    if(process.platform==='win32') {
      childProcess.spawnSync('taskkill',['/PID',String(server.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});
    } else server.kill('SIGTERM');
    fs.writeFileSync(path.join(output,'receipt.json'),JSON.stringify(receipt,null,2)+'\n');
    console.log(JSON.stringify({status:receipt.status,stage,elapsed_ms:receipt.elapsed_ms}));
  }
})();
