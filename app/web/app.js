'use strict';
const $ = id => document.getElementById(id);
const el = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
let catalog = [], userType = '', selected = null, matter = null;
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {cache: 'no-store'} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  let data; try { data = await response.json(); } catch { throw new Error('The service is temporarily unavailable. Please try again.'); }
  if (!response.ok) throw new Error(data.detail?.message || (response.status === 413 ? 'Please shorten your question and omit sensitive details.' : 'We could not process this request. Check the information and try again.'));
  return data;
}
function options(select, entries, includeUnknown = true) {
  select.replaceChildren();
  for (const [value, label] of entries) { const o = el('option', label); o.value = value; select.append(o); }
  if (includeUnknown) { const o = el('option', 'Not sure / other'); o.value = 'Other'; select.append(o); }
}
function showError(target, text) { target.hidden = false; target.replaceChildren(el('p', text)); target.classList.add('error'); }
function relevant() { return catalog.filter(w => w.user_types.includes(userType) && w.jurisdiction.state === $('state').value); }
function updateMatters() {
  $('assistant').hidden = true; $('route-result').hidden = true;
  options($('matter-type'), [['', 'Choose a matter'], ...relevant().map(w => [w.routing.selectors.matter_type[0], w.title])]);
  $('details').hidden = true;
}
function updateDetails() {
  const w = relevant().find(w => w.routing.selectors.matter_type.includes($('matter-type').value));
  $('details').hidden = !$('matter-type').value;
  options($('court'), (w?.routing.selectors.court || []).map(v => [v, v]));
  options($('role'), (w?.routing.selectors.role || []).map(v => [v, v === 'business_operator' ? 'Business owner / operator' : 'Defendant (person being sued)']));
  options($('document'), (w ? (w.routing.selectors.document_title || ['Warrant in Debt — Small Claims Division']) : []).map(v => [v, v]));
  $('form-label').hidden = !w?.routing.required_fields.includes('form_number');
  $('form-number').required = !!w?.routing.required_fields.includes('form_number');
  $('form-number').value = w?.routing.selectors.form_number?.[0] || '';
}
function displayCoverage() {
  const container = $('coverage-list'); container.replaceChildren();
  for (const w of catalog) {
    const card = el('article', undefined, 'card');
    card.append(el('small', w.user_types.includes('small_business_owner') ? 'Small businesses' : 'Individuals'), el('h3', w.title), el('p', w.purpose), el('p', w.jurisdiction.state + ' · ' + (w.jurisdiction.court || w.jurisdiction.agency)), el('div', 'Proposed · Development only · Public approval pending', 'state'));
    container.append(card);
  }
}
function beginWorkflow(w) {
  selected = w; $('assistant').hidden = false;
  $('workflow-title').textContent = w.title; $('workflow-purpose').textContent = w.purpose;
  $('scope-limits').replaceChildren(...w.scope_limits.map(x => el('li', x)));
  $('intake-fields').replaceChildren(); $('conversation').replaceChildren();
  const labels = {court_name_or_locality: 'Court or agency shown', document_title_or_form_number: 'Document title or form number', return_date_and_time_if_shown: 'Printed date and time (or “Not shown”)'};
  for (const field of w.intake_fields.filter(f => !['state', 'user_goal'].includes(f))) {
    const label = el('label', labels[field] || field.replaceAll('_', ' ')); const input = el('input'); input.name = field; input.required = true; input.maxLength = 250;
    if (field === 'court_name_or_locality') input.value = matter.court;
    if (field === 'document_title_or_form_number') input.value = matter.form_number || matter.document_title;
    label.append(input); $('intake-fields').append(label);
  }
  $('assistant').scrollIntoView({behavior: 'smooth'});
}
async function route(event) {
  event.preventDefault(); $('route-result').classList.remove('error'); $('assistant').hidden = true;
  matter = {country: 'US', state: $('state').value, user_type: userType, matter_type: $('matter-type').value, court: $('court').value, document_title: $('document').value, form_number: $('form-number').value, role: $('role').value};
  try {
    const result = await api('/routing/evaluate', matter); const target = $('route-result'); target.hidden = false; target.replaceChildren();
    if (result.state === 'exact_match') {
      const w = catalog.find(w => w.workflow_id === result.workflow_ids[0]);
      target.append(el('h3', w.title), el('p', 'These details fit this development workflow. This does not determine legal jurisdiction, venue, service validity, or representation requirements.'));
      const button = el('button', 'Continue with this workflow →', 'button'); button.type = 'button'; button.addEventListener('click', () => beginWorkflow(w)); target.append(button);
    } else if (['candidate_match', 'insufficient_information', 'ambiguous'].includes(result.state)) {
      target.append(el('h3', 'A little more information is needed'), el('p', result.state === 'ambiguous' ? 'More than one workflow fits. Please check the distinguishing court and document details; no workflow has been selected.' : 'Please confirm: ' + result.missing_fields.map(x => x.replaceAll('_', ' ')).join(', ') + '.'));
    } else {
      target.append(el('h3', 'This matter is not yet covered'), el('p', 'Pro-One does not yet have a reviewed workflow for this matter. No question has been sent to a model.'));
      for (const url of result.official_resources || []) { const a = el('a', 'Open official resource'); a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer'; target.append(a, el('br')); }
    }
  } catch (error) { showError($('route-result'), error.message); }
}
function renderAnswer(data) {
  const out = $('conversation');
  out.replaceChildren(el('div', $('question').value, 'question-bubble'));
  if (!data.response) { out.append(el('div', data.message + (data.missing_information.length ? ' Missing: ' + data.missing_information.map(x => x.replaceAll('_', ' ')).join(', ') : ''), 'notice error')); return; }
  out.append(el('p', data.message + (data.model.testing ? ' Offline test provider: source excerpts, not a live AI answer.' : ''), 'hint'));
  const answer = el('article', undefined, 'answer');
  for (const section of data.response.sections) {
    answer.append(el('h3', section.user_provided ? 'You provided (unverified)' : section.heading));
    const p = el('p', section.text);
    for (const number of section.citation_numbers) { const a = el('a', '[' + number + ']'); a.href = '#source-' + number; const sup = el('sup'); sup.append(a); p.append(' ', sup); }
    answer.append(p);
  }
  const sources = el('section', undefined, 'sources'); sources.append(el('h3', 'Sources you can inspect'));
  for (const source of data.response.sources) {
    const row = el('div', undefined, 'source'); row.id = 'source-' + source.number;
    const a = el('a', '[' + source.number + '] ' + source.title); if (source.url) { a.href = source.url; a.target = '_blank'; a.rel = 'noopener noreferrer'; }
    row.append(a, el('small', source.issuing_authority + ' · ' + source.locator), el('small', source.citation), el('small', source.maturity + ' source · ' + (source.currentness === 'certified' ? 'Declared currentness certification available' : 'Currentness has not been certified')));
    for (const limit of source.limitations) row.append(el('small', limit)); sources.append(row);
  }
  answer.append(sources);
  const warnings = el('details'); warnings.append(el('summary', 'Important limits, privacy, and date notices')); const list = el('ul'); for (const warning of data.response.warnings) list.append(el('li', warning)); warnings.append(list); answer.append(warnings);
  out.append(answer); out.scrollIntoView({behavior: 'smooth', block: 'start'});
}
async function ask(event) {
  event.preventDefault(); $('ask-button').disabled = true; $('ask-button').textContent = 'Checking sources and preparing response…';
  const answers = {state: matter.state, user_goal: $('question').value};
  for (const input of $('intake-fields').querySelectorAll('input')) answers[input.name] = input.value;
  const [provider, model] = $('provider').value.split('|');
  const risks = $('urgent').checked ? selected.risk_options.filter(r => r.type === 'deadline_risk').map(r => r.id) : [];
  try { renderAnswer(await api('/workflows/' + encodeURIComponent(selected.workflow_id) + '/response', {answers, matter, risk_ids: risks, retrieval: {query: $('question').value, limit: 5}, ...(provider ? {generation: {provider, model}} : {})})); }
  catch (error) { showError($('conversation'), error.message); }
  finally { $('ask-button').disabled = false; $('ask-button').textContent = 'Ask Pro-One ↗'; }
}
document.querySelectorAll('[data-user]').forEach(button => button.addEventListener('click', () => {
  userType = button.dataset.user; document.querySelectorAll('[data-user]').forEach(b => b.setAttribute('aria-pressed', String(b === button))); $('route-form').hidden = false; updateMatters();
}));
$('state').addEventListener('change', updateMatters); $('matter-type').addEventListener('change', updateDetails); $('route-form').addEventListener('submit', route); $('question-form').addEventListener('submit', ask);
Promise.all([api('/workflows'), api('/model/status')]).then(([coverage, status]) => {
  catalog = coverage.workflows; displayCoverage();
  const choices = Object.entries(status.available).flatMap(([p, models]) => models.map(m => [p + '|' + m, p === 'testing' ? 'Offline test provider (no live AI)' : p + ' · ' + m]));
  options($('provider'), status.configured ? choices : [['', 'Default provider unavailable — select an available option explicitly'], ...choices], false);
  if (status.configured) $('provider').value = status.provider + '|' + status.model;
  $('model-note').textContent = status.configured ? (status.testing_provider ? 'Offline testing is active. Set server credentials to use a real provider.' : 'The selected real provider will receive the minimum facts and selected source evidence.') : 'A server administrator must configure a provider before generation is available.';
  if (location.pathname === '/coverage') $('coverage').scrollIntoView();
}).catch(error => showError($('route-result'), error.message));
