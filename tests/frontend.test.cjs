const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const test = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '../app/static/app.js'), 'utf8')
  .replace(/start\(\)\.catch\(showError\);\s*$/, '');




function fixture() {
  const elements = new Map();
  class Element {
    constructor(selector) {
      this.selector = selector;
      this.listeners = {};
      this.value = '';
      this.hidden = false;
      this.disabled = false;
      this.isConnected = true;
      this.classList = { toggle() {} };
    }


    addEventListener(name, handler, options) {
      (this.listeners[name] ||= []).push({ handler, options });
    }
    focus() { this.focused = true; }
    showModal() { this.open = true; }
    close(value) {
      this.open = false;
      this.returnValue = value;
      const listeners = this.listeners.close || [];
      this.listeners.close = listeners.filter(item => !item.options?.once);
      listeners.forEach(item => item.handler());
    }


    querySelector(selector) { return node(`${this.selector} ${selector}`); }
    reportValidity() { return true; }
    scrollIntoView() {}
    reset() {}
  }


  function node(selector) {
    if (!elements.has(selector)) elements.set(selector, new Element(selector));
    return elements.get(selector);
  }
  const previousFocus = new Element('previous-focus');
  const context = vm.createContext({
    document: { querySelector: node, querySelectorAll: () => [], activeElement: previousFocus },
    HTMLElement: Element,
    FormData: class {},
    Error,
    Promise,
    setTimeout: () => 1,
    clearTimeout: () => {},
    Date,
    fetch: async () => ({ ok: true, json: async () => ({}) }),
  });
  vm.runInContext(source, context);
  const run = code => vm.runInContext(code, context);
  return { node, run, context, previousFocus };
}




test('confirmation restores focus and rejects a second action while open', async () => {
  const { node, run, previousFocus } = fixture();
  const confirmation = run("confirmAction({title:'Confirm',message:'Details'})");
  assert.equal(node('#confirmation-dialog').open, true);
  assert.equal(node('#confirmation-cancel').focused, true);
  assert.equal(await run("confirmAction({title:'Duplicate',message:'Ignored'})"), false);
  node('#confirmation-dialog').close('confirm');
  assert.equal(await confirmation, true);
  assert.equal(previousFocus.focused, true);
});






test('cancelling a destructive change leaves the action unconfirmed', async () => {
  const { node, run } = fixture();
  run('timetable.lessons = [{}]');
  const confirmation = run('canInvalidate()');
  node('#confirmation-dialog').close('cancel');
  assert.equal(await confirmation, false);
});




test('leaving a session dismisses its outstanding confirmation', async () => {
  const { node, run } = fixture();
  const confirmation = run("confirmAction({title:'Confirm',message:'Details'})");
  run('showLogin()');
  assert.equal(await confirmation, false);
  assert.equal(node('#confirmation-dialog').open, false);
});




for (const status of [200, 401]) {
  test(`late HTTP ${status} from an old session cannot change a new session`, async () => {
    const { run, context } = fixture();
    let respond;
    context.fetch = () => new Promise(resolve => { respond = resolve; });
    run("currentUser = 'previous-user'");
    const response = run("api('/api/catalog')");
    run("sessionEpoch += 1; currentUser = 'new-user'");
    respond({ ok: status === 200, status, json: async () => ({ detail: 'Old response' }) });
    await assert.rejects(response, error => error.name === 'StaleSessionError');
    assert.equal(run('currentUser'), 'new-user');
  });
}




test('form submission captures currentTarget before awaiting confirmation', async () => {
  const { run, node, context } = fixture();
  context.sent = [];
  run(`
    timetable.lessons = [{}];
    api = async (url, options) => { sent.push({url, body:options.body}); return {}; };
    refresh = async () => {};
    notify = () => {};
    bindDataForm('#sample-form', '/api/subjects', form => ({name:form.elements.name.value}), 'Saved');
  `);
  const form = node('#sample-form');
  form.elements = { name: { value: 'Математика' } };
  const event = { currentTarget: form, preventDefault() {} };
  const handled = form.listeners.submit[0].handler(event);
  event.currentTarget = null;



  node('#confirmation-dialog').close('confirm');
  await handled;
  assert.equal(context.sent.length, 1);
  assert.equal(context.sent[0].url, '/api/subjects');
  assert.equal(context.sent[0].body.name, 'Математика');
});





test('generation conflict recovers the active job instead of creating another', async () => {
  const { run } = fixture();
  run(`
    timetable.lessons=[];
    showPage=()=>{};
    notify=()=>{};
    renderJob=job=>{activeJob=job;generating=true;};
    api=async url=>{
      if (url.endsWith('/generate')) {const error=new Error('Active');error.status=409;throw error;}
      return {id:'active-job',status:'running'};
    };
  `);


  
  await run('generate()');
  assert.equal(run('activeJob.id'), 'active-job');
  assert.equal(run('generating'), true);
});

test('cancelling remains active and cannot submit another cancel request', async () => {
  const { run, node, context } = fixture();
  context.calls = [];
  run(`
    api=async url=>{calls.push(url);};
    renderJob({id:'active-job',status:'running',created_at:1,progress:{phase:'cancelling'}});
  `);
  assert.equal(run('generating'), true);
  assert.equal(node('#generation-cancel').disabled, true);
  await run('cancelGeneration()');
  assert.equal(context.calls.length, 0);
});
