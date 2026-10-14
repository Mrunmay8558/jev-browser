const $ = id => document.getElementById(id);
const terminal = new Set(['completed', 'failed', 'stopped', 'limit_reached']);
const modeNames = {demo: 'Local demo', jev: 'Jev only', live: 'Gemini + Jev'};
let config, run = null, mode = 'jev', working = false, detached = false;
const desktop = window.jevDesktop;
let desktopState = {url: ''};
let lastImage = -1, lastEvents = -1, displayedRun = '', pollTimer, viewEpoch = 0, tripDraftKey = '';
function busy(value) {
  working = value;
  $('new-chat').disabled = value;
  $('send').disabled = value || !config;
  $('save-details').disabled = value;
}
function notice(message = '') { $('notice').textContent = message; $('notice').hidden = !message; }

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
function appendTrainResults(node, result) {
  const heading = document.createElement('p');
  heading.className = 'train-search-heading';
  heading.textContent = result.sourceHeading;
  node.append(heading);
  const list = document.createElement('ol');
  list.className = 'train-results';
  list.setAttribute('aria-label', 'Train schedules from IRCTC');
  for (const train of result.trains) {
    const card = document.createElement('li');
    card.className = 'train-card';
    const name = document.createElement('strong');
    name.className = 'train-name';
    name.textContent = `${train.name} · ${train.number}`;
    card.append(name);
    const schedule = document.createElement('div');
    schedule.className = 'train-schedule';
    for (const [label, stop] of [['Departs', train.departure], ['Arrives', train.arrival]]) {
      const column = document.createElement('div');
      for (const [className, value] of [['train-stop-label', label], ['train-time', stop.time], ['train-date', stop.date], ['train-station', stop.station]]) {
        const line = document.createElement('span');
        line.className = className;
        line.textContent = value;
        column.append(line);
      }
      schedule.append(column);
    }
    card.append(schedule);
    list.append(card);
  }
  node.append(list);
  const note = document.createElement('p');
  note.className = 'train-result-note';
  note.textContent = result.note;
  node.append(note);
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
      node.textContent = run.result.summary;
      const hasTrains = Array.isArray(run.result.trains);
      if (hasTrains) appendTrainResults(node, run.result);
      for (const quote of hasTrains ? [] : run.result.evidence) {
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
  if (nearBottom || wasEmpty) {
    const result = nodes.findLast(node => node.classList.contains('result'));
    if (result && run.result?.trains?.length) {
      // Start at the answer's heading, not at the last of many train cards.
      thread.scrollTop += result.getBoundingClientRect().top - thread.getBoundingClientRect().top - 12;
    } else thread.scrollTop = thread.scrollHeight;
  }
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
  for (const id of ['max-steps', 'threshold', 'add-value']) $(id).disabled = active;
  $('known-values').querySelectorAll('input,button').forEach(element => { element.disabled = active; });
  $('new-chat').disabled = working;
  $('start-url').disabled = active || mode === 'demo';
  $('send').disabled = working || !config;
  $('task').maxLength = active ? 2000 : 4000;
  $('task').placeholder = active ? 'Add details or change the next steps…' : 'Ask the browser to do something…';
  $('composer-hint').textContent = active ? 'Updates this task · Enter to send' : 'Enter to send';
  $('pause').disabled = !active || !!run.pending;
  $('stop').disabled = !active;
  $('focus').disabled = !run.page;
  $('status').textContent = ({handoff:'Needs your details',review:'Needs guidance',approval:'Needs approval',paused:'Paused'})[run.status] || run.status.replaceAll('_', ' ');
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
    const trip = run.pending.flightDetails;
    $('handoff-title').textContent = trip ? 'Your flight details' : run.status === 'approval' ? 'Review this action' : run.status === 'paused' ? 'You have control' : 'Agent paused';
    $('handoff-message').textContent = run.pending.message;
    $('trip-form').hidden = !trip;
    $('approve').hidden = run.status !== 'approval';
    $('resume').hidden = !!trip;
    $('resume').textContent = run.status === 'approval' ? 'Skip & replan' : 'Resume agent';
    $('handoff-help').textContent = trip ? 'No special format needed. Save these details to continue, or choose New task to start over.' : run.status === 'approval' ? 'Only Approve authorizes this action. New task stops this run.' : 'After changing the page yourself, choose Resume agent to read it again and continue. Sending guidance in chat also resumes the agent. New task starts over.';
    const draftKey = trip ? run.id + ':' + JSON.stringify(trip) : '';
    if (trip && tripDraftKey !== draftKey) {
      tripDraftKey = draftKey;
      for (const [id, key] of Object.entries({'trip-from':'from_city','trip-to':'to_city','trip-departure':'departure_date','trip-type':'trip_type','trip-return':'return_date'})) $(id).value = trip[key] || '';
      $('trip-error').hidden = true;
      updateReturnField();
    }
  } else { tripDraftKey = ''; $('trip-form').hidden = true; }
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
    const epoch = viewEpoch;
    try {
      const data = await api(run ? `/api/agent/runs/${run.id}` : '/api/agent/current');
      if (data && epoch === viewEpoch) render(data);
    } catch (e) { if (epoch === viewEpoch) error(e.message); }
  }
  pollTimer = setTimeout(poll, isActive() && !run.pending ? 250 : 1500);
}
function addValueRow(name = '', value = '') {
  const row = $('value-row-template').content.firstElementChild.cloneNode(true);
  const index = $('known-values').children.length + 1;
  row.querySelector('[data-name]').value = name;
  row.querySelector('[data-name]').setAttribute('aria-label', `Field on website ${index}`);
  row.querySelector('[data-value]').value = value;
  row.querySelector('[data-value]').setAttribute('aria-label', `Text to enter ${index}`);
  row.querySelector('button').addEventListener('click', () => row.remove());
  $('known-values').append(row);
}
$('add-value').addEventListener('click', () => { if ($('known-values').children.length < 16) addValueRow(); });
addValueRow();
function clearValues() { $('known-values').replaceChildren(); addValueRow(); }
function formValues() {
  const values = {};
  for (const row of $('known-values').children) {
    const name = row.querySelector('[data-name]').value.trim();
    const value = row.querySelector('[data-value]').value.trim();
    if (!name && !value) continue;
    if (!name || !value) throw Error('In Task settings, give each extra field both a name and the text to enter, or remove the empty row.');
    values[name] = value;
  }
  return values;
}
function updateReturnField() {
  const returning = $('trip-type').value === 'Return';
  $('return-field').hidden = !returning;
  $('trip-return').required = returning;
  $('trip-return').min = $('trip-departure').value;
}
$('trip-type').addEventListener('change', updateReturnField);
$('trip-departure').addEventListener('change', updateReturnField);
$('trip-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (working || !run?.pending?.flightDetails || !$('trip-form').reportValidity()) return;
  busy(true); error(); $('trip-error').hidden = true;
  try {
    render(await api(`/api/agent/runs/${run.id}/control`, {command:'details', details:{
      from_city:$('trip-from').value.trim(), to_city:$('trip-to').value.trim(),
      departure_date:$('trip-departure').value, trip_type:$('trip-type').value,
      return_date:$('trip-type').value === 'Return' ? $('trip-return').value : null
    }}));
    notice('Trip details saved. Continuing this task…');
    void poll();
  } catch (e) { $('trip-error').textContent = e.message; $('trip-error').hidden = false; }
  finally { busy(false); }
});
async function sendMessage(event) {
  event?.preventDefault();
  const task = $('task').value.trim();
  if (!task || working || !config) return;
  busy(true); error(); notice();
  try {
    if (isActive()) {
      render(await api(`/api/agent/runs/${run.id}/control`, {command: 'message', message: task}));
    } else {
      if (mode === 'jev' && !config.jevOnlyAvailable) throw Error('Jev-only needs TYPESAFE_API_KEY in .env. Gemini is optional. Add the key and restart.');
      if (mode === 'live' && !config.liveAvailable) throw Error('Gemini + Jev needs GEMINI_API_KEY and TYPESAFE_API_KEY in .env. Add them and restart.');
      let startUrl = $('start-url').value.trim();
      if (!startUrl && mode !== 'demo') startUrl = task.match(/https?:\/\/[^\s<>]+/)?.[0] || '';
      // The server resolves explicit website names and task URLs before opening a browser.
      if (startUrl.includes('/demo/')) {startUrl = ''; clearValues();} 
      const data = await api('/api/agent/runs', {
        task, start_url: mode === 'demo' ? '' : startUrl, mode,
        inputs: mode === 'demo' ? {} : formValues(),
        max_steps: Number($('max-steps').value), threshold: Number($('threshold').value)
      });
      detached = false; lastEvents = -1; lastImage = -1; render(data);
    }
    $('task').value = '';
  } catch (e) { error(e.message); }
  finally { busy(false); }
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
  clearValues();
  $('task').focus();
});
$('new-chat').addEventListener('click', async () => {
  if (working) return;
  const wasActive = isActive();
  busy(true); error(); notice();
  detached = true; viewEpoch++; clearTimeout(pollTimer);
  try {
    await api('/api/agent/reset', {});
    run = null; displayedRun = ''; lastEvents = lastImage = -1; tripDraftKey = '';
    $('messages').replaceChildren(); $('welcome').hidden = false; $('handoff').hidden = true;
    $('trip-form').reset(); $('trip-form').hidden = true;
    $('start-url').value = ''; clearValues();
    $('task').value = ''; $('task').maxLength = 4000; $('task').placeholder = 'Ask the browser to do something…';
    $('status').textContent = 'Ready'; $('status').className = 'status'; $('step').textContent = 'Ready when you are';
    $('message').textContent = 'Choose a mode and send a task in the chat.';
    $('metrics').textContent = 'No model calls yet'; $('inspector').textContent = 'No decision yet.';
    for (const id of ['pause','stop','focus']) $(id).disabled = true;
    for (const id of ['max-steps','threshold','add-value']) $(id).disabled = false;
    document.querySelectorAll('[data-mode]').forEach(button => { button.disabled = false; });
    $('composer-hint').textContent = 'Enter to send';
    if (mode === 'demo') mode = 'jev';
    emptyBrowser(); setMode(mode); updateReturnField();
    notice(wasActive ? 'Previous task stopped. What would you like to do next?' : 'Ready for a new task.');
    $('thread').scrollTop = 0; $('task').focus();
  } catch (e) { error('Could not stop the current task. ' + e.message); }
  finally { detached = false; busy(false); void poll(); }
});
$('settings-toggle').addEventListener('click', () => showSettings(true));
$('close-settings').addEventListener('click', () => showSettings(false));
$('save-settings').addEventListener('click', () => showSettings(false));
$('settings').addEventListener('close', () => {$('settings-toggle').setAttribute('aria-expanded', 'false'); reportBounds();});
for (const command of ['pause', 'stop', 'resume', 'approve', 'focus']) {
  $(command).addEventListener('click', async () => {
    if (!run || working) return;
    busy(true); error(); notice();
    try { render(await api(`/api/agent/runs/${run.id}/control`, {command})); }
    catch (e) { error(e.message); }
    finally { busy(false); }
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
