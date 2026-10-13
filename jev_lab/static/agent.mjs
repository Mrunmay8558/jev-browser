const $ = id => document.getElementById(id);
const terminal = new Set(['completed', 'failed', 'stopped', 'limit_reached']);
const modeNames = {demo: 'Local demo', jev: 'Jev only', live: 'Gemini + Jev'};
let config, run = null, mode = 'jev', working = false, detached = false;
const desktop = window.jevDesktop;
let desktopState = {url: ''};
let lastImage = -1, lastEvents = -1, displayedRun = '', pollTimer;

function error(message = '') {
  $('error').textContent = message;
  $('error').hidden = !message;
}
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
  });
  const data = await response.json();
  if (!response.ok) throw Error(data.details?.map(d => d.message).join(' ') || data.error || 'Request failed.');
  return data;
}
function isActive() { return run && !terminal.has(run.status); }
function setMode(value) {
  mode = value;
  for (const button of document.querySelectorAll('[data-mode]')) {
    button.setAttribute('aria-pressed', String(button.dataset.mode === mode));
  }
  const notes = {
    demo: 'Local demo · real browser actions, scripted decisions. No API keys needed.',
    jev: 'Python builds possible actions → Jev chooses → browser acts. Requires only a Jev key.',
    live: 'Gemini proposes actions → Jev evaluates → browser acts. Requires both keys.'
  };
  $('mode-note').textContent = notes[mode];
  $('key-note').textContent = config ? `Keys configured: Jev ${config.jevConfigured ? '✓' : 'missing'} · Gemini ${config.geminiConfigured ? '✓' : 'missing'}. Add missing keys to .env and restart the Python server.` : '';
  $('start-url').disabled = mode === 'demo' || isActive();
}
function showSettings(show) {
  if (show) $('settings').showModal(); else $('settings').close();
  $('settings-toggle').setAttribute('aria-expanded', String(show));
  reportBounds();
}
function emptyBrowser(takeover = false) {
  $('screen').hidden = true;
  $('screen-empty').hidden = false;
  $('empty-title').textContent = takeover ? 'The browser is yours.' : 'A front-row seat to every step.';
  $('empty-text').textContent = takeover
    ? (desktop ? 'Continue directly in the browser on the right, then resume.' : 'Switch to the Chrome window to continue. Page capture is paused until you resume.')
    : (desktop ? 'Enter a website address above, or send a task in chat. This pane is a real browser.' : 'Send a task to open Chrome. Page snapshots and the agent cursor appear here.');
}
function renderMessages(nearBottom) {
  const thread = $('thread');
  if (lastEvents === run.events.length) return;
  const wasEmpty = lastEvents < 0;
  lastEvents = run.events.length;
  const nodes = [];
  for (const event of run.events) {
    if (['observe', 'judge'].includes(event.kind)) continue;
    if (event.kind === 'plan' && !event.actions?.length) continue;
    const node = document.createElement('div');
    node.className = event.kind === 'user' ? 'message user'
      : ['action', 'control', 'retry'].includes(event.kind) ? 'activity'
      : 'message assistant';
    node.textContent = event.kind === 'action' ? `✓ ${event.message}` : event.message;
    if (event.kind === 'complete' && run.result) {
      node.className += ' result';
      for (const quote of run.result.evidence) {
        const evidence = document.createElement('div');
        evidence.className = 'evidence'; evidence.textContent = quote; node.append(evidence);
      }
      const link = document.createElement('a');
      try {
        const url = new URL(run.result.url);
        if (['http:', 'https:'].includes(url.protocol)) {
          link.href = url.href; link.target = '_blank'; link.rel = 'noreferrer';
          link.textContent = 'Open result URL ↗'; node.append(link);
        }
      } catch { /* The result text remains visible if the URL is malformed. */ }
    }
    nodes.push(node);
  }
  $('messages').replaceChildren(...nodes);
  if (nearBottom || wasEmpty) thread.scrollTop = thread.scrollHeight;
}
function render(data) {
  if (!data || detached) return;
  if (data.id === displayedRun && data.events.length < lastEvents) return;
  const followConversation = $('thread').scrollHeight - $('thread').scrollTop - $('thread').clientHeight < 100;
  if (data.id !== displayedRun) {
    displayedRun = data.id; lastEvents = -1; lastImage = -1;
    setMode(data.mode);
  }
  run = data;
  $('welcome').hidden = true;
  const active = isActive();
  for (const button of document.querySelectorAll('[data-mode]')) button.disabled = active;
  for (const id of ['new-chat', 'max-steps', 'threshold', 'form-values']) $(id).disabled = active;
  $('start-url').disabled = active || mode === 'demo';
  $('send').disabled = working || !config;
  $('task').maxLength = active ? 2000 : 4000;
  $('task').placeholder = active ? 'Add details or change the next steps…' : 'Ask the browser to do something…';
  $('composer-hint').textContent = active ? 'Send guidance' : 'Enter to send';
  $('pause').disabled = !active || !!run.pending;
  $('stop').disabled = !active;
  $('focus').disabled = !run.page;
  $('status').textContent = run.status.replaceAll('_', ' ');
  $('status').className = 'status ' + run.status;
  $('step').textContent = `Step ${run.step} / ${run.maxSteps} · ${modeNames[run.mode]}`;
  $('message').textContent = run.message;
  if (!desktop) $('url').textContent = run.page?.url || 'Opening Chrome…';
  $('metrics').textContent = `Gemini: ${run.modelCalls?.gemini || 0} calls · Jev: ${run.modelCalls?.jev || 0} calls · ${Math.round(run.elapsedSeconds || 0)}s`;
  if (!desktop && lastImage !== run.imageRevision) {
    lastImage = run.imageRevision;
    if (['handoff', 'paused'].includes(run.status)) emptyBrowser(true);
    else if (lastImage > 0) {
      $('screen').src = `/api/agent/runs/${run.id}/screen?v=${lastImage}`;
      $('screen').hidden = false; $('screen-empty').hidden = true;
    }
  }
  $('handoff').hidden = !run.pending;
  if (run.pending) {
    $('handoff-title').textContent = run.status === 'approval' ? 'Review this action' : 'Your input is needed';
    $('handoff-message').textContent = run.pending.message;
    $('approve').hidden = run.status !== 'approval';
    $('resume').textContent = run.status === 'approval' ? 'Skip & replan' : 'Resume';
  }
  renderMessages(followConversation);
  $('inspector').textContent = run.lastDecision ? JSON.stringify({
    mode: modeNames[run.mode],
    candidateSource: run.mode === 'jev' ? 'Python / observed DOM + supplied values' : run.mode === 'live' ? 'Gemini' : 'Scripted demo',
    modelCalls: run.modelCalls, ...run.lastDecision
  }, null, 2) : 'No decision yet.';
}
async function poll() {
  clearTimeout(pollTimer);
  if (!detached) {
    try {
      const data = await api(run ? `/api/agent/runs/${run.id}` : '/api/agent/current');
      if (data) render(data);
    } catch (e) { error(e.message); }
  }
  pollTimer = setTimeout(poll, isActive() && !run.pending ? 250 : 1500);
}
function formValues() {
  const values = {};
  for (const line of $('form-values').value.split('\n').filter(line => line.trim())) {
    const match = line.match(/^\s*([^:]{1,80}):\s*(.+?)\s*$/);
    if (!match) throw Error('Use one Field label: value per line in Task settings.');
    values[match[1].trim()] = match[2];
  }
  return values;
}
async function sendMessage(event) {
  event?.preventDefault();
  const task = $('task').value.trim();
  if (!task || working || !config) return;
  working = true; $('send').disabled = true; error();
  try {
    if (isActive()) {
      render(await api(`/api/agent/runs/${run.id}/control`, {command: 'message', message: task}));
    } else {
      if (mode === 'jev' && !config.jevOnlyAvailable) throw Error('Jev-only needs TYPESAFE_API_KEY in .env. Gemini is optional. Add the key and restart.');
      if (mode === 'live' && !config.liveAvailable) throw Error('Gemini + Jev needs GEMINI_API_KEY and TYPESAFE_API_KEY in .env. Add them and restart.');
      let startUrl = $('start-url').value.trim();
      if (!startUrl && mode !== 'demo') startUrl = task.match(/https?:\/\/[^\s<>]+/)?.[0] || '';
      // The server resolves explicit website names and task URLs before opening a browser.
      if (startUrl.includes('/demo/')) {startUrl = ''; $('form-values').value = '';} 
      const data = await api('/api/agent/runs', {
        task, start_url: mode === 'demo' ? '' : startUrl, mode,
        inputs: mode === 'demo' ? {} : formValues(),
        max_steps: Number($('max-steps').value), threshold: Number($('threshold').value)
      });
      detached = false; lastEvents = -1; lastImage = -1; render(data);
    }
    $('task').value = '';
  } catch (e) { error(e.message); }
  finally { working = false; $('send').disabled = false; }
}
$('composer').addEventListener('submit', sendMessage);
$('task').addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) sendMessage(event);
});
for (const button of document.querySelectorAll('[data-mode]')) button.addEventListener('click', () => {
  if (!isActive()) { setMode(button.dataset.mode); error(); }
});
$('preset').addEventListener('click', () => {
  $('task').value = 'Open MakeMyTrip and search for Dubai flights. Show me the options before booking.';
  $('start-url').value = 'https://www.makemytrip.com/flights/';
  $('form-values').value = 'To: Dubai';
  $('task').focus();
});
$('new-chat').addEventListener('click', () => {
  if (isActive()) return;
  detached = true; run = null; displayedRun = ''; lastEvents = lastImage = -1;
  $('messages').replaceChildren(); $('welcome').hidden = false; $('handoff').hidden = true;
  $('start-url').value = ''; $('form-values').value = '';
  $('task').value = ''; $('task').placeholder = 'Ask the browser to do something…';
  $('status').textContent = 'Ready'; $('step').textContent = 'Ready when you are';
  $('message').textContent = 'Choose a mode and send a task in the chat.';
  $('url').textContent = 'Your browser will appear here'; $('metrics').textContent = 'No model calls yet';
  $('inspector').textContent = 'No decision yet.'; $('focus').disabled = true;
  error(); emptyBrowser(); setMode(mode);
});
$('settings-toggle').addEventListener('click', () => showSettings(true));
$('close-settings').addEventListener('click', () => showSettings(false));
$('save-settings').addEventListener('click', () => showSettings(false));
$('settings').addEventListener('close', () => {$('settings-toggle').setAttribute('aria-expanded', 'false'); reportBounds();});
for (const command of ['pause', 'stop', 'resume', 'approve', 'focus']) {
  $(command).addEventListener('click', async () => {
    if (!run || working) return;
    working = true; error();
    try { render(await api(`/api/agent/runs/${run.id}/control`, {command})); }
    catch (e) { error(e.message); }
    finally { working = false; $('send').disabled = false; }
  });
}
$('screen').addEventListener('error', () => emptyBrowser(['handoff', 'paused'].includes(run?.status)));
function reportBounds() {
  if (!desktop) return;
  const box = $('browser-slot').getBoundingClientRect();
  desktop.setBounds({x:box.x,y:box.y,width:box.width,height:box.height,visible:!$('settings').open && /^https?:/.test(desktopState.url)});
}
function updateBrowser(state) {
  desktopState = state;
  if (document.activeElement !== $('browser-address')) $('browser-address').value = /^https?:/.test(state.url) ? state.url : '';
  if (state.error) error(state.error);
  reportBounds();
}
async function beforeManualNavigation() {
  if (isActive() && !run.pending) {
    render(await api(`/api/agent/runs/${run.id}/control`, {command:'pause'}));
    for (let i=0; i<120 && isActive() && !run.pending; i++) {
      await new Promise(resolve=>setTimeout(resolve,500));
      render(await api(`/api/agent/runs/${run.id}`));
    }
    if (isActive() && !run.pending) throw Error('The agent is still pausing. Use Stop before navigating.');
  }
}
if (desktop) {
  document.body.classList.add('desktop');
  $('address-form').hidden = false; $('url').hidden = true; $('focus').hidden = true;
  $('browser-caption').textContent = 'Live browser · click, scroll, and type here';
  $('empty-text').textContent = 'Enter a website address above, or send a task in chat. This pane is a real browser.';
  new ResizeObserver(reportBounds).observe($('browser-slot'));
  window.addEventListener('resize', reportBounds);
  desktop.onState(updateBrowser);
  updateBrowser(await desktop.state());
  $('address-form').addEventListener('submit', async event => {
    event.preventDefault(); error();
    try {await beforeManualNavigation(); updateBrowser(await desktop.navigate($('browser-address').value.trim()));}
    catch (e) {error(e.message);}
  });
  for (const action of ['back','forward','reload']) $('browser-'+action).addEventListener('click',async()=>{
    error();
    try {await beforeManualNavigation(); updateBrowser(await desktop.control(action));}
    catch(e){error(e.message);}
  });
}
try {
  config = await api('/api/agent/config');
  $('connection').textContent = config.liveAvailable ? 'Both model modes ready' : config.jevOnlyAvailable ? 'Jev ready · Gemini optional' : 'Add a Jev key to run browser tasks';
  setMode('jev'); await poll();
} catch (e) { error(e.message); }
