(async function init() {
  const cfg = window.LOOKUP_CONFIG;
  if (!cfg) {
    console.error('LOOKUP_CONFIG is not defined. Set it before loading lookup.js.');
    return;
  }
  const lang = cfg.lang; // 'en' or 'fr'

  const loadingMsg = document.getElementById('loading-msg');
  const errorMsg = document.getElementById('error-msg');
  const app = document.getElementById('app');

  let services;
  let generatedAt;
  try {
    const resp = await fetch('services.json');
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    services = data.services;
    generatedAt = data.generated_at;
  } catch (_) {
    loadingMsg.hidden = true;
    errorMsg.hidden = false;
    return;
  }

  const acronymMap = new Map(services.map(s => [s[`org_name_${lang}`], s[`acronym_${lang}`]]));

  loadingMsg.hidden = true;
  app.hidden = false;

  const lastUpdated = document.getElementById('last-updated');
  lastUpdated.textContent = `${cfg.strings.lastUpdated}: ${new Date(generatedAt).toLocaleDateString(cfg.locale, { year: 'numeric', month: 'long', day: 'numeric' })}`;
  lastUpdated.hidden = false;

  // --- State ---
  let currentDept = '';
  let currentMatches = [];
  let activeIndex = -1;
  let lastQuery = '';
  let debounceTimer = null;

  // --- DOM refs ---
  const deptInput = document.querySelector('gcds-input[input-id="dept-input"]');
  const deptDropdown = document.getElementById('dept-dropdown');
  const serviceInput = document.querySelector('gcds-input[input-id="service-input"]');
  const dropdown = document.getElementById('dropdown');
  const resultDiv = document.getElementById('result');

  // --- Shared value reader for GCDS events ---
  function readValue(e) {
    if (e.detail && typeof e.detail.value === 'string') return e.detail.value;
    if (e.target && 'value' in e.target) return e.target.value;
    return '';
  }

  // -----------------------------------------------
  // Department autocomplete
  // -----------------------------------------------
  const allDepts = [...new Set(services.map(s => s[`org_name_${lang}`]))].sort();
  let deptMatches = [];
  let deptActiveIndex = -1;
  let deptLastQuery = '';
  let deptDebounceTimer = null;

  deptInput.addEventListener('focus', () => runDeptSearch(deptLastQuery));
  deptInput.addEventListener('gcdsInput', e => scheduleDept(readValue(e)));
  deptInput.addEventListener('input', e => scheduleDept(readValue(e)));

  function scheduleDept(value) {
    clearTimeout(deptDebounceTimer);
    deptDebounceTimer = setTimeout(() => runDeptSearch(value.trim()), 120);
  }

  function runDeptSearch(q) {
    deptLastQuery = q;
    if (currentDept) {
      currentDept = '';
      serviceInput.disabled = true;
      serviceInput.value = '';
      lastQuery = '';
      hideDropdown();
      hideResult();
    }
    deptMatches = allDepts
      .filter(d => {
        if (!q) return true;
        const acronym = acronymMap.get(d);
        const searchable = acronym ? `${d} ${acronym}` : d;
        return searchable.toLowerCase().includes(q.toLowerCase());
      })
      .slice(0, 10);
    deptActiveIndex = -1;
    renderDeptDropdown();
  }

  function renderDeptDropdown() {
    deptDropdown.textContent = '';
    deptMatches.forEach((dept, i) => {
      const item = document.createElement('div');
      item.className = 'dropdown-item' + (i === deptActiveIndex ? ' active' : '');
      item.setAttribute('role', 'option');
      // innerHTML is safe: highlight() only inserts text through escHtml()
      const acronym = acronymMap.get(dept);
      const label = acronym ? `${dept} (${acronym})` : dept;
      item.innerHTML = highlight(label, deptLastQuery);
      item.addEventListener('mousedown', e => {
        e.preventDefault();
        selectDept(dept);
      });
      deptDropdown.appendChild(item);
    });
    deptDropdown.style.display = deptMatches.length ? 'block' : 'none';
  }

  function hideDeptDropdown() {
    deptDropdown.style.display = 'none';
    deptDropdown.textContent = '';
    deptActiveIndex = -1;
    deptMatches = [];
  }

  function selectDept(name) {
    deptInput.value = name;
    currentDept = name;
    hideDeptDropdown();
    serviceInput.disabled = false;
  }

  deptInput.addEventListener('keydown', e => {
    if (deptDropdown.style.display === 'none') return;
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        deptActiveIndex = Math.min(deptActiveIndex + 1, deptMatches.length - 1);
        renderDeptDropdown();
        break;
      case 'ArrowUp':
        e.preventDefault();
        deptActiveIndex = Math.max(deptActiveIndex - 1, -1);
        renderDeptDropdown();
        break;
      case 'Enter':
        if (deptActiveIndex >= 0 && deptMatches[deptActiveIndex]) {
          selectDept(deptMatches[deptActiveIndex]);
        }
        break;
      case 'Escape':
        hideDeptDropdown();
        break;
    }
  });

  // -----------------------------------------------
  // Service search
  // -----------------------------------------------
  serviceInput.addEventListener('focus', () => { if (currentDept) runSearch(lastQuery); });
  serviceInput.addEventListener('gcdsInput', e => schedule(readValue(e)));
  serviceInput.addEventListener('input', e => schedule(readValue(e)));

  function schedule(value) {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => runSearch(value.trim()), 120);
  }

  function runSearch(q) {
    lastQuery = q;
    hideResult();
    if (!currentDept) { hideDropdown(); return; }

    currentMatches = services
      .filter(s =>
        s[`org_name_${lang}`] === currentDept &&
        (!q || s[`service_${lang}`].toLowerCase().includes(q.toLowerCase()))
      )
      .slice(0, 10);

    activeIndex = -1;
    renderDropdown(q);
  }

  function escHtml(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function highlight(text, query) {
    if (!query) return escHtml(text);
    const idx = text.toLowerCase().indexOf(query.toLowerCase());
    if (idx === -1) return escHtml(text);
    return (
      escHtml(text.slice(0, idx)) +
      '<mark>' + escHtml(text.slice(idx, idx + query.length)) + '</mark>' +
      escHtml(text.slice(idx + query.length))
    );
  }

  function renderDropdown(query) {
    dropdown.textContent = '';
    if (currentMatches.length === 0) {
      const msg = document.createElement('div');
      msg.className = 'dropdown-item';
      msg.style.fontStyle = 'italic';
      msg.style.color = '#5a6a7e';
      msg.textContent = cfg.strings.noMatches;
      dropdown.appendChild(msg);
    } else {
      currentMatches.forEach((match, i) => {
        const item = document.createElement('div');
        item.className = 'dropdown-item' + (i === activeIndex ? ' active' : '');
        item.setAttribute('role', 'option');
        // innerHTML is safe: highlight() only inserts text through escHtml()
        item.innerHTML = highlight(match[`service_${lang}`], query);
        item.addEventListener('mousedown', e => {
          e.preventDefault();
          selectService(match);
        });
        dropdown.appendChild(item);
      });
    }
    dropdown.style.display = 'block';
  }

  function hideDropdown() {
    dropdown.style.display = 'none';
    dropdown.textContent = '';
    activeIndex = -1;
    currentMatches = [];
  }

  // -----------------------------------------------
  // Keyboard navigation
  // -----------------------------------------------
  serviceInput.addEventListener('keydown', e => {
    if (dropdown.style.display === 'none') return;
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        activeIndex = Math.min(activeIndex + 1, currentMatches.length - 1);
        renderDropdown(lastQuery);
        break;
      case 'ArrowUp':
        e.preventDefault();
        activeIndex = Math.max(activeIndex - 1, -1);
        renderDropdown(lastQuery);
        break;
      case 'Enter':
        if (activeIndex >= 0 && currentMatches[activeIndex]) {
          selectService(currentMatches[activeIndex]);
        }
        break;
      case 'Escape':
        hideDropdown();
        break;
    }
  });

  document.addEventListener('click', e => {
    const inWrapper = e.composedPath().some(n => n.classList?.contains('search-wrapper'));
    if (!inWrapper) {
      hideDeptDropdown();
      hideDropdown();
    }
  });

  // -----------------------------------------------
  // Result panel
  // -----------------------------------------------
  function selectService(service) {
    serviceInput.value = service[`service_${lang}`];
    hideDropdown();

    document.getElementById('r-service-en').textContent = service.service_en;
    document.getElementById('r-service-fr').textContent = service.service_fr;
    const acronym = service[`acronym_${lang}`];
    document.getElementById('r-org-en').textContent = `${service[`org_name_${lang}`]} (${service.gc_orgID})`;
    document.getElementById('r-service-id').textContent = service.service_id;
    const pid = service.program_id;
    document.getElementById('r-program-id').textContent =
      Array.isArray(pid) && pid.length > 0 ? pid.join(', ') : cfg.strings.noProgram;

    const copyBtn = document.getElementById('copy-btn');
    copyBtn.textContent = cfg.strings.copyDefault;
    resultDiv.hidden = false;
  }

  function hideResult() {
    resultDiv.hidden = true;
  }

  // -----------------------------------------------
  // Copy button
  // -----------------------------------------------
  document.getElementById('copy-btn').addEventListener('click', () => {
    const id = document.getElementById('r-service-id').textContent;
    navigator.clipboard.writeText(id).then(() => {
      const btn = document.getElementById('copy-btn');
      btn.textContent = cfg.strings.copied;
      setTimeout(() => { btn.textContent = cfg.strings.copyDefault; }, 2000);
    }).catch(() => {
      document.getElementById('copy-btn').textContent = cfg.strings.copyFailed;
    });
  });
})();