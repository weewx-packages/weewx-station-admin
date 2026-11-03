// Copyright (c) 2026 Manuel Hilgert <hilman2@gmail.com>
'use strict';

const page = document.getElementById('page');
const tabs = document.getElementById('tabs');
const jobBox = document.getElementById('job');
const logout = document.getElementById('logout');
const languageChoice = document.getElementById('language');
let refreshTimer = null;
// The form the Settings page shows: '' for weewx.conf, otherwise the name of a report.
let settingsForm = '';
// English is the text in this file. Every other language has a file in i18n that
// translates each English text, and the server translates its messages from the same file.
const LANGUAGES = {en: 'English', de: 'Deutsch'};
const language = chooseLanguage();
// Dates and numbers follow the browser's own region where it has the chosen language.
const locale = navigator.language.toLowerCase().startsWith(language) ? navigator.language : language;
let catalog = {};
// Counts the tab changes. A refresh that was under way during a change is dropped,
// or its late answer would replace the page of the new tab.
let tabChanges = 0;

// The choice on the page wins, then the first language of the browser this page knows.
function chooseLanguage() {
  const stored = localStorage.getItem('language');
  if (stored in LANGUAGES) return stored;
  for (const tag of navigator.languages || [navigator.language]) {
    const code = tag.slice(0, 2).toLowerCase();
    if (code in LANGUAGES) return code;
  }
  return 'en';
}

// Translate an English text of this page. Names in braces are filled from values.
function t(text, values = {}) {
  return (catalog[text] || text).replace(/\{(\w+)\}/g, (match, name) => name in values ? values[name] : match);
}

// Build an element. Text always goes through textContent, so nothing from the
// station or an extension can become markup.
function el(tag, attributes = {}, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) {
    if (name.startsWith('on')) node.addEventListener(name.slice(2), value);
    else if (name === 'text') node.textContent = value;
    else if (value === true) node.setAttribute(name, '');
    else if (value !== false && value !== null && value !== undefined) node.setAttribute(name, value);
  }
  for (const child of children.flat()) {
    if (child !== null && child !== undefined) node.append(child);
  }
  return node;
}

async function api(path, body, method) {
  const options = {headers: {'X-Station-Admin': '1', 'X-Language': language}};
  if (body !== undefined) {
    options.method = method || 'POST';
    if (body instanceof File) {
      options.body = body;
    } else {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(body);
    }
  }
  const reply = await fetch('/admin/api/' + path, options);
  const value = await reply.json().catch(() => ({}));
  if (reply.status === 401) { showLogin(); throw new Error(t('Log in first.')); }
  if (!reply.ok) throw new Error(value.error || t('The request failed.'));
  return value;
}

// Replace the page. Parts of a page can be null, which replaceChildren would print.
function show(...children) {
  page.replaceChildren(...children.flat().filter(child => child !== null && child !== undefined));
}

function size(bytes) {
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let index = 0;
  while (bytes >= 1024 && index < units.length - 1) { bytes /= 1024; index++; }
  return bytes.toLocaleString(locale, {maximumFractionDigits: index ? 1 : 0}) + ' ' + units[index];
}

function when(seconds) {
  return seconds ? new Date(seconds * 1000).toLocaleString(locale) : '-';
}

function duration(seconds) {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor(seconds % 86400 / 3600);
  const minutes = Math.floor(seconds % 3600 / 60);
  return days ? t('{days} d {hours} h', {days, hours}) : t('{hours} h {minutes} min', {hours, minutes});
}

function field(label, name, value, attributes = {}) {
  return el('label', {text: label}, el('input', {name, value, ...attributes}));
}

function select(label, name, choices, value, attributes = {}) {
  return el('label', {text: label}, el('select', {name, ...attributes},
    Object.entries(choices).map(([key, text]) => el('option', {value: key, text, selected: key === String(value)}))));
}

// One line of the sensor map: the WeeWX field and what fills it.
function mapRow(key, value) {
  const row = el('tr', {},
    el('td', {}, el('input', {value: key})), el('td', {}, el('input', {value})),
    el('td', {}, el('button', {class: 'quiet', text: t('Remove'), onclick: () => row.remove()})));
  return row;
}

