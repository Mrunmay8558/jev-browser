const byId = id => document.getElementById(id);
const frame = byId('browser');
let config = { liveAvailable: false, model: 'jev-1.13.0' };
let current = null, observation = null, generation = 0, busy = false;
let activeTab = 'request';
let policyGeneration = 0;
const history = [];

function announce(message) { byId('announcement').textContent = message; }
function showError(message = '') { byId('error').textContent = message; byId('error').hidden = !message; }
function snapshot() {
  const doc = frame.contentDocument;
  if (!doc?.documentElement.dataset.pageId) throw new Error('The practice browser is still loading.');
  const goal = byId('goal').value.trim();
  if (!goal) throw new Error('Enter a goal first.');
  return {
    goal,
    page: { id: doc.documentElement.dataset.pageId, title: doc.title, text: doc.querySelector('main').innerText.trim() },
    elements: [...doc.querySelectorAll('a[data-action-id]')].filter(el => el.getClientRects().length > 0).map(el => ({ id: el.dataset.actionId, role: 'link', text: el.innerText.trim(), href: el.getAttribute('href') })),
  };
}

async function postJson(path, body) {
  const response = await fetch(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body), signal: AbortSignal.timeout(30000),
  });
  const data = await response.json();
  if (!response.ok) {
    const fields = data.details?.map(item => `${item.field}: ${item.message}`).join(' ');
    throw new Error(fields || data.error || 'The request failed.');
  }
  return data;
}

function clearHighlight() { frame.contentDocument?.querySelectorAll('.agent-selected').forEach(element => element.classList.remove('agent-selected')); }
function invalidate() {
  generation += 1;
  policyGeneration += 1;
  current = null;
  clearHighlight();
  byId('decision-empty').hidden = false;
  byId('decision-result').hidden = true;
  byId('apply').disabled = true;
  byId('response-json').textContent = 'No response for the current page and goal yet.';
  byId('response-caption').textContent = 'Evaluate a step to see its answer.';
  updateButtons();
}

async function observe() {
  invalidate();
  const thisGeneration = generation;
  showError();
  try {
    observation = snapshot();
    byId('address').textContent = `atlas.local / ${observation.page.id}`;
    byId('snapshot-summary').textContent = `${observation.elements.length} visible links observed`;
    byId('request-json').textContent = 'Preparing the request in Python…';
    updateButtons();
    const payload = await postJson('/api/payload', { state: observation });
    if (generation !== thisGeneration) return;
    byId('request-json').textContent = JSON.stringify(payload, null, 2);
  } catch (error) {
    if (generation !== thisGeneration) return;
    observation = null;
    byId('snapshot-summary').textContent = error.message;
    byId('request-json').textContent = 'Enter a valid goal and wait for the practice page to load.';
  }
  updateButtons();
}

function updateButtons() {
  byId('evaluate').disabled = busy || !observation || (byId('mode').value === 'live' && !config.liveAvailable);
  byId('evaluate').textContent = busy ? 'Evaluating the page…' : byId('mode').value === 'live' ? 'Ask Jev for the next step ↗' : 'Evaluate demo step ↗';
  byId('goal').disabled = busy;
  byId('mode').disabled = busy;
  byId('reset').disabled = busy;
  document.querySelectorAll('.preset').forEach(button => { button.disabled = busy; });
}

function addHistory(text) {
  history.push({ step: history.length + 1, text });
  const list = byId('history'); list.replaceChildren();
  for (const entry of history) { const item = document.createElement('li'); item.textContent = entry.text; list.append(item); }
}

async function updatePolicy() {
  const threshold = Number(byId('threshold').value);
  byId('threshold-value').textContent = threshold.toFixed(2);
  const decision = current;
  const revision = ++policyGeneration;
  byId('apply').disabled = true;
  if (!decision) return null;
  try {
    if (decision.threshold !== threshold) {
      byId('policy-title').textContent = 'Checking your rule…';
      const policy = await postJson('/api/policy', {
        state: decision.payload.state, response: decision.response, threshold,
      });
      if (current !== decision || policyGeneration !== revision) return null;
      decision.policy = policy;
      decision.threshold = threshold;
    }
    const policy = decision.policy;
    byId('policy').className = `policy ${policy.status}`;
    byId('policy-title').textContent = policy.label;
    byId('policy-reason').textContent = policy.reason;
    byId('apply').disabled = busy || policy.status !== 'ready';
    return policy;
  } catch (error) {
    if (current === decision && policyGeneration === revision) {
      // A failed policy check must not leave a previous ready decision usable.
      decision.policy = null;
      byId('policy-title').textContent = 'Rule check failed';
      byId('policy-reason').textContent = 'Evaluate a fresh decision before applying a click.';
      showError(error.message);
    }
    return null;
  }
}

