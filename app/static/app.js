'use strict';
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const DAYS = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница'];
const EVENT_LABELS = {
  lesson_start: 'Начало урока',
  lesson_end: 'Конец урока',
  break_start: 'Перемена · 5 минут',
  long_break_start: 'Большая перемена · 15 минут',
  end_of_day: 'Конец учебного дня'
};
const PAGE_LABELS = {
  overview: 'Обзор',
  school: 'Данные школы',
  timetable: 'Расписание',
  music: 'Музыка',
  bells: 'Звонки и настройки'
};
let catalog = null;
let timetable = {
  lessons: [],
  periods: []
};
let music = {
  tracks: [],
  playlists: {},
  event_types: []
};
let bells = {
  events: [],
  periods: [],
  priority: []
};
let playlistDraft = [];
let editingTeacher = null;
let editingClass = null;
let editingLesson = null;
let generating = false;
let playerBusy = false;
let playerPollPending = false;
let lastPlayerError = null;
let currentUser = null;
let csrfToken = '';
let activeJob = null;
let jobPollTimer = null;
let sessionEpoch = 0;
let confirmationPending = false;

class StaleSessionError extends Error {
  constructor() {
    super('Ответ относится к завершённому сеансу.');
    this.name = 'StaleSessionError';
  }
}



function requireCurrentSession(epoch) {
  if (epoch !== sessionEpoch) throw new StaleSessionError();
}

function isStaleSession(error) {
  return error instanceof StaleSessionError;
}

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}

function notify(message) {
  $('#error').hidden = true;
  const box = $('#notice');
  box.textContent = message;
  box.hidden = false;
}



function errorMessage(detail) {
  if (Array.isArray(detail)) {
    return detail.map(item =>
      `${(item.loc || []).slice(1).join('.')}: ${item.msg || 'Некорректное значение'}`).join('\n');
  }
  if (detail && typeof detail === 'object') {
    return [detail.message, ...(detail.details || [])].filter(Boolean).join('\n');
  }
  return String(detail || 'Не удалось выполнить действие.');
}

function showError(error) {
  if (isStaleSession(error)) return;
  const box = currentUser ? $('#error') : $('#login-error');
  $('#notice').hidden = true;
  box.textContent = error instanceof Error ? error.message : errorMessage(error);
  box.hidden = false;
  box.scrollIntoView({
    behavior: 'smooth',
    block: 'nearest'
  });
}

function showLogin(message = '') {
  sessionEpoch += 1;
  currentUser = null;
  csrfToken = '';
  activeJob = null;
  generating = false;
  playerBusy = false;
  clearTimeout(jobPollTimer);
  if ($('#confirmation-dialog').open) $('#confirmation-dialog').close('cancel');
  $('#workspace').hidden = true;
  $('#login-screen').hidden = false;
  $('#login-loading').hidden = true;
  $('#login-error').hidden = !message;
  $('#login-error').textContent = message;
  $('#login-form [name=password]').value = '';
}



async function api(path, options = {}) {
  const requestEpoch = sessionEpoch;
  const init = {
    ...options,
    credentials: 'same-origin'
  };
  const method = (init.method || 'GET').toUpperCase();
  init.headers = {
    ...init.headers
  };
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && csrfToken) init.headers['X-CSRF-Token'] = csrfToken;
  if (init.body && !(init.body instanceof FormData)) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(init.body);
  }
  let response;
  try {
    response = await fetch(path, init);
  } catch {
    requireCurrentSession(requestEpoch);
    throw new Error('Нет связи с сервером. Проверьте, запущено ли приложение, и повторите действие.');
  }
  let data;
  try {
    data = await response.json();
  } catch {
    data = {};
  }
  requireCurrentSession(requestEpoch);
  if (!response.ok) {
    if (response.status === 401 && !['/api/auth/login', '/api/auth/me'].includes(path)) showLogin(
      'Сеанс завершён. Войдите снова.');
    const error = new Error(errorMessage(data.detail || data.message ||
      `Ошибка запроса (${response.status}).`));
    error.status = response.status;
    throw error;
  }
  return data;
}

function guard(handler) {
  return async event => {
    try {
      await handler(event);
    } catch (error) {
      showError(error);
    }
  };
}