function values(form) {
  return Object.fromEntries(new FormData(form).entries());
}

function failure(error) {
  const box = page.querySelector('.error') || page.insertBefore(el('p', {class: 'error'}), page.firstChild);
  box.textContent = error.message;
}

// Run an action of a page, follow its job, and redraw the page when it is done.
async function act(path, body, after) {
  try {
    const reply = await api(path, body, body instanceof File ? 'PUT' : 'POST');
    if (reply.job) await follow(reply.job, after);
    else if (after) after();
  } catch (error) {
    failure(error);
  }
}

async function follow(number, after) {
  jobBox.hidden = false;
  const title = el('b');
  const output = el('pre');
  const close = el('button', {class: 'quiet', text: t('Close'), onclick: () => { jobBox.hidden = true; }, hidden: true});
  jobBox.replaceChildren(title, output, close);
  for (;;) {
    let job;
    try {
      job = await api('jobs/' + number);
    } catch (error) {
      // An update restarts this server a few seconds after its job has ended.
      title.textContent = t('The administration restarted. Reload the page.');
      close.hidden = false;
      return;
    }
    title.textContent = job.title + ': ' + t(job.state);
    output.textContent = job.log;
    output.scrollTop = output.scrollHeight;
    if (job.state !== 'running') {
      close.hidden = false;
      if (job.state === 'done' && after) after();
      return;
    }
    await new Promise(resolve => setTimeout(resolve, 1500));
  }
}