async function displayDecision() {
  const answer = current.response.answers;
  const chosen = current.payload.state.elements.find(element => element.id === answer.next_action.choice);
  byId('decision-empty').hidden = true;
  byId('decision-result').hidden = false;
  byId('chosen-label').textContent = chosen ? `Open “${chosen.text.split('\n')[0]}”` : 'Stop on this page';
  byId('confidence').textContent = answer.next_action.confidence.toFixed(2);
  byId('relevance').textContent = `${answer.page_relevance.score.toFixed(2)} / 2`;
  byId('goal-met').textContent = answer.goal_met.noul.toFixed(2);
  const bars = byId('probabilities'); bars.replaceChildren();
  for (const [id, probability] of Object.entries(answer.next_action.probabilities).sort((a, b) => b[1] - a[1])) {
    const label = current.payload.state.elements.find(element => element.id === id)?.text.split('\n')[0] ?? 'Stop';
    const row = document.createElement('div'); row.className = `probability-row ${id === answer.next_action.choice ? 'selected' : ''}`;
    const name = document.createElement('span'); name.className = 'probability-label'; name.textContent = label; name.title = label;
    const track = document.createElement('div'); track.className = 'probability-track';
    const fill = document.createElement('div'); fill.className = 'probability-fill'; fill.style.width = `${probability * 100}%`; track.append(fill);
    const value = document.createElement('span'); value.className = 'probability-value'; value.textContent = `${Math.round(probability * 100)}%`;
    row.append(name, track, value); bars.append(row);
  }
  byId('request-json').textContent = JSON.stringify(current.payload, null, 2);
  byId('response-json').textContent = JSON.stringify(current.response, null, 2);
  byId('response-caption').textContent = current.mode === 'demo' ? 'Scripted teaching response · not a Jev prediction' : 'Live response from TypeSafe';
  byId('decision-meta').textContent = current.mode === 'demo' ? 'Scripted demo · no model call or measured model latency.' : `${current.response.model} · server round trip ${current.elapsedMs} ms`;
  clearHighlight();
  if (chosen) frame.contentDocument.querySelector(`[data-action-id="${chosen.id}"]`)?.classList.add('agent-selected');
  const policy = await updatePolicy();
  if (policy) announce(`${byId('chosen-label').textContent}. ${policy.label}.`);
}

async function evaluateStep() {
  if (busy) return;
  showError();
  let state;
  try { state = snapshot(); } catch (error) { showError(error.message); return; }
  invalidate();
  const thisGeneration = generation;
  busy = true; updateButtons();
  try {
    const data = await postJson('/api/decide', {
      state, mode: byId('mode').value, threshold: Number(byId('threshold').value),
    });
    if (generation !== thisGeneration || JSON.stringify(snapshot()) !== JSON.stringify(state)) throw new Error('The page changed while the decision was being made. Evaluate the current page again.');
    current = data;
    await displayDecision();
    if (generation !== thisGeneration) return;
    const answer = data.response.answers.next_action;
    addHistory(`${data.mode === 'demo' ? 'Demo' : 'Live Jev'} · ${state.page.title}: selected ${state.elements.find(element => element.id === answer.choice)?.text.split('\n')[0] ?? 'stop'} (confidence ${answer.confidence.toFixed(2)}).`);
  } catch (error) {
    current = null;
    byId('decision-result').hidden = true;
    byId('decision-empty').hidden = false;
    showError(error.name === 'TimeoutError' ? 'The decision request timed out. No click was performed.' : error.message);
    announce('The decision failed. No click was performed.');
  } finally { busy = false; updateButtons(); updatePolicy(); }
}