async function pending(button, action, pendingText = 'Сохраняем…') {
  if (!button || button.disabled) return;
  const original = button.textContent;
  button.disabled = true;
  button.textContent = pendingText;
  try {
    return await action();
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

function showPage(name) {
  if (!PAGE_LABELS[name]) name = 'overview';
  $$('.page').forEach(page => {
    page.hidden = page.id !== `page-${name}`;
  });
  $$('.nav-item').forEach(button => {
    const active = button.dataset.page === name;
    button.classList.toggle('active', active);
    if (active) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  });
  $('#page-name').textContent = PAGE_LABELS[name];
  history.replaceState(null, '', `#${name}`);
}

function table(container, headers, rows, empty = 'Пока нет записей.') {
  const root = typeof container === 'string' ? $(container) : container;
  root.replaceChildren();
  if (!rows.length) {
    root.append(el('div', empty, 'empty-state'));
    return;
  }
  const node = el('table');
  const head = el('thead');
  const headRow = el('tr');
  headers.forEach(title => headRow.append(el('th', title)));
  head.append(headRow);
  const body = el('tbody');
  rows.forEach(values => {
    const row = el('tr');
    values.forEach(value => {
      const cell = el('td');
      if (value instanceof Node) cell.append(value);
      else cell.textContent = String(value ?? '—');
      row.append(cell);
    });
    body.append(row);
  });
  node.append(head, body);
  root.append(node);
}

function options(select, items, label, placeholder = 'Выберите…') {
  const previous = select.value;
  const selected = select.multiple ? [...select.selectedOptions].map(x => x.value) : [];
  select.replaceChildren();
  if (!select.multiple && placeholder !== null) {
    const opt = el('option', placeholder);
    opt.value = '';
    select.append(opt);
  }
  items.forEach(item => {
    const opt = el('option', typeof label === 'function' ? label(item) : item[label]);
    opt.value = String(item.id);
    if (select.multiple) opt.selected = selected.includes(opt.value);
    select.append(opt);
  });
  if (!select.multiple && [...select.options].some(x => x.value === previous)) select.value = previous;
}

function lookup(items, id, fallback = '—') {
  return items.find(item => item.id === id)?.name || fallback;
}

function gradeName(id) {
  const grade = catalog.grades.find(item => item.id === id);
  return grade ? `${grade.number}-я параллель` : '—';
}

function classLabel(item) {
  return `${item.name} · смена ${item.shift || 1}`;
}

function idValue(form, name) {
  return Number(form.elements[name].value);
}




function confirmAction({
  title,
  message,
  confirmLabel = 'Продолжить'
}) {
  if (confirmationPending) return Promise.resolve(false);
  const dialog = $('#confirmation-dialog');
  const previousFocus = document.activeElement;
  $('#confirmation-title').textContent = title;
  $('#confirmation-message').textContent = message;
  $('#confirmation-accept').textContent = confirmLabel;
  dialog.returnValue = 'cancel';
  confirmationPending = true;
  return new Promise(resolve => {
    dialog.addEventListener('close', () => {
      confirmationPending = false;
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus();
      resolve(dialog.returnValue === 'confirm');
    }, {
      once: true
    });
    dialog.showModal();
    $('#confirmation-cancel').focus();
  });
}



async function canInvalidate() {
  if (!timetable.lessons.length) return true;
  const epoch = sessionEpoch;
  const confirmed = await confirmAction({
    title: 'Обновить данные школы?',
    message: 'После сохранения расписание и план звонков будут очищены. Затем нужно создать расписание заново.',
    confirmLabel: 'Сохранить и очистить'
  });
  requireCurrentSession(epoch);
  return confirmed;
}

function showSchoolSection(name) {
  const names = ['people', 'classes', 'plan'];
  if (!names.includes(name)) name = 'people';
  $$('.school-step').forEach(button => {
    const active = button.dataset.schoolSection === name;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', String(active));
  });
  $$('.school-section').forEach(section => {
    section.hidden = section.id !== `school-section-${name}`;
  });
}



async function refresh() {
  const epoch = sessionEpoch;
  const results = await Promise.all([api('/api/catalog'), api('/api/timetable'), api('/api/music'), api(
    '/api/bells')]);
  requireCurrentSession(epoch);
  [catalog, timetable, music, bells] = results;
  renderCatalog();
  renderOverview();
  renderMusic();
  renderBells();
  renderTimetable();
}



function renderOverview() {
  const items = [
    [catalog.classes.length, 'Классов в школе', '▦'],
    [catalog.teachers.length, 'Учителей', '◉'],
    [timetable.lessons.length, 'Уроков в неделю', '▤'],
    [music.tracks.length, 'Музыкальных треков', '♫']
  ];
  $('#stats').replaceChildren(...items.map(([count, label, symbol]) => {
    const node = el('div', null, 'stat');
    node.append(el('small', symbol), el('strong', count), el('span', label));
    return node;
  }));
  $('#hero-start').textContent = catalog.settings.start_time;
  $('#overview-summary').textContent = timetable.lessons.length ?
    `Уроков на неделю: ${timetable.lessons.length}. Классов: ${catalog.classes.length}. Откройте расписание, чтобы посмотреть результат.` :
    'Расписание ещё не создано. Заполните данные школы и создайте первую учебную неделю.';
  $('#seed-button').disabled = catalog.teachers.length > 0 || catalog.grades.length > 0 || catalog.subjects
    .length > 0;
  const scheduler = $('#scheduler-chip');
  scheduler.textContent = catalog.settings.scheduler_enabled ? 'Звонки включены' : 'Звонки выключены';
  scheduler.classList.toggle('on', catalog.settings.scheduler_enabled);
  const audio = $('#audio-chip');
  audio.textContent = catalog.settings.audio_enabled ? 'Звук включён' : 'Звук выключен';
  audio.classList.toggle('on', catalog.settings.audio_enabled);
  renderReadiness();
}

function renderReadiness() {
  const missing = [];
  for (const schoolClass of catalog.classes) {
    const requirements = catalog.grade_subjects.filter(item => item.grade_id === schoolClass.grade_id);
    const assigned = catalog.assignments.filter(item => item.class_id === schoolClass.id);
    if (!requirements.length && !assigned.some(item => item.lessons_per_week)) missing.push(
      `${schoolClass.name}: не задана недельная нагрузка.`);
    for (const requirement of requirements) {
      if (!catalog.assignments.some(item => item.class_id === schoolClass.id && item.subject_id ===
          requirement.subject_id)) {
        missing.push(
          `${schoolClass.name} · ${lookup(catalog.subjects, requirement.subject_id)}: не назначен учитель.`);
      }
    }
  }
  const container = $('#setup-check');
  container.replaceChildren();
  if (!catalog.classes.length) {
    container.append(el('p', 'Добавьте классы и предметы или загрузите пример школы.', 'hint'));
  } else if (missing.length) {
    container.append(el('strong', `Осталось заполнить: ${missing.length}`));
    const list = el('ul');
    missing.slice(0, 12).forEach(message => list.append(el('li', message)));
    container.append(list);
    if (missing.length > 12) container.append(el('p',
      `Ещё ${missing.length - 12} незаполненных назначений или учебных планов.`, 'hint'));
  } else {
    container.append(el('strong', 'Учебный план и назначения заполнены.'));
    container.append(el('p',
      'При генерации программа дополнительно проверит пересечения учителей, классов и кабинетов.', 'hint'
    ));
  }
}

function selectedLessons() {
  const isTeacher = $('#view-type').value === 'teacher';
  const selectedId = Number($('#view-id').value);
  return timetable.lessons.filter(lesson => (isTeacher ? lesson.teacher_id : lesson.class_id) === selectedId);
}

function timetableTitle() {
  const select = $('#view-id');
  return `Расписание · ${select.selectedOptions[0]?.textContent || ''}`;
}

function exportTimetable() {
  const lessons = selectedLessons();
  if (!lessons.length) return;
  const rows = [
    ['День', 'Смена', 'Урок', 'Начало', 'Конец', 'Класс', 'Предмет', 'Учитель', 'Кабинет']
  ];
  lessons.sort((a, b) => a.weekday - b.weekday || (a.shift || 1) - (b.shift || 1) || a.period - b.period);
  lessons.forEach(lesson => {
    const period = lessonPeriods(lesson.shift || 1).find(item => item.period === lesson.period);
    rows.push([DAYS[lesson.weekday], lesson.shift || 1, lesson.period, period?.start || '', period?.end ||
      '', lesson.class_name, lesson.subject_name, lesson.teacher_name, lesson.room_name || ''
    ]);
  });
  const quote = value => {
    let text = String(value ?? '');
    if (/^[\s]*[=+@-]/.test(text)) text = `'${text}`;
    return `"${text.replaceAll('"', '""')}"`;
  };
  const csv = '\uFEFF' + rows.map(row => row.map(quote).join(',')).join('\r\n');
  const url = URL.createObjectURL(new Blob([csv], {
    type: 'text/csv;charset=utf-8;'
  }));
  const link = el('a');
  link.href = url;
  link.download = `timetable-${$('#view-type').value}-${$('#view-id').value}.csv`;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function lessonPeriods(shift = 1) {
  return timetable.shift_periods?.[String(shift)] || (shift === 1 ? timetable.periods : []);
}

function renderCatalog() {
  const c = catalog;
  options($('#teacher-form [name=subject_ids]'), c.subjects, 'name', null);
  for (const selector of ['#class-form [name=grade_id]', '#grade-limit-form [name=grade_id]',
      '#curriculum-form [name=grade_id]'
    ]) {
    options($(selector), c.grades, item => `${item.number}-я параллель`);
  }
  options($('#curriculum-form [name=subject_id]'), c.subjects, 'name');
  options($('#assignment-form [name=class_id]'), c.classes, classLabel);
  options($('#assignment-form [name=room_id]'), c.rooms, 'name', 'Без кабинета');
  updateAssignmentChoices();
  table('#subject-list', ['Предмет', 'По возможности раньше'], c.subjects.map(s => [s.name, s.is_hard ? 'Да' :
    '—'
  ]), 'Добавьте первый предмет.');
  table('#teacher-list', ['Учитель', 'Предметы', ''], c.teachers.map(teacher => {
    const edit = el('button', 'Изменить', 'text-button');
    edit.type = 'button';
    edit.addEventListener('click', () => editTeacher(teacher));
    return [teacher.name, teacher.subject_ids.map(id => lookup(c.subjects, id)).join(', '), edit];
  }), 'Добавьте учителей и укажите их предметы.');
  table('#grade-list', ['Параллель', 'Классы', 'Уроков в день'], c.grades.map(g => [`${g.number}-я параллель`,
    c.classes.filter(x => x.grade_id === g.id).map(x => x.name).join(', '), g.max_lessons_per_day
  ]), 'Добавьте параллель обучения.');
  table('#class-list', ['Класс', ''], c.classes.map(schoolClass => {
    const edit = el('button', 'Изменить', 'text-button');
    edit.type = 'button';
    edit.addEventListener('click', () => editClass(schoolClass));
    return [classLabel(schoolClass), edit];
  }), 'Добавьте существующие классы: укажите название и смену.');
  $('#room-list').replaceChildren(...c.rooms.map(x => el('span', x.name, 'tag')));
  table('#curriculum-list', ['Параллель', 'Предмет', 'В неделю'], c.grade_subjects.map(g => [gradeName(g
      .grade_id), lookup(c.subjects, g.subject_id), g.lessons_per_week]),
    'Задайте недельную нагрузку по предметам.');
  table('#assignment-list', ['Класс / предмет', 'Учитель', 'Кабинет', 'В неделю'], c.assignments.map(a => {
    const label = el('div');
    label.append(el('strong', lookup(c.classes, a.class_id)), el('small', lookup(c.subjects, a
      .subject_id)));
    const schoolClass = c.classes.find(item => item.id === a.class_id);
    const inherited = c.grade_subjects.find(item => item.grade_id === schoolClass?.grade_id && item
      .subject_id === a.subject_id)?.lessons_per_week;
    return [label, lookup(c.teachers, a.teacher_id), lookup(c.rooms, a.room_id), a.lessons_per_week ??
      inherited ?? '—'
    ];
  }), 'Назначьте учителя для каждого предмета в классе.');
  const settingsForm = $('#settings-form');
  Object.entries(c.settings).forEach(([key, value]) => {
    const input = settingsForm.elements[key];
    if (!input) return;
    if (input.type === 'checkbox') input.checked = Boolean(value);
    else input.value = value;
  });
  updateViewChoices();
  for (const form of ['#grade-form', '#class-form']) {
    const secondShift = $(`${form} [name=shift] option[value="2"]`);
    secondShift.disabled = !c.settings.shifts_enabled;
    if (!c.settings.shifts_enabled) $(`${form} [name=shift]`).value = '1';
  }
}

function updateAssignmentChoices() {
  if (!catalog) return;
  const form = $('#assignment-form');
  const schoolClass = catalog.classes.find(c => c.id === idValue(form, 'class_id'));
  const allowed = schoolClass ? catalog.grade_subjects.filter(g => g.grade_id === schoolClass.grade_id).map(
    g => g.subject_id) : [];
  options(form.elements.subject_id, schoolClass ? catalog.subjects : [], subject =>
    `${subject.name}${allowed.includes(subject.id) ? ' · учебный план' : ''}`, schoolClass ?
    'Выберите предмет…' : 'Сначала выберите класс…');
  updateTeacherChoices();
}

function updateTeacherChoices() {
  const form = $('#assignment-form');
  const subjectId = idValue(form, 'subject_id');
  options(form.elements.teacher_id, catalog.teachers.filter(t => t.subject_ids.includes(subjectId)), 'name',
    subjectId ? 'Выберите учителя…' : 'Сначала выберите предмет…');
  const schoolClass = catalog.classes.find(item => item.id === idValue(form, 'class_id'));
  const assigned = catalog.assignments.find(item => item.class_id === schoolClass?.id && item.subject_id ===
    subjectId);
  form.elements.teacher_id.value = assigned ? String(assigned.teacher_id) : '';
  form.elements.room_id.value = assigned?.room_id ? String(assigned.room_id) : '';
  form.elements.lessons_per_week.value = assigned?.lessons_per_week ?? '';
  form.elements.lessons_per_week.required = Boolean(subjectId && !catalog.grade_subjects.some(item => item
    .grade_id === schoolClass?.grade_id && item.subject_id === subjectId));
}

function editTeacher(teacher) {
  editingTeacher = teacher.id;
  const form = $('#teacher-form');



  form.elements.name.value = teacher.name;
  [...form.elements.subject_ids.options].forEach(opt => {
    opt.selected = teacher.subject_ids.includes(Number(opt.value));
  });
  $('#teacher-save').textContent = 'Сохранить учителя';
  $('#teacher-cancel').hidden = false;
  form.scrollIntoView({
    behavior: 'smooth',
    block: 'center'
  });
}

function cancelTeacherEdit() {
  editingTeacher = null;
  $('#teacher-form').reset();
  $('#teacher-save').textContent = 'Добавить учителя';
  $('#teacher-cancel').hidden = true;
}

function editClass(schoolClass) {
  editingClass = schoolClass.id;
  const form = $('#class-form');
  for (const name of ['name', 'grade_id', 'shift']) form.elements[name].value = schoolClass[name];
  $('#class-save').textContent = 'Сохранить класс';
  $('#class-cancel').hidden = false;
  form.scrollIntoView({
    behavior: 'smooth',
    block: 'center'
  });
}

function cancelClassEdit() {
  editingClass = null;
  $('#class-form').reset();
  $('#class-save').textContent = 'Добавить класс';
  $('#class-cancel').hidden = true;
}

function updateViewChoices() {
  const isTeacher = $('#view-type').value === 'teacher';
  $('#view-label').textContent = isTeacher ? 'Учитель' : 'Класс';
  options($('#view-id'), isTeacher ? catalog.teachers : catalog.classes, isTeacher ? 'name' : classLabel,
    null);
}

function renderTimetable() {
  const quality = timetable.quality;
  const qualitySummary = $('#timetable-quality');
  qualitySummary.hidden = !quality || !timetable.lessons.length;
  qualitySummary.textContent = quality ?
    `Вся школа: окон между уроками — ${quality.class_windows}; максимум уроков у класса за день — ${quality.max_daily_load}.` :
    '';
  qualitySummary.title = 'Окно — свободный урок между первым и последним уроком класса в течение дня.';
  const isTeacher = $('#view-type').value === 'teacher';
  const selectedId = Number($('#view-id').value);
  const selected = selectedLessons();
  const schoolClass = catalog.classes.find(item => item.id === selectedId);
  const shifts = isTeacher ? [...new Set(selected.map(item => item.shift || 1))].sort() : [schoolClass
    ?.shift || 1
  ];
  $('#timetable-title').textContent = timetableTitle();
  $('#timetable-export').disabled = !selected.length;
  $('#timetable-print').disabled = !selected.length;
  const container = $('#timetable-grid');
  container.replaceChildren();
  $('#timetable-count').textContent = selected.length ?
    `Уроков на неделю: ${selected.length}. При переносе урока время звонков пересчитывается.` : '';
  if (!timetable.lessons.length) {
    container.append(el('div', 'Добавьте данные школы и нажмите «Создать расписание».', 'empty-state'));
    return;
  }
  if (!selectedId) {
    container.append(el('div', 'Выберите класс или учителя.', 'empty-state'));
    return;
  }
  if (!selected.length) {
    container.append(el('div', 'Для этого учителя или класса пока нет уроков.', 'empty-state'));
    return;
  }
  const node = el('table', null, 'timetable');
  const head = el('thead');
  const headRow = el('tr');
  ['Урок', ...DAYS].forEach(day => headRow.append(el('th', day)));
  head.append(headRow);


  const body = el('tbody');
  shifts.forEach(shift => {
    const shiftRow = el('tr', null, 'shift-heading');
    const title = el('th', `Смена ${shift} · ${shift === 1 ? 'первая' : 'вторая'}`);
    title.colSpan = DAYS.length + 1;
    shiftRow.append(title);


    body.append(shiftRow);
    lessonPeriods(shift).forEach(period => {
      const row = el('tr');


      const time = el('td', null, 'period-cell');
      time.append(el('strong', `Урок ${period.period}`), el('span', `${period.start}–${period.end}`));
      row.append(time);
      DAYS.forEach((_, weekday) => {
        const cell = el('td');
        const lesson = selected.find(item => item.weekday === weekday && item.period === period
          .period && (item.shift || 1) === shift);
        if (lesson) {
          const button = el('button', null, 'lesson-cell');
          button.type = 'button';
          button.setAttribute('aria-label',
            `Перенести: ${lesson.subject_name}, ${DAYS[weekday]}, смена ${shift}, урок ${period.period}`
          );
          button.append(el('strong', lesson.subject_name), el('small', isTeacher ? lesson
            .class_name : lesson.teacher_name));
          if (lesson.room_name) button.append(el('span', lesson.room_name, 'lesson-room'));
          button.addEventListener('click', () => editLesson(lesson));
          cell.append(button);
        } else {
          cell.className = 'free-cell';
          cell.textContent = '·';
        }
        row.append(cell);
      });
      body.append(row);
    });
  });
  node.append(head, body);
  container.append(node);
}

function editLesson(lesson) {
  editingLesson = lesson.id;
  $('#edit-lesson-title').textContent =
    `${lesson.class_name} · ${lesson.subject_name} · ${lesson.teacher_name}`;
  const form = $('#lesson-form');
  form.elements.weekday.value = lesson.weekday;
  options(form.elements.period, lessonPeriods(lesson.shift || 1).map(p => ({
    id: p.period,
    label: `${p.period} · ${p.start}–${p.end}`
  })), 'label', null);
  form.elements.period.value = lesson.period;
  $('#lesson-editor').hidden = false;
  $('#lesson-editor').scrollIntoView({
    behavior: 'smooth',
    block: 'nearest'
  });
}

function setGenerating(value) {
  generating = value;
  $$('[data-generate]').forEach(button => {
    button.disabled = value;
    button.textContent = value ? 'Расписание создаётся…' : 'Создать расписание';
  });
  $('#generation-seed').disabled = value;
  $('#generation-optimize').disabled = value;
}
function renderJob(job) {
  activeJob = job;
  const isActive = ['queued', 'running'].includes(job.status);
  setGenerating(isActive);
  $('#generation-panel').hidden = false;
  $('#generation-panel').classList.toggle('complete', job.status === 'succeeded');
  $('#generation-panel').classList.toggle('failed', job.status === 'failed');
  const titles = {
    queued: 'Задача в очереди',
    running: 'Ищем подходящий вариант…',
    succeeded: 'Расписание готово',
    failed: 'Расписание не создано',
    cancelled: 'Генерация отменена'
  };
  $('#generation-title').textContent = titles[job.status] || 'Проверяем состояние…';
  $('#generation-cancel').hidden = !isActive;
  const cancelling = job.progress?.phase === 'cancelling';
  $('#generation-cancel').disabled = cancelling;
  $('#generation-cancel').textContent = cancelling ? 'Отменяем…' : 'Отменить';
  $('#generation-meter').hidden = !isActive;
  const progress = job.progress || {};
  const started = job.started_at || job.created_at;
  const elapsed = progress.elapsed_seconds ?? (started ? Math.max(0, Date.now() / 1000 - started) : 0);
  const phases = {
    queued: 'Ожидание запуска',
    modeling: 'Подготовка требований',
    solving: 'Проверка вариантов',
    cancelling: 'Останавливаем генерацию…'
  };
  const parts = [phases[progress.phase] || (isActive ? 'Обработка задачи' : '')];
  if (isActive) parts.push(`Прошло ${Math.floor(elapsed)} сек.`);
  if (progress.solutions) parts.push(`Найдено вариантов: ${progress.solutions}`);
  if (job.status === 'succeeded') {
    const result = job.result || {};
    parts.splice(0, parts.length, `Сохранено уроков: ${result.lesson_count ?? 0}`,
      `Время: ${Number(result.elapsed_seconds || 0).toFixed(1)} сек.`);
    $('#generation-info').textContent =
      `Начальное число: ${result.seed ?? '—'}. ${result.status === 'optimal' ? 'Найден наилучший вариант по выбранным критериям.' : 'Найден корректный вариант, все обязательные условия выполнены.'}`;
  }
  if (job.status === 'failed') parts.splice(0, parts.length, errorMessage(job.error));
  if (job.status === 'cancelled') parts.splice(0, parts.length,
    'Предыдущее расписание сохранено. Можно запустить новую генерацию.');
  $('#generation-progress').textContent = parts.filter(Boolean).join(' · ');
  $('#generation-hint').hidden = !isActive;
}
async function pollJob(jobId, epoch = sessionEpoch) {
  clearTimeout(jobPollTimer);
  if (!currentUser || epoch !== sessionEpoch) return;
  try {
    const job = await api(`/api/timetable/jobs/${encodeURIComponent(jobId)}`);
    if (!currentUser || epoch !== sessionEpoch) return;
    renderJob(job);
    if (['queued', 'running'].includes(job.status)) {
      jobPollTimer = setTimeout(() => pollJob(jobId, epoch), 900);
      return;
    }
    if (job.status === 'succeeded') {
      $('#lesson-editor').hidden = true;
      await refresh();
      notify('Новое расписание проверено и сохранено.');
    }
  } catch (error) {
    if (!currentUser || epoch !== sessionEpoch) return;
    if (error.status === 404) {
      activeJob = null;
      setGenerating(false);
      showError(error);
      return;
    }
    $('#generation-progress').textContent = 'Не удалось обновить состояние. Повторим автоматически…';
    jobPollTimer = setTimeout(() => pollJob(jobId, epoch), 2500);
  }
}

async function generate() {
  if (generating) return;
  const seedInput = $('#generation-seed');
  if (!seedInput.reportValidity()) return;
  const epoch = sessionEpoch;
  if (timetable.lessons.length) {
    const confirmed = await confirmAction({
      title: 'Создать новое расписание?',
      message: 'После успешной генерации новый вариант заменит текущее расписание и ручные переносы. Если подходящего варианта не найдётся, прежнее расписание останется.',
      confirmLabel: 'Создать новый вариант'
    });
    requireCurrentSession(epoch);
    if (!confirmed) return;
  }
  setGenerating(true);
  try {
    const body = {
      optimize: $('#generation-optimize').checked
    };
    if (seedInput.value !== '') body.seed = Number(seedInput.value);
    const job = await api('/api/timetable/generate', {
      method: 'POST',
      body
    });
    renderJob(job);
    showPage('timetable');
    jobPollTimer = setTimeout(() => pollJob(job.id), 250);
  } catch (error) {
    if (isStaleSession(error)) return;
    requireCurrentSession(epoch);
    if (error.status === 409) {
      const runningJob = await api('/api/timetable/jobs/current');
      if (runningJob) {
        renderJob(runningJob);
        showPage('timetable');
        jobPollTimer = setTimeout(() => pollJob(runningJob.id), 250);
        notify('Генерация уже запущена. Показываем её состояние.');
        return;
      }
    }
    setGenerating(false);
    throw error;
  }
}

async function cancelGeneration() {
  if (!activeJob || !generating || activeJob.progress?.phase === 'cancelling') return;
  const id = activeJob.id;
  const button = $('#generation-cancel');
  button.disabled = true;
  button.textContent = 'Отменяем…';
  try {
    const job = await api(`/api/timetable/jobs/${encodeURIComponent(id)}/cancel`, {
      method: 'POST'
    });
    renderJob(job);
    clearTimeout(jobPollTimer);
    if (['queued', 'running'].includes(job.status)) jobPollTimer = setTimeout(() => pollJob(id), 300);
  } catch (error) {
    if (!isStaleSession(error) && currentUser) {
      button.disabled = false;
      button.textContent = 'Отменить';
    }
    throw error;
  }
}
function renderMusic() {
  const tracks = music.tracks;
  $('#track-list').replaceChildren();
  if (!tracks.length) $('#track-list').append(el('div', 'Загрузите первый музыкальный файл.', 'empty-state'));
  tracks.forEach(track => {
    const row = el('div', null, 'track-row');
    const name = el('div', null, 'track-name');
    name.append(el('span', track.original_name), el('small', `Трек ${track.id}`));
    row.append(el('span', '♫', 'track-icon'), name);
    $('#track-list').append(row);
  });
  options($('#test-form [name=track_id]'), tracks, 'original_name');
  options($('#playlist-track'), tracks, 'original_name');
  const events = (music.event_types || Object.keys(EVENT_LABELS)).map(type => ({
    id: type,
    name: EVENT_LABELS[type] || type
  }));
  const eventSelect = $('#playlist-event');
  const previousEvent = eventSelect.value;
  options(eventSelect, events, 'name', null);
  if (!previousEvent && events.some(event => event.id === 'break_start')) eventSelect.value = 'break_start';
  loadPlaylistDraft();
}

function loadPlaylistDraft() {
  playlistDraft = [...(music.playlists[$('#playlist-event').value] || [])];
  $('#playlist-saved-note').textContent = '';
  renderPlaylist();
}
function renderPlaylist() {
  const container = $('#playlist-items');
  container.replaceChildren();
  if (!playlistDraft.length) container.append(el('div',
    'Плейлист пуст. Добавьте трек или оставьте это событие без музыки.', 'empty-state'));
  playlistDraft.forEach((id, index) => {
    const track = music.tracks.find(item => item.id === id);
    const row = el('div', null, 'playlist-row');
    row.append(el('span', String(index + 1).padStart(2, '0'), 'playlist-index'), el('span', track
      ?.original_name || `Трек ${id}`, 'playlist-name'));
    const actions = [
      ['↑', 'Поднять трек выше', index === 0, () => {
        [playlistDraft[index - 1], playlistDraft[index]] = [playlistDraft[index], playlistDraft[
          index - 1]];
      }],
      ['↓', 'Опустить трек ниже', index === playlistDraft.length - 1, () => {
        [playlistDraft[index + 1], playlistDraft[index]] = [playlistDraft[index], playlistDraft[
          index + 1]];
      }],
      ['×', 'Убрать из плейлиста', false, () => {
        playlistDraft.splice(index, 1);
      }]
    ];
    actions.forEach(([text, label, disabled, action]) => {
      const button = el('button', text, `small-button${text === '×' ? ' remove' : ''}`);
      button.type = 'button';
      button.setAttribute('aria-label', label);
      button.disabled = disabled;
      button.addEventListener('click', () => {
        action();
        renderPlaylist();
        $('#playlist-saved-note').textContent = 'Есть несохранённые изменения.';
      });
      row.append(button);
    });
    container.append(row);
  });
}
async function refreshPlayer() {
  if (playerPollPending) return;
  const epoch = sessionEpoch;
  playerPollPending = true;
  try {
    const status = await api('/api/music/status');
    requireCurrentSession(epoch);
    playerBusy = Boolean(status.busy);
    const heading = playerBusy ? (status.mode === 'dry-run' ? 'Проверка без звучания' :
      'Музыка играет на колонках сервера') : (status.mode === 'idle' ? 'Готово к воспроизведению' :
      'Воспроизведение остановлено');
    const lines = [heading];
    const trackName = status.original_name || status.track_name;
    if (trackName && playerBusy) lines.push(trackName);
    if (status.duration && playerBusy) lines.push(
      `${status.duration} сек., включая затухание ${status.fade_out_seconds || 0} сек.`);
    lines.push(catalog?.settings.scheduler_enabled ? 'Автоматические звонки включены.' :
      'Автоматические звонки выключены.');
    if (status.error) lines.push(`Ошибка звука: ${status.error}`);
    if (status.scheduler?.last_result?.status === 'error') lines.push(
      `Ошибка звонков: ${status.scheduler.last_result.message}`);
    $('#player-status').textContent = lines.join('\n');
    $('#player-status').classList.toggle('player-error', Boolean(status.error));
    if (status.error && status.error !== lastPlayerError) showError(new Error(
      `Не удалось воспроизвести музыку: ${status.error}`));
    lastPlayerError = status.error || null;
  } finally {
    playerPollPending = false;
  }
}

function renderBells() {
  const grids = bells.shift_periods || {
    '1': bells.periods
  };
  const rows = Object.entries(grids).flatMap(([shift, periods]) => periods.map(p => [
    `Смена ${shift} · ${p.period}`, p.start, p.end,
    p.period === periods.length ? '—' : (p.period === catalog.settings.long_break_after ? '15 минут' :
      '5 минут')
  ]));
  table('#period-list', ['Урок', 'Начало', 'Конец', 'Перемена'], rows);
  $('#bell-priority').textContent = (bells.priority || []).map(type => EVENT_LABELS[type] || type).join(
    ' → ');
  const day = Number($('#bell-day').value);
  table('#bell-list', ['Время', 'Событие', 'Урок'], bells.events.filter(event => event.weekday === day).map(
    event => [el('span', event.time, 'time-badge'), EVENT_LABELS[event.event_type] || event.event_type,
      `${event.period}`
    ]), 'Звонков пока нет. Сначала создайте расписание.');
}

function bindDataForm(selector, endpoint, payload, success, method = 'POST') {
  $(selector).addEventListener('submit', guard(async event => {
    event.preventDefault();
    const form = event.currentTarget;
    if (!await canInvalidate()) return;
    const body = payload(form);
    await pending(form.querySelector('[type=submit]'), async () => {
      await api(typeof endpoint === 'function' ? endpoint(form) : endpoint, {
        method,
        body
      });
      form.reset();
      $('#lesson-editor').hidden = true;
      await refresh();
      notify(success);
    });
  }));
}

function bind() {
  $$('[data-school-section]').forEach(button => button.addEventListener('click', () => showSchoolSection(
    button.dataset.schoolSection)));
  showSchoolSection('people');
  $$('[data-page]').forEach(button => button.addEventListener('click', event => {
    event.preventDefault();
    showPage(button.dataset.page);
  }));
  $$('[data-generate]').forEach(button => button.addEventListener('click', guard(generate)));
  $$('[data-stop]').forEach(button => button.addEventListener('click', guard(async () => {
    await api('/api/music/stop', {
      method: 'POST'
    });
    notify('Музыка остановлена. Настройка автоматических звонков не изменилась.');
    await refreshPlayer();
  })));
  $('#seed-button').addEventListener('click', guard(async event => {
    await pending(event.currentTarget, async () => {
      await api('/api/seed', {
        method: 'POST'
      });
      await refresh();
      notify('Пример школы загружен. Создайте расписание для шести классов.');
    }, 'Загружаем пример…');
    $('#seed-button').disabled = catalog.grades.length > 0;
  }));
  bindDataForm('#subject-form', '/api/subjects', f => ({
    name: f.elements.name.value.trim(),
    is_hard: f.elements.is_hard.checked
  }), 'Предмет добавлен.');
  bindDataForm('#grade-form', '/api/grades', f => ({
    number: idValue(f, 'number'),
    parallel_count: idValue(f, 'parallel_count'),
    max_lessons_per_day: idValue(f, 'max_lessons_per_day'),
    shift: idValue(f, 'shift')
  }), 'Параллель и классы добавлены.');
  $('#class-form').addEventListener('submit', guard(async event => {
    event.preventDefault();
    const form = event.currentTarget;
    if (!await canInvalidate()) return;
    const body = {
      name: form.elements.name.value.trim(),
      grade_id: idValue(form, 'grade_id'),
      shift: idValue(form, 'shift')
    };
    await pending($('#class-save'), async () => {
      await api(editingClass ? `/api/classes/${editingClass}` : '/api/classes', {
        method: editingClass ? 'PUT' : 'POST',
        body
      });
      await refresh();
      notify('Класс сохранён. Создайте расписание заново.');
      $('#lesson-editor').hidden = true;
    });
    cancelClassEdit();
  }));
  $('#class-cancel').addEventListener('click', cancelClassEdit);
  bindDataForm('#room-form', '/api/rooms', f => ({
    name: f.elements.name.value.trim()
  }), 'Кабинет добавлен.');
  bindDataForm('#curriculum-form', '/api/curriculum', f => ({
    grade_id: idValue(f, 'grade_id'),
    subject_id: idValue(f, 'subject_id'),
    lessons_per_week: idValue(f, 'lessons_per_week')
  }), 'Недельная нагрузка сохранена.');
  bindDataForm('#assignment-form', '/api/assignments', f => ({
    class_id: idValue(f, 'class_id'),
    subject_id: idValue(f, 'subject_id'),
    teacher_id: idValue(f, 'teacher_id'),
    room_id: f.elements.room_id.value ? idValue(f, 'room_id') : null,
    lessons_per_week: f.elements.lessons_per_week.value ? idValue(f, 'lessons_per_week') : null
  }), 'Назначение сохранено.');
  bindDataForm('#grade-limit-form', f => `/api/grades/${idValue(f, 'grade_id')}`, f => ({
    max_lessons_per_day: idValue(f, 'max_lessons_per_day')
  }), 'Лимит уроков обновлён.', 'PUT');
  $('#teacher-form').addEventListener('submit', guard(async event => {
    event.preventDefault();
    const form = event.currentTarget;
    if (!await canInvalidate()) return;
    const body = {
      name: form.elements.name.value.trim(),
      subject_ids: [...form.elements.subject_ids.selectedOptions].map(option => Number(option
        .value))
    };
    await pending($('#teacher-save'), async () => {
      await api(editingTeacher ? `/api/teachers/${editingTeacher}` : '/api/teachers', {
        method: editingTeacher ? 'PUT' : 'POST',
        body
      });
      await refresh();
      notify(editingTeacher ? 'Учитель обновлён.' : 'Учитель добавлен.');
    });
    cancelTeacherEdit();
  }));
  $('#teacher-cancel').addEventListener('click', cancelTeacherEdit);
  $('#assignment-form [name=class_id]').addEventListener('change', updateAssignmentChoices);
  $('#assignment-form [name=subject_id]').addEventListener('change', updateTeacherChoices);
  $('#grade-limit-form [name=grade_id]').addEventListener('change', () => {
    const form = $('#grade-limit-form');
    const grade = catalog.grades.find(g => g.id === idValue(form, 'grade_id'));
    if (grade) form.elements.max_lessons_per_day.value = grade.max_lessons_per_day;
  });
  $('#view-type').addEventListener('change', () => {
    updateViewChoices();
    renderTimetable();
    $('#lesson-editor').hidden = true;
  });
  $('#view-id').addEventListener('change', () => {
    renderTimetable();
    $('#lesson-editor').hidden = true;
  });
  $('#timetable-export').addEventListener('click', exportTimetable);
  $('#timetable-print').addEventListener('click', () => {
    if (selectedLessons().length) window.print();
  });
  $('#cancel-lesson-edit').addEventListener('click', () => {
    $('#lesson-editor').hidden = true;
    editingLesson = null;
  });
  $('#lesson-form').addEventListener('submit', guard(async event => {
    event.preventDefault();
    if (!editingLesson) return;
    const form = event.currentTarget;
    await pending(form.querySelector('[type=submit]'), async () => {
      await api(`/api/timetable/${editingLesson}`, {
        method: 'PATCH',
        body: {
          weekday: idValue(form, 'weekday'),
          period: idValue(form, 'period')
        }
      });
      $('#lesson-editor').hidden = true;
      editingLesson = null;
      await refresh();
      notify('Урок перенесён. Пересечения и недельная нагрузка проверены.');
    });
  }));
  $('#upload-form').addEventListener('submit', guard(async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const file = form.elements.file.files[0];
    if (file && file.size > 25 * 1024 * 1024) throw new Error('Размер файла превышает 25 МиБ.');
    await pending(form.querySelector('[type=submit]'), async () => {
      await api('/api/music/upload', {
        method: 'POST',
        body: new FormData(form)
      });
      form.reset();
      music = await api('/api/music');
      renderMusic();
      renderOverview();
      notify('Трек загружен. Добавьте его в плейлист или проверьте звучание.');
    }, 'Загружаем…');
  }));
  $('#test-form').addEventListener('submit', guard(async event => {
    event.preventDefault();
    const form = event.currentTarget;
    await pending(form.querySelector('[type=submit]'), async () => {
      await api('/api/music/test', {
        method: 'POST',
        body: {
          track_id: idValue(form, 'track_id')
        }
      });
      notify(catalog.settings.audio_enabled ? 'Музыка запускается на колонках сервера.' :
        'Проверка запущена без звучания. Чтобы услышать музыку, включите звук в настройках.');
      await refreshPlayer();
    }, 'Запускаем…');
  }));
  $('#refresh-player').addEventListener('click', guard(refreshPlayer));
  $('#playlist-event').addEventListener('change', loadPlaylistDraft);
  $('#playlist-add').addEventListener('click', () => {
    const id = Number($('#playlist-track').value);
    if (!id) {
      showError(new Error('Выберите трек.'));
      return;
    }
    playlistDraft.push(id);
    renderPlaylist();
    $('#playlist-saved-note').textContent = 'Есть несохранённые изменения.';
  });
  $('#playlist-save').addEventListener('click', guard(async event => {
    const eventType = $('#playlist-event').value;
    if (!eventType) throw new Error('Сначала выберите событие звонка.');
    await pending(event.currentTarget, async () => {
      await api(`/api/music/playlists/${encodeURIComponent(eventType)}`, {
        method: 'PUT',
        body: {
          track_ids: playlistDraft
        }
      });
      music = await api('/api/music');
      $('#playlist-saved-note').textContent =
        'Плейлист сохранён. Очередь начнётся с первого трека.';
      notify(`Плейлист «${EVENT_LABELS[eventType] || eventType}» сохранён.`);
    });
  }));
  $('#bell-day').addEventListener('change', renderBells);
  $('#settings-form').addEventListener('submit', guard(async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const body = {};
    for (const name of ['start_time', 'second_shift_start_time', 'timezone']) body[name] = form
      .elements[name].value;
    for (const name of ['max_lessons_per_day', 'playback_duration', 'fade_out_seconds',
        'solver_time_limit', 'long_break_after'
      ]) body[name] = idValue(form, name);
    for (const name of ['use_rooms', 'scheduler_enabled', 'audio_enabled', 'shifts_enabled']) body[
      name] = form.elements[name].checked;
    const structural = ['max_lessons_per_day', 'use_rooms'].some(key => body[key] !== catalog
      .settings[key]);
    if (structural && !await canInvalidate()) return;
    await pending(form.querySelector('[type=submit]'), async () => {
      await api('/api/settings', {
        method: 'PUT',
        body
      });
      await refresh();
      notify('Настройки сохранены. Звонки работают по часовому поясу школы.');
    });
  }));
}

async function openWorkspace(user, epoch = sessionEpoch) {
  requireCurrentSession(epoch);
  currentUser = user.username;
  csrfToken = user.csrf_token;
  $('#account-name').textContent = user.username;
  $('#login-screen').hidden = true;
  $('#workspace').hidden = false;
  $('#login-error').hidden = true;
  $('#login-form [name=password]').value = '';
  $('#error').hidden = true;
  $('#notice').hidden = true;
  $('#generation-panel').hidden = true;
  setGenerating(false);
  await refresh();
  requireCurrentSession(epoch);
  await refreshPlayer();
  requireCurrentSession(epoch);
  const job = await api('/api/timetable/jobs/current');
  requireCurrentSession(epoch);
  if (job && ['queued', 'running'].includes(job.status)) {
    renderJob(job);
    jobPollTimer = setTimeout(() => pollJob(job.id), 250);
  }
}

async function start() {
  bind();
  showPage(location.hash.slice(1) || 'overview');
  $('#generation-cancel').addEventListener('click', guard(cancelGeneration));
  $('#login-form').addEventListener('submit', guard(async event => {
    event.preventDefault();
    const form = event.currentTarget;
    await pending(form.querySelector('[type=submit]'), async () => {
      $('#login-error').hidden = true;
      sessionEpoch += 1;
      const user = await api('/api/auth/login', {
        method: 'POST',
        body: {
          username: form.elements.username.value.trim(),
          password: form.elements.password.value
        }
      });
      await openWorkspace(user);
    }, 'Входим…');
  }));
  $('#logout-button').addEventListener('click', guard(async () => {
    await api('/api/auth/logout', {
      method: 'POST'
    });
    showLogin();
  }));
  try {
    const user = await api('/api/auth/me');
    await openWorkspace(user);
  } catch (error) {
    if (isStaleSession(error)) {
    } else if (error.status === 401) showLogin();
    else {
      showLogin();
      showError(error);
    }
  }
  $('#login-loading').hidden = true;
  window.setInterval(() => {
    if (!currentUser || document.hidden || (!playerBusy && $('#page-music').hidden)) return;
    refreshPlayer().catch(error => {
      if (currentUser && !isStaleSession(error)) $('#player-status').textContent =
        `Не удалось обновить состояние: ${error.message}`;
    });
  }, 1500);
}
start().catch(showError);