const views = {
  async Status() {
    const draw = async () => {
      const change = tabChanges;
      const status = await api('status');
      if (change !== tabChanges) return;
      const pi = status.raspberry;
      const station = [
        ['WeeWX', t(status.weewx)],
        [t('Last record'), status.record ? when(status.record.time) : t('none yet')],
        [t('Records'), status.record ? status.record.rows.toLocaleString(locale) : '0'],
      ];
      const power = pi.undervoltage === null ? '-' : pi.undervoltage ? t('Too weak') : t('OK');
      // What can need attention is a tile; what only describes the Pi is a line below.
      const health = [
        [t('Processor temperature'), pi.temperature === null ? '-' : pi.temperature.toLocaleString(locale, {maximumFractionDigits: 1}) + ' °C'],
        [t('Power supply'), power, pi.undervoltage],
        [t('Free disk'), t('{free} of {total}', {free: size(pi.disk.free), total: size(pi.disk.total)})],
        [t('Free memory'), t('{free} of {total}', {free: size(pi.memory.available), total: size(pi.memory.total)})],
        [t('Running for'), duration(pi.uptime)],
      ];
      const details = [
        [t('Model'), pi.model || '-'],
        [t('Address'), pi.address || '-'],
        [t('Host name'), pi.hostname],
        [t('Time'), pi.time_synced ? t('synchronized') : t('waiting')],
        [t('System'), pi.system || '-'],
        [t('Kernel'), pi.kernel],
        [t('Image'), pi.release || '-'],
        [t('Administration'), pi.admin],
      ];
      const tiles = (list, kind = 'tiles') => el('div', {class: kind}, list.map(([name, value, bad, hint]) =>
        el('div', {class: bad ? 'tile bad' : 'tile', title: hint || null}, el('b', {text: String(value)}), el('span', {text: name}))));
      // A reading carries the name the weather pages give it, and its WeeWX name on hover.
      const live = status.live ? Object.entries(status.live).filter(([name]) => !['dateTime', 'usUnits'].includes(name))
        .map(([name, text]) => [status.labels[name] || name, text, false, name]) : [];
      show(
        el('p', {class: 'message ' + (status.weewx === 'active' ? 'good' : 'warn'), text: status.message}),
        tiles(station),
        live.length ? el('h2', {text: t('Current readings')}) : null,
        live.length ? tiles(live, 'tiles readings') : null,
        el('h2', {text: 'Raspberry Pi'}),
        pi.undervoltage ? el('p', {class: 'error', text: t('The power supply is too weak right now. This can corrupt the memory card. Use the official power supply for your model of Raspberry Pi.')}) : null,
        tiles(health),
        el('dl', {class: 'card facts'}, details.map(([name, value]) => el('div', {}, el('dt', {text: name}), el('dd', {text: String(value)})))),
        el('h2', {text: t('Log')}), el('pre', {text: status.log}));
    };
    await draw();
    refreshTimer = setInterval(() => draw().catch(() => {}), 5000);
  },

  async Station() {
    const {values: current, drivers, address, configured, timezone, languages} = await api('station');
    const zone = !configured && Intl.DateTimeFormat().resolvedOptions().timeZone || timezone;
    const browserLanguage = navigator.language.replace('-', '_') + '.UTF-8';
    const pageLanguage = !configured && browserLanguage in languages ? browserLanguage : current.language;
    const driverBox = el('div');
    const driverInput = item => {
      if (item.kind === 'choice') {
        // A US station has the 0.01 inch bucket, the others the 0.2 mm one.
        const linked = item.name === 'band' ? {onchange: event => { driverBox.querySelector('[name=bucket]').value = event.target.value === 'US' ? '0' : '1'; }} : {};
        return select(item.label, item.name, item.choices, item.value, linked);
      }
      if (item.kind === 'secret') {
        return field(item.label, item.name, '', {type: 'password', autocomplete: 'off', placeholder: item.stored ? t('Stored. Leave empty to keep it.') : ''});
      }
      return field(item.label, item.name, item.value, item.kind === 'port' ? {inputmode: 'numeric'} : {});
    };
    const drawDriver = key => {
      const driver = drivers.find(item => item.key === key);
      const inputs = driver.fields.map(item => [item, driverInput(item)]);
      const showFields = () => {
        for (const [item, input] of inputs) {
          const shown = !item.when || driverBox.querySelector(`[name=${item.when[0]}]`).value === item.when[1];
          input.style.display = shown ? '' : 'none';
        }
      };
      const note = driver.note ? [el('p', {class: 'note', text: driver.note.replace('{address}', address || t('this address'))})] : [];
      driverBox.replaceChildren(...inputs.map(([, input]) => input), ...note);
      driverBox.onchange = showFields;
      showFields();
    };
    drawDriver(current.driver);
    const location = field(t('Station name'), 'location', configured ? current.location : '', {required: true, maxlength: 80});
    const title = field(t('Title of the weather pages'), 'title', current.title || (configured ? current.location : ''), {required: true, maxlength: 80});
    // Until somebody types a title of their own, the title follows the station name.
    let titleTyped = Boolean(current.title);
    title.querySelector('input').addEventListener('input', () => { titleTyped = true; });
    location.querySelector('input').addEventListener('input', event => {
      if (!titleTyped) title.querySelector('input').value = event.target.value;
    });
    const form = el('form', {class: 'card', onsubmit: event => {
      event.preventDefault();
      act('station', values(form), () => { select_tab('Status'); });
    }},
      select(t('Kind of station'), 'driver', Object.fromEntries(drivers.map(item => [item.key, item.title])), current.driver, {onchange: event => drawDriver(event.target.value)}),
      driverBox,
      location,
      title,
      field(t('Latitude'), 'latitude', configured ? current.latitude : '', {required: true, inputmode: 'decimal', placeholder: '52.52'}),
      field(t('Longitude'), 'longitude', configured ? current.longitude : '', {required: true, inputmode: 'decimal', placeholder: '13.40'}),
      field(t('Altitude'), 'altitude', configured ? current.altitude : '', {required: true, inputmode: 'decimal'}),
      select(t('Altitude given in'), 'altitude_unit', {meter: t('metres'), foot: t('feet')}, current.altitude_unit),
      field(t('Time zone'), 'timezone', zone, {required: true}),
      select(t('Units on the weather pages'), 'units', {metricwx: t('Metric (°C, m/s, mm)'), metric: t('Metric (°C, km/h, cm)'), us: t('US (°F, mph, in)')}, current.units),
      select(t('Language of the weather pages'), 'language', languages, pageLanguage),
      el('p', {class: 'note', text: t('Dates and numbers follow this language. Belchertown has translated text for German, French, Italian and Catalan, partly; other languages keep English text.')}),
      el('div', {class: 'row'}, el('button', {text: t('Save and start')})));
    show(form);
  },

  async Settings() {
    const data = await api('settings?form=' + encodeURIComponent(settingsForm));
    const skin = settingsForm !== '';
    const changes = new Map();
    const rows = [];
    const choices = Object.fromEntries(data.forms.map(item => [item.key, item.key ? t('Report {name}, skin {skin}', {name: item.key, skin: item.skin}) : 'weewx.conf']));
    const option = (path, item) => {
      const key = JSON.stringify([...path, item.name]);
      const record = change => { changes.set(key, {path, name: item.name, ...change}); };
      const current = item.value !== null ? item.value : (item.default !== null ? item.default : '');
      let input;
      if (item.secret) {
        input = el('input', {type: 'password', autocomplete: 'new-password', placeholder: item.stored ? t('Stored. Leave empty to keep it.') : ''});
      } else if (['true', 'false'].includes(current.toLowerCase())) {
        input = el('select', {}, ['true', 'false'].map(text => el('option', {value: text, text, selected: current.toLowerCase() === text})));
      } else {
        input = el('input', {value: current});
      }
      input.addEventListener('change', () => record({value: input.value}));
      const notes = [];
      if (item.comment) notes.push(el('div', {class: 'note comment', text: item.comment}));
      if (skin && item.default !== null && !item.secret) notes.push(el('div', {class: 'note', text: t('Skin default: {value}', {value: item.default || '""'})}));
      // A value in weewx.conf overrides the skin, and dropping it brings the skin's back.
      const reset = skin && item.value !== null && item.default !== null
        ? el('button', {type: 'button', class: 'quiet', text: t('Use the default'), onclick: () => {
          record({reset: true});
          if (!item.secret) input.value = item.default;
          reset.disabled = true;
        }}) : null;
      const row = el('div', {class: item.value !== null && skin ? 'option changed' : 'option'},
        el('label', {text: item.name}, el('div', {class: 'row'}, input, reset)), notes);
      row.dataset.search = (item.name + ' ' + item.comment).toLowerCase();
      rows.push(row);
      return row;
    };
    const section = (path, tree) => {
      const inner = [
        tree.comment ? el('p', {class: 'note comment', text: tree.comment}) : null,
        tree.options.map(item => option(path, item)),
        tree.sections.map(child => section([...path, child.name], child))];
      return path.length ? el('details', {}, el('summary', {text: tree.name}), ...inner) : el('div', {}, ...inner);
    };
    const body = section([], data.tree);
    const search = el('input', {type: 'search', placeholder: t('Search the options')});
    search.addEventListener('input', () => {
      const needle = search.value.toLowerCase().trim();
      for (const row of rows) row.style.display = !needle || row.dataset.search.includes(needle) ? '' : 'none';
      for (const box of [...body.querySelectorAll('details')].reverse()) {
        const visible = [...box.querySelectorAll('.option')].some(row => row.style.display !== 'none');
        box.style.display = visible ? '' : 'none';
        box.open = Boolean(needle) && visible;
      }
    });
    show(
      select(t('What to set'), 'form', choices, settingsForm, {onchange: event => { settingsForm = event.target.value; select_tab('Settings'); }}),
      el('p', {class: 'note', text: skin
        ? t('These settings are stored in weewx.conf, in the section of the report. They override the skin and stay when the skin is updated.')
        : t('Options of weewx.conf. Sections and new options are added on the System page.')}),
      search, body,
      el('div', {class: 'row sticky'}, el('button', {text: t('Save and restart WeeWX'), onclick: () => {
        if (changes.size) act('settings', {form: settingsForm, changes: [...changes.values()]}, () => select_tab('Settings'));
      }})));
  },

  async Sensors() {
    const draw = async () => {
      const change = tabChanges;
      const data = await api('sensors');
      if (change !== tabChanges) return;
      const rows = data.observations.map(item => el('tr', {},
        el('td', {text: item.name}), el('td', {text: item.value}),
        el('td', {}, item.archived ? t('kept') : el('button', {class: 'quiet', text: t('Add column'), onclick: () => act('database', {action: 'add', name: item.name, type: 'REAL'}, draw)}))));
      const entries = Object.entries(data.mapping);
      const left = t('WeeWX field');
      const right = data.map_kind === 'sensor_map' ? t('Decoded reading') : t('Field from the console');
      const editor = el('tbody', {}, entries.map(([key, value]) => mapRow(key, value)));
      show(
        el('h2', {text: t('What the station receives')}),
        rows.length ? el('table', {}, el('thead', {}, el('tr', {}, [t('Observation'), t('Value'), t('History')].map(text => el('th', {text})))), el('tbody', {}, rows))
          : el('p', {class: 'note', text: t('Nothing received in the last two minutes.')}),
        data.map_kind ? el('h2', {text: t('Assign sensors')}) : null,
        data.map_kind ? el('table', {}, el('thead', {}, el('tr', {}, [left, right, ''].map(text => el('th', {text})))), editor) : null,
        data.map_kind ? el('div', {class: 'row'},
          el('button', {class: 'quiet', text: t('Add entry'), onclick: () => editor.append(mapRow('', ''))}),
          el('button', {text: t('Save and restart WeeWX'), onclick: () => {
            const mapping = {};
            for (const row of editor.children) {
              const [key, value] = row.querySelectorAll('input');
              if (key.value.trim()) mapping[key.value.trim()] = value.value.trim();
            }
            act('sensors', {mapping}, draw);
          }})) : null);
    };
    await draw();
  },

  async Database() {
    const data = await api('database');
    const name = el('input', {name: 'name', placeholder: t('Column name'), required: true});
    const kind = el('select', {name: 'type'}, ['REAL', 'INTEGER', 'TEXT'].map(text => el('option', {text})));
    const redraw = () => select_tab('Database');
    const rows = data.columns.map(column => el('tr', {},
      el('td', {text: column.name}), el('td', {text: column.type}),
      el('td', {}, column.protected ? null : [
        el('button', {class: 'quiet', text: t('Rename'), onclick: () => {
          const new_name = prompt(t('New name of {name}', {name: column.name}));
          if (new_name) act('database', {action: 'rename', name: column.name, new_name}, redraw);
        }}), ' ',
        el('button', {class: 'danger', text: t('Drop'), onclick: () => {
          if (prompt(t('This deletes every value in {name}. A backup is made first. Type the name to confirm.', {name: column.name})) === column.name) {
            act('database', {action: 'drop', name: column.name}, redraw);
          }
        }})])));
    show(
      el('p', {text: t('Database size {size}. Every change makes a backup first and stops WeeWX while it runs.', {size: size(data.size)})}),
      el('form', {class: 'row', onsubmit: event => { event.preventDefault(); act('database', {action: 'add', name: name.value, type: kind.value}, redraw); }},
        name, kind, el('button', {text: t('Add column')})),
      el('table', {}, el('thead', {}, el('tr', {}, [t('Column'), t('Type'), ''].map(text => el('th', {text})))), el('tbody', {}, rows)));
  },

  async Extensions() {
    const data = await api('extensions');
    const redraw = () => select_tab('Extensions');
    const installed = new Set(data.installed.map(item => item.status.split('/').pop().trim()));
    // The column of the catalog only helps when there is more than one.
    const several = data.repositories.filter(source => source.enabled).length > 1;
    const filter = el('input', {placeholder: t('Search the catalog')});
    const results = el('tbody');
    const draw = () => {
      const needle = filter.value.toLowerCase();
      results.replaceChildren(...data.catalog
        .filter(item => !needle || (item.id + item.name + item.description).toLowerCase().includes(needle))
        .slice(0, 60)
        .map(item => el('tr', {},
          el('td', {}, el('b', {text: item.name}), el('div', {class: 'note', text: item.description})),
          several ? el('td', {text: item.repo}) : null,
          el('td', {text: item.category}), el('td', {text: item.version}),
          el('td', {}, installed.has(item.id) ? t('installed') : el('button', {text: t('Install'), onclick: () => act('extensions', {action: 'install', name: item.id, repo: item.repo}, redraw)})))));
    };
    filter.addEventListener('input', draw);
    draw();
    const upload = el('input', {type: 'file', accept: '.zip,.gz,.tgz'});
    const link = el('input', {placeholder: 'https://github.com/owner/repository'});
    const alias = el('input', {placeholder: t('Name, such as my-catalog'), required: true});
    const address = el('input', {placeholder: 'https://example.org/repository.json', required: true});
    const repository = action => source => act('extensions', {action, alias: source.alias}, redraw);
    show(
      data.error ? el('p', {class: 'error', text: data.error}) : null,
      el('h2', {text: t('Installed')}),
      data.installed.length === 0 ? el('p', {class: 'note', text: t('No extensions are installed, or the package manager cannot list them.')}) : el('table', {}, el('thead', {}, el('tr', {}, [t('Name'), t('Version'), t('Source'), ''].map(text => el('th', {text})))),
        el('tbody', {}, data.installed.map(item => {
          const managed = item.source !== '-';
          return el('tr', {}, el('td', {text: item.name}), el('td', {text: item.version}), el('td', {text: item.source}),
            el('td', {},
              managed ? el('button', {class: 'quiet', text: t('Update'), onclick: () => act('extensions', {action: 'update', name: item.name}, redraw)}) : null, ' ',
              el('button', {class: 'danger', text: t('Remove'), onclick: () => { if (confirm(t('Remove {name}?', {name: item.name}))) act('extensions', {action: 'remove', name: item.name}, redraw); }})));
        }))),
      el('div', {class: 'row'}, el('button', {text: t('Update everything'), onclick: () => act('extensions', {action: 'update-all'}, redraw)})),
      el('h2', {text: t('Install from a link')}),
      el('p', {class: 'note', text: t('A GitHub repository installs its newest release, or its main branch if it has no release. A link to a release, a branch or a .zip or .tar.gz file installs exactly that. A package of a catalog installs from the catalog, so it gets updates there.')}),
      el('form', {class: 'row', onsubmit: event => { event.preventDefault(); act('extensions', {action: 'install-link', link: link.value}, redraw); }},
        link, el('button', {text: t('Install')})),
      el('h2', {text: t('Upload an extension')}),
      el('p', {class: 'note', text: t('Installers run on this station, so install only what you trust.')}),
      el('div', {class: 'row'}, upload, el('button', {text: t('Install the file'), onclick: () => {
        if (upload.files[0]) act('extensions/upload?name=' + encodeURIComponent(upload.files[0].name), upload.files[0], redraw);
      }})),
      el('h2', {text: t('Catalog')}), filter,
      el('table', {}, el('thead', {}, el('tr', {}, [t('Name'), several ? t('Catalog') : null, t('Type'), t('Version'), ''].filter(text => text !== null).map(text => el('th', {text})))), results),
      el('h2', {text: t('Catalogs')}),
      el('table', {}, el('thead', {}, el('tr', {}, [t('Name'), t('Address'), t('On'), ''].map(text => el('th', {text})))),
        el('tbody', {}, data.repositories.map(source => el('tr', {},
          el('td', {text: source.alias}), el('td', {text: source.url}),
          el('td', {}, el('input', {type: 'checkbox', checked: source.enabled, disabled: source.main, onchange: event => repository(event.target.checked ? 'repo-enable' : 'repo-disable')(source)})),
          el('td', {}, source.main ? null : el('button', {class: 'danger', text: t('Remove'), onclick: () => { if (confirm(t('Remove {name}?', {name: source.alias}))) repository('repo-remove')(source); }})))))),
      el('form', {class: 'row', onsubmit: event => { event.preventDefault(); act('extensions', {action: 'repo-add', alias: alias.value, url: address.value}, redraw); }},
        alias, address, el('button', {text: t('Add catalog')})));
  },

  async Reports() {
    const data = await api('reports');
    const redraw = () => select_tab('Reports');
    show(
      el('table', {}, el('thead', {}, el('tr', {}, [t('Report'), t('Skin'), t('Target'), t('On')].map(text => el('th', {text})))),
        el('tbody', {}, data.reports.map(report => el('tr', {},
          el('td', {text: report.name}), el('td', {text: report.skin}), el('td', {text: report.html_root}),
          el('td', {}, el('input', {type: 'checkbox', checked: report.enable, onchange: event => act('reports', {name: report.name, enable: event.target.checked}, redraw)})))))),
      el('div', {class: 'row'}, el('button', {text: t('Generate the reports now'), onclick: () => act('reports', {action: 'generate'})})));
  },

  async Uploads() {
    const data = await api('uploads');
    const redraw = () => select_tab('Uploads');
    show(el('div', {}, Object.entries(data.services).map(([name, service]) => {
      const form = el('form', {class: 'service', onsubmit: event => {
        event.preventDefault();
        const submitted = values(form);
        submitted.enable = form.querySelector('[name=enable]').checked;
        act('uploads', {name, values: submitted}, redraw);
      }},
        el('h2', {text: service.title}),
        el('label', {class: 'inline'}, el('input', {type: 'checkbox', name: 'enable', checked: service.enable}), t('Send data')),
        service.fields.map(item => item.kind === 'secret'
          ? field(item.name, item.name, '', {type: 'password', autocomplete: 'new-password', placeholder: service.secrets_set.includes(item.name) ? t('Stored. Leave empty to keep it.') : ''})
          : field(item.name, item.name, service.values[item.name] || '')),
        el('div', {class: 'row'}, el('button', {text: t('Save')})));
      return form;
    })));
  },

  async Backup() {
    const data = await api('backups');
    const redraw = () => select_tab('Backup');
    const upload = el('input', {type: 'file', accept: '.gz'});
    show(
      el('p', {text: t('A backup holds the database, weewx.conf with its passwords, the extensions and the skins. Keep downloads somewhere safe.')}),
      el('div', {class: 'row'}, el('button', {text: t('Create a backup'), onclick: () => act('backups', {action: 'create'}, redraw)})),
      el('table', {}, el('thead', {}, el('tr', {}, [t('File'), t('Size'), t('Created'), ''].map(text => el('th', {text})))),
        el('tbody', {}, data.backups.map(item => el('tr', {},
          el('td', {}, el('a', {href: `/admin/api/backups/${item.name}/download`, text: item.name})),
          el('td', {text: size(item.size)}), el('td', {text: when(item.time)}),
          el('td', {},
            el('button', {class: 'quiet', text: t('Restore'), onclick: () => { if (confirm(t('Replace the station with {name}?', {name: item.name}))) act('backups', {action: 'restore', name: item.name}, redraw); }}), ' ',
            el('button', {class: 'danger', text: t('Delete'), onclick: () => { if (confirm(t('Delete {name}?', {name: item.name}))) act('backups', {action: 'delete', name: item.name}, redraw); }})))))),
      el('h2', {text: t('Upload a backup')}),
      el('div', {class: 'row'}, upload, el('button', {text: t('Upload'), onclick: () => {
        if (upload.files[0]) act('backups/upload', upload.files[0], redraw);
      }})));
  },

  async System() {
    const {text} = await api('config');
    const editor = el('textarea', {spellcheck: 'false'});
    editor.value = text;
    const password = el('form', {onsubmit: event => {
      event.preventDefault();
      act('password', values(password), () => { password.reset(); });
    }},
      field(t('Current password'), 'current', '', {type: 'password', required: true, autocomplete: 'current-password'}),
      field(t('New password'), 'new', '', {type: 'password', required: true, minlength: 8, autocomplete: 'new-password'}),
      el('div', {class: 'row'}, el('button', {text: t('Change the password')})));
    show(
      el('h2', {text: t('Station')}),
      el('div', {class: 'row'},
        el('button', {text: t('Restart WeeWX'), onclick: () => act('system', {action: 'restart-weewx'})}),
        el('button', {text: t('Update the system'), onclick: () => act('system', {action: 'upgrade'})}),
        el('button', {class: 'danger', text: t('Reboot'), onclick: () => { if (confirm(t('Reboot the station?'))) act('system', {action: 'reboot'}); }}),
        el('button', {class: 'danger', text: t('Shut down'), onclick: () => { if (confirm(t('Shut the station down? It stays off until you unplug it.'))) act('system', {action: 'poweroff'}); }})),
      el('h2', {text: t('Administrator password')}), password,
      el('h2', {text: 'weewx.conf'}), editor,
      el('div', {class: 'row'}, el('button', {text: t('Save and restart WeeWX'), onclick: () => act('config', {text: editor.value})})));
  },
};