function applyAction() {
  if (!current || busy) return;
  try {
    if (current.threshold !== Number(byId('threshold').value) || current.policy?.status !== 'ready') throw new Error('This decision does not meet your current rule.');
    if (JSON.stringify(snapshot()) !== JSON.stringify(current.payload.state)) throw new Error('The page or goal has changed. Evaluate a fresh snapshot before clicking.');
    const chosen = current.response.answers.next_action.choice;
    const observed = current.payload.state.elements.find(element => element.id === chosen);
    const element = frame.contentDocument.querySelector(`[data-action-id="${chosen}"]`);
    if (!element || !observed || element.getAttribute('href') !== observed.href) throw new Error('The selected element is no longer available.');
    addHistory(`Browser clicked “${observed.text.split('\n')[0]}”. A fresh page snapshot is required for the next decision.`);
    invalidate(); observation = null; updateButtons();
    element.click();
  } catch (error) { invalidate(); showError(error.message); }
}

function renderPresets(scenarios) {
for (const scenario of scenarios) {
  const button = document.createElement('button'); button.className = 'preset'; button.textContent = scenario.label; button.setAttribute('aria-pressed', String(scenario.id === 'install'));
  button.addEventListener('click', () => {
    byId('goal').value = scenario.goal;
    document.querySelectorAll('.preset').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
    invalidate(); observation = null; updateButtons(); frame.src = '/demo/site.html?page=home';
  });
  byId('presets').append(button);
}
}

function selectTab(name) {
  activeTab = name;
  for (const item of ['request', 'response', 'terms', 'trace']) {
    byId(`tab-${item}`).setAttribute('aria-selected', String(item === name));
    byId(`tab-${item}`).tabIndex = item === name ? 0 : -1;
    byId(`pane-${item}`).hidden = item !== name;
  }
  byId('copy').hidden = ['terms', 'trace'].includes(name);
}
const tabNames = ['request', 'response', 'terms', 'trace'];
for (const name of tabNames) {
  byId(`tab-${name}`).addEventListener('click', () => selectTab(name));
  byId(`tab-${name}`).addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const index = event.key === 'Home' ? 0 : event.key === 'End' ? tabNames.length - 1 : (tabNames.indexOf(name) + (event.key === 'ArrowRight' ? 1 : -1) + tabNames.length) % tabNames.length;
    selectTab(tabNames[index]); byId(`tab-${tabNames[index]}`).focus();
  });
}

byId('copy').addEventListener('click', async () => {
  try { await navigator.clipboard.writeText(byId(`${activeTab}-json`).textContent); byId('copy').textContent = 'Copied'; setTimeout(() => { byId('copy').textContent = 'Copy JSON'; }, 1500); }
  catch { showError('Clipboard access is unavailable. Select the JSON below and copy it manually.'); }
});
byId('evaluate').addEventListener('click', evaluateStep);
byId('apply').addEventListener('click', applyAction);
byId('threshold').addEventListener('input', updatePolicy);
byId('goal').addEventListener('input', () => {
  document.querySelectorAll('.preset').forEach(button => button.setAttribute('aria-pressed', 'false'));
  observe();
});
byId('mode').addEventListener('change', () => {
  byId('source-badge').textContent = byId('mode').value.toUpperCase();
  byId('mode-note').textContent = byId('mode').value === 'live' ? 'Each evaluation sends the goal and practice-page snapshot to TypeSafe using your key.' : 'No API calls. Preset goals follow a scripted path.';
  observe();
});
byId('reset').addEventListener('click', () => {
  invalidate(); observation = null; history.length = 0;
  byId('history').replaceChildren(); const item = document.createElement('li'); item.className = 'history-empty'; item.textContent = 'Your decisions and clicks will appear here.'; byId('history').append(item);
  updateButtons(); frame.src = '/demo/site.html?page=home';
});
frame.addEventListener('load', observe);
selectTab('request');
try {
  const response = await fetch('/api/config');
  if (!response.ok) throw new Error('Configuration could not be loaded.');
  config = await response.json();
  renderPresets(config.scenarios);
  const option = byId('mode').querySelector('option[value="live"]');
  option.disabled = !config.liveAvailable;
  option.textContent = config.liveAvailable ? 'Live Jev · key configured' : 'Live Jev · add API key';
  observe();
} catch (error) { showError(error.message); }
