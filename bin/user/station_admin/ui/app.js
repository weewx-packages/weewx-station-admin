// Copyright (c) 2026 Manuel Hilgert <hilman2@gmail.com>
'use strict';

const page = document.getElementById('page');
const tabs = document.getElementById('tabs');
const jobBox = document.getElementById('job');
const logout = document.getElementById('logout');
let refreshTimer = null;

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
  const options = {headers: {'X-Station-Admin': '1'}};
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
  if (reply.status === 401) { showLogin(); throw new Error('Log in first.'); }
  if (!reply.ok) throw new Error(value.error || 'The request failed.');
  return value;
}

function size(bytes) {
  const units = ['B', 'KB', 'MB', 'GB'];
  let index = 0;
  while (bytes >= 1024 && index < units.length - 1) { bytes /= 1024; index++; }
  return bytes.toFixed(index ? 1 : 0) + ' ' + units[index];
}

function when(seconds) {
  return seconds ? new Date(seconds * 1000).toLocaleString() : '-';
}

function field(label, name, value, attributes = {}) {
  return el('label', {text: label}, el('input', {name, value, ...attributes}));
}

function select(label, name, choices, value, attributes = {}) {
  return el('label', {text: label}, el('select', {name, ...attributes},
    Object.entries(choices).map(([key, text]) => el('option', {value: key, text, selected: key === String(value)}))));
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
  const close = el('button', {class: 'quiet', text: 'Close', onclick: () => { jobBox.hidden = true; }, hidden: true});
  jobBox.replaceChildren(title, output, close);
  for (;;) {
    let job;
    try {
      job = await api('jobs/' + number);
    } catch (error) {
      // An update restarts this server a few seconds after its job has ended.
      title.textContent = 'The administration restarted. Reload the page.';
      close.hidden = false;
      return;
    }
    title.textContent = job.title + ': ' + job.state;
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
      const status = await api('status');
      const tiles = [
        ['WeeWX', status.weewx],
        ['Last record', status.record ? when(status.record.time) : 'none yet'],
        ['Records', status.record ? status.record.rows.toLocaleString() : '0'],
        ['Free disk', size(status.disk.free)],
        ['Free memory', size(status.memory.available)],
        ['Temperature', status.temperature === null ? '-' : status.temperature.toFixed(1) + ' °C'],
        ['Time', status.time_synced ? 'synchronized' : 'waiting'],
        ['Address', status.address || '-'],
      ];
      const live = status.live ? Object.entries(status.live).filter(([name]) => !['dateTime', 'usUnits'].includes(name)) : [];
      page.replaceChildren(
        el('p', {class: 'message', text: status.message}),
        el('div', {class: 'tiles'}, tiles.map(([name, value]) => el('div', {class: 'tile'}, el('b', {text: String(value)}), el('span', {text: name})))),
        live.length ? el('h2', {text: 'Current readings'}) : null,
        live.length ? el('div', {class: 'tiles'}, live.map(([name, value]) => el('div', {class: 'tile'}, el('b', {text: String(Math.round(value * 100) / 100)}), el('span', {text: name})))) : null,
        el('h2', {text: 'Log'}), el('pre', {text: status.log}),
        el('p', {class: 'note', text: status.release || ''}));
    };
    await draw();
    refreshTimer = setInterval(() => draw().catch(() => {}), 5000);
  },

  async Station() {
    const {values: current, address, configured, timezone} = await api('station');
    const zone = !configured && Intl.DateTimeFormat().resolvedOptions().timeZone || timezone;
    const driverBox = el('div');
    const drawDriver = driver => {
      if (driver === 'rtldavis') {
        driverBox.replaceChildren(
          select('Frequency band', 'band', {EU: 'EU, 868 MHz', US: 'US, 915 MHz', NZ: 'NZ, 921 MHz'}, current.band, {
            onchange: event => { driverBox.querySelector('[name=bucket]').value = event.target.value === 'US' ? '0' : '1'; }}),
          select('ISS channel, as shown on the console', 'channel', Object.fromEntries([1, 2, 3, 4, 5, 6, 7, 8].map(n => [n, n])), current.channel),
          select('Rain bucket', 'bucket', {1: '0.2 mm per tip', 0: '0.01 inch per tip'}, current.bucket));
      } else {
        driverBox.replaceChildren(
          field('Port', 'port', current.port, {inputmode: 'numeric'}),
          el('p', {class: 'note', text: `In WS View Plus under Weather Services, Customized, set: protocol Ecowitt, server ${address || 'this address'}, path /, port ${current.port}, interval 60 seconds.`}));
      }
    };
    drawDriver(current.driver);
    const form = el('form', {onsubmit: event => {
      event.preventDefault();
      act('station', values(form), () => { select_tab('Status'); });
    }},
      select('Kind of station', 'driver', {rtldavis: 'Davis, through an RTL-SDR dongle', ecowitt: 'Ecowitt console'}, current.driver, {onchange: event => drawDriver(event.target.value)}),
      field('Station name', 'location', configured ? current.location : '', {required: true, maxlength: 80}),
      field('Latitude', 'latitude', configured ? current.latitude : '', {required: true, inputmode: 'decimal', placeholder: '52.52'}),
      field('Longitude', 'longitude', configured ? current.longitude : '', {required: true, inputmode: 'decimal', placeholder: '13.40'}),
      field('Altitude', 'altitude', configured ? current.altitude : '', {required: true, inputmode: 'decimal'}),
      select('Altitude given in', 'altitude_unit', {meter: 'metres', foot: 'feet'}, current.altitude_unit),
      field('Time zone', 'timezone', zone, {required: true}),
      select('Units on the weather pages', 'units', {metricwx: 'Metric (°C, m/s, mm)', metric: 'Metric (°C, km/h, cm)', us: 'US (°F, mph, in)'}, current.units),
      driverBox,
      el('div', {class: 'row'}, el('button', {text: 'Save and start'})));
    page.replaceChildren(form);
  },

  async Sensors() {
    const draw = async () => {
      const data = await api('sensors');
      const rows = data.observations.map(item => el('tr', {},
        el('td', {text: item.name}), el('td', {text: String(Math.round(item.value * 100) / 100)}),
        el('td', {}, item.archived ? 'kept' : el('button', {class: 'quiet', text: 'Add column', onclick: () => act('database', {action: 'add', name: item.name, type: 'REAL'}, draw)}))));
      const entries = Object.entries(data.mapping);
      const left = 'WeeWX field';
      const right = data.map_kind === 'sensor_map' ? 'Decoded reading' : 'Field from the console';
      const editor = el('tbody', {}, entries.map(([key, value]) => mapRow(key, value)));
      page.replaceChildren(
        el('h2', {text: 'What the station receives'}),
        rows.length ? el('table', {}, el('thead', {}, el('tr', {}, ['Observation', 'Value', 'History'].map(text => el('th', {text})))), el('tbody', {}, rows))
          : el('p', {class: 'note', text: 'Nothing received in the last two minutes.'}),
        data.map_kind ? el('h2', {text: 'Assign sensors'}) : null,
        data.map_kind ? el('table', {}, el('thead', {}, el('tr', {}, [left, right, ''].map(text => el('th', {text})))), editor) : null,
        data.map_kind ? el('div', {class: 'row'},
          el('button', {class: 'quiet', text: 'Add entry', onclick: () => editor.append(mapRow('', ''))}),
          el('button', {text: 'Save and restart WeeWX', onclick: () => {
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
    const name = el('input', {name: 'name', placeholder: 'Column name', required: true});
    const kind = el('select', {name: 'type'}, ['REAL', 'INTEGER', 'TEXT'].map(text => el('option', {text})));
    const redraw = () => select_tab('Database');
    const rows = data.columns.map(column => el('tr', {},
      el('td', {text: column.name}), el('td', {text: column.type}),
      el('td', {}, column.protected ? null : [
        el('button', {class: 'quiet', text: 'Rename', onclick: () => {
          const new_name = prompt('New name of ' + column.name);
          if (new_name) act('database', {action: 'rename', name: column.name, new_name}, redraw);
        }}), ' ',
        el('button', {class: 'danger', text: 'Drop', onclick: () => {
          if (prompt(`This deletes every value in ${column.name}. A backup is made first. Type the name to confirm.`) === column.name) {
            act('database', {action: 'drop', name: column.name}, redraw);
          }
        }})])));
    page.replaceChildren(
      el('p', {text: `Database size ${size(data.size)}. Every change makes a backup first and stops WeeWX while it runs.`}),
      el('form', {class: 'row', onsubmit: event => { event.preventDefault(); act('database', {action: 'add', name: name.value, type: kind.value}, redraw); }},
        name, kind, el('button', {text: 'Add column'})),
      el('table', {}, el('thead', {}, el('tr', {}, ['Column', 'Type', ''].map(text => el('th', {text})))), el('tbody', {}, rows)));
  },

  async Extensions() {
    const data = await api('extensions');
    const redraw = () => select_tab('Extensions');
    const installed = new Set(data.installed.map(item => item.status.split('/').pop().trim()));
    const filter = el('input', {placeholder: 'Search the catalog'});
    const results = el('tbody');
    const draw = () => {
      const needle = filter.value.toLowerCase();
      results.replaceChildren(...data.catalog
        .filter(item => !needle || (item.id + item.name + item.description).toLowerCase().includes(needle))
        .slice(0, 60)
        .map(item => el('tr', {},
          el('td', {}, el('b', {text: item.name}), el('div', {class: 'note', text: item.description})),
          el('td', {text: item.category}), el('td', {text: item.version}),
          el('td', {}, installed.has(item.id) ? 'installed' : el('button', {text: 'Install', onclick: () => act('extensions', {action: 'install', name: item.id}, redraw)})))));
    };
    filter.addEventListener('input', draw);
    draw();
    const upload = el('input', {type: 'file', accept: '.zip,.gz,.tgz'});
    page.replaceChildren(
      data.error ? el('p', {class: 'error', text: data.error}) : null,
      el('h2', {text: 'Installed'}),
      el('table', {}, el('thead', {}, el('tr', {}, ['Name', 'Version', 'Source', ''].map(text => el('th', {text})))),
        el('tbody', {}, data.installed.map(item => {
          const managed = item.source !== '-';
          return el('tr', {}, el('td', {text: item.name}), el('td', {text: item.version}), el('td', {text: item.source}),
            el('td', {},
              managed ? el('button', {class: 'quiet', text: 'Update', onclick: () => act('extensions', {action: 'update', name: item.name}, redraw)}) : null, ' ',
              el('button', {class: 'danger', text: 'Remove', onclick: () => { if (confirm('Remove ' + item.name + '?')) act('extensions', {action: 'remove', name: item.name}, redraw); }})));
        }))),
      el('div', {class: 'row'}, el('button', {text: 'Update everything', onclick: () => act('extensions', {action: 'update-all'}, redraw)})),
      el('h2', {text: 'Upload an extension'}),
      el('p', {class: 'note', text: 'Installers run on this station, so install only what you trust.'}),
      el('div', {class: 'row'}, upload, el('button', {text: 'Install the file', onclick: () => {
        if (upload.files[0]) act('extensions/upload?name=' + encodeURIComponent(upload.files[0].name), upload.files[0], redraw);
      }})),
      el('h2', {text: 'Catalog'}), filter, el('table', {}, results));
  },

  async Reports() {
    const data = await api('reports');
    const redraw = () => select_tab('Reports');
    page.replaceChildren(
      el('table', {}, el('thead', {}, el('tr', {}, ['Report', 'Skin', 'Target', 'On'].map(text => el('th', {text})))),
        el('tbody', {}, data.reports.map(report => el('tr', {},
          el('td', {text: report.name}), el('td', {text: report.skin}), el('td', {text: report.html_root}),
          el('td', {}, el('input', {type: 'checkbox', checked: report.enable, onchange: event => act('reports', {name: report.name, enable: event.target.checked}, redraw)})))))),
      el('div', {class: 'row'}, el('button', {text: 'Generate the reports now', onclick: () => act('reports', {action: 'generate'})})));
  },

  async Uploads() {
    const data = await api('uploads');
    const redraw = () => select_tab('Uploads');
    page.replaceChildren(el('div', {}, Object.entries(data.services).map(([name, service]) => {
      const form = el('form', {class: 'service', onsubmit: event => {
        event.preventDefault();
        const submitted = values(form);
        submitted.enable = form.querySelector('[name=enable]').checked;
        act('uploads', {name, values: submitted}, redraw);
      }},
        el('h2', {text: service.title}),
        el('label', {class: 'inline'}, el('input', {type: 'checkbox', name: 'enable', checked: service.enable}), 'Send data'),
        service.fields.map(item => item.kind === 'secret'
          ? field(item.name, item.name, '', {type: 'password', autocomplete: 'new-password', placeholder: service.secrets_set.includes(item.name) ? 'stored; leave empty to keep' : ''})
          : field(item.name, item.name, service.values[item.name] || '')),
        el('div', {class: 'row'}, el('button', {text: 'Save'})));
      return form;
    })));
  },

  async Backup() {
    const data = await api('backups');
    const redraw = () => select_tab('Backup');
    const upload = el('input', {type: 'file', accept: '.gz'});
    page.replaceChildren(
      el('p', {text: 'A backup holds the database, weewx.conf with its passwords, the extensions and the skins. Keep downloads somewhere safe.'}),
      el('div', {class: 'row'}, el('button', {text: 'Create a backup', onclick: () => act('backups', {action: 'create'}, redraw)})),
      el('table', {}, el('thead', {}, el('tr', {}, ['File', 'Size', 'Created', ''].map(text => el('th', {text})))),
        el('tbody', {}, data.backups.map(item => el('tr', {},
          el('td', {}, el('a', {href: `/admin/api/backups/${item.name}/download`, text: item.name})),
          el('td', {text: size(item.size)}), el('td', {text: when(item.time)}),
          el('td', {},
            el('button', {class: 'quiet', text: 'Restore', onclick: () => { if (confirm('Replace the station with ' + item.name + '?')) act('backups', {action: 'restore', name: item.name}, redraw); }}), ' ',
            el('button', {class: 'danger', text: 'Delete', onclick: () => { if (confirm('Delete ' + item.name + '?')) act('backups', {action: 'delete', name: item.name}, redraw); }})))))),
      el('h2', {text: 'Upload a backup'}),
      el('div', {class: 'row'}, upload, el('button', {text: 'Upload', onclick: () => {
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
      field('Current password', 'current', '', {type: 'password', required: true, autocomplete: 'current-password'}),
      field('New password', 'new', '', {type: 'password', required: true, minlength: 8, autocomplete: 'new-password'}),
      el('div', {class: 'row'}, el('button', {text: 'Change the password'})));
    page.replaceChildren(
      el('h2', {text: 'Station'}),
      el('div', {class: 'row'},
        el('button', {text: 'Restart WeeWX', onclick: () => act('system', {action: 'restart-weewx'})}),
        el('button', {text: 'Update the system', onclick: () => act('system', {action: 'upgrade'})}),
        el('button', {class: 'danger', text: 'Reboot', onclick: () => { if (confirm('Reboot the station?')) act('system', {action: 'reboot'}); }}),
        el('button', {class: 'danger', text: 'Shut down', onclick: () => { if (confirm('Shut the station down? It stays off until you unplug it.')) act('system', {action: 'poweroff'}); }})),
      el('h2', {text: 'Administrator password'}), password,
      el('h2', {text: 'weewx.conf'}), editor,
      el('div', {class: 'row'}, el('button', {text: 'Save and restart WeeWX', onclick: () => act('config', {text: editor.value})})));
  },
};

async function select_tab(name) {
  clearInterval(refreshTimer);
  refreshTimer = null;
  for (const button of tabs.children) button.classList.toggle('active', button.textContent === name);
  try {
    await views[name]();
  } catch (error) {
    page.replaceChildren(el('p', {class: 'error', text: error.message}));
  }
}

function showApplication(firstTab) {
  tabs.hidden = false;
  logout.hidden = false;
  tabs.replaceChildren(...Object.keys(views).map(name => el('button', {text: name, onclick: () => select_tab(name)})));
  select_tab(firstTab);
}

function showLogin() {
  clearInterval(refreshTimer);
  tabs.hidden = true;
  logout.hidden = true;
  const password = el('input', {type: 'password', required: true, autocomplete: 'current-password'});
  const form = el('form', {onsubmit: async event => {
    event.preventDefault();
    try {
      await api('login', {password: password.value});
      showApplication('Status');
    } catch (error) { failure(error); }
  }}, el('label', {text: 'Password'}, password), el('div', {class: 'row'}, el('button', {text: 'Log in'})));
  page.replaceChildren(form);
}

function showFirstStart() {
  const first = el('input', {type: 'password', required: true, minlength: 8, autocomplete: 'new-password'});
  const second = el('input', {type: 'password', required: true, autocomplete: 'new-password'});
  const form = el('form', {onsubmit: async event => {
    event.preventDefault();
    if (first.value !== second.value) { failure(new Error('The passwords differ.')); return; }
    try {
      await api('setup-password', {password: first.value});
      showApplication('Station');
    } catch (error) { failure(error); }
  }},
    el('h2', {text: 'Welcome'}),
    el('p', {text: 'Choose a password for this administration. Everyone on your network can reach this page until you do.'}),
    el('label', {text: 'Password, at least 8 characters'}, first),
    el('label', {text: 'Repeat the password'}, second),
    el('div', {class: 'row'}, el('button', {text: 'Continue'})));
  page.replaceChildren(form);
}

logout.addEventListener('click', async () => {
  await api('logout', {});
  showLogin();
});

(async () => {
  // A reload can hit the seconds in which an update restarts this server.
  let session;
  while (!session) {
    try {
      session = await api('session');
    } catch (error) {
      page.replaceChildren(el('p', {class: 'note', text: 'Waiting for the administration.'}));
      await new Promise(resolve => setTimeout(resolve, 2000));
    }
  }
  if (!session.password_set) showFirstStart();
  else if (session.authenticated) showApplication('Status');
  else showLogin();
})();