async function select_tab(name) {
  tabChanges++;
  clearInterval(refreshTimer);
  refreshTimer = null;
  for (const button of tabs.children) button.classList.toggle('active', button.dataset.view === name);
  try {
    await views[name]();
  } catch (error) {
    show(el('p', {class: 'error', text: error.message}));
  }
}

function showApplication(firstTab) {
  tabs.hidden = false;
  logout.hidden = false;
  tabs.replaceChildren(...Object.keys(views).map(name => el('button', {text: t(name), 'data-view': name, onclick: () => select_tab(name)})));
  select_tab(firstTab);
}

function showLogin() {
  clearInterval(refreshTimer);
  tabs.hidden = true;
  logout.hidden = true;
  const password = el('input', {type: 'password', required: true, autocomplete: 'current-password'});
  const form = el('form', {class: 'card narrow', onsubmit: async event => {
    event.preventDefault();
    try {
      await api('login', {password: password.value});
      showApplication('Status');
    } catch (error) { failure(error); }
  }}, el('h2', {text: t('Log in')}), el('label', {text: t('Password')}, password), el('div', {class: 'row'}, el('button', {text: t('Log in')})));
  show(form);
}

function showFirstStart() {
  const first = el('input', {type: 'password', required: true, minlength: 8, autocomplete: 'new-password'});
  const second = el('input', {type: 'password', required: true, autocomplete: 'new-password'});
  const form = el('form', {class: 'card narrow', onsubmit: async event => {
    event.preventDefault();
    if (first.value !== second.value) { failure(new Error(t('The passwords differ.'))); return; }
    try {
      await api('setup-password', {password: first.value});
      showApplication('Station');
    } catch (error) { failure(error); }
  }},
    el('h2', {text: t('Welcome')}),
    el('p', {text: t('Choose a password for this administration. Everyone on your network can reach this page until you do.')}),
    el('label', {text: t('Password, at least 8 characters')}, first),
    el('label', {text: t('Repeat the password')}, second),
    el('div', {class: 'row'}, el('button', {text: t('Continue')})));
  show(form);
}

logout.addEventListener('click', async () => {
  await api('logout', {});
  showLogin();
});

(async () => {
  document.documentElement.lang = language;
  if (language !== 'en') {
    catalog = await fetch(`/admin/i18n/${language}.json`).then(reply => reply.json()).catch(() => ({}));
  }
  document.title = t('WeeWX Station administration');
  document.getElementById('weather-pages').textContent = t('Weather pages');
  logout.textContent = t('Log out');
  languageChoice.replaceChildren(...Object.entries(LANGUAGES).map(([code, name]) => el('option', {value: code, text: name, selected: code === language})));
  languageChoice.addEventListener('change', () => {
    localStorage.setItem('language', languageChoice.value);
    location.reload();
  });
  // A reload can hit the seconds in which an update restarts this server.
  let session;
  while (!session) {
    try {
      session = await api('session');
    } catch (error) {
      show(el('p', {class: 'note', text: t('Waiting for the administration.')}));
      await new Promise(resolve => setTimeout(resolve, 2000));
    }
  }
  if (!session.password_set) showFirstStart();
  else if (session.authenticated) showApplication('Status');
  else showLogin();
})();
