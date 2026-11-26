(() => {
  // Ready-made base URLs for OpenAI-compatible services; "Other" lets the user type any URL.
  const API_PRESETS = [
    { label: 'OpenAI', url: 'https://api.openai.com/v1' },
    { label: 'Groq', url: 'https://api.groq.com/openai/v1' },
    { label: 'OpenRouter', url: 'https://openrouter.ai/api/v1' },
    { label: 'Google Gemini', url: 'https://generativelanguage.googleapis.com/v1beta/openai' },
    { label: 'LM Studio (on this computer)', url: 'http://localhost:1234/v1' },
    { label: 'Other', url: '' },
  ];

  function initializeAssistantSettings() {
    if (!document.getElementById('assistantSettings')) return;

    const $ = id => document.getElementById(id);
    const providerOllama = $('assistantProviderOllama');
    const providerApi = $('assistantProviderApi');
    const ollamaSection = $('assistantOllamaSection');
    const apiSection = $('assistantApiSection');
    const ollamaUrl = $('assistantOllamaUrl');
    const ollamaModel = $('assistantOllamaModel');
    const ollamaInfo = $('assistantOllamaInfo');
    const refreshButton = $('assistantRefreshModels');
    const memoryInfo = $('assistantMemoryInfo');
    const recommendedList = $('assistantRecommended');
    const customModel = $('assistantCustomModel');
    const pullCustomButton = $('assistantPullCustom');
    const pullProgress = $('assistantPullProgress');
    const pullText = $('assistantPullText');
    const pullBar = $('assistantPullBar');
    const apiPreset = $('assistantApiPreset');
    const apiUrl = $('assistantApiUrl');
    const apiModel = $('assistantApiModel');
    const apiKey = $('assistantApiKey');
    const apiKeyClearWrap = $('assistantApiKeyClearWrap');
    const apiKeyClear = $('assistantApiKeyClear');
    const saveButton = $('assistantSave');
    const testButton = $('assistantTest');
    const status = $('assistantStatus');
    const badge = $('assistantBadge');

    let saved = null;
    let pullTimer = null;

    async function request(path, options = {}) {
      const response = await fetch(`/api${path}`, { ...options, credentials: 'include' });

      if (response.status === 401) {
        window.location.href = '/login';
        throw new Error('Please sign in.');
      }

      const data = await response.json().catch(() => null);

      if (!response.ok) {
        const detail = data?.detail;
        throw new Error(
          Array.isArray(detail)
            ? detail.map(item => item.msg.replace(/^Value error, /, '')).join('; ')
            : typeof detail === 'string' ? detail : `Request failed: HTTP ${response.status}`
        );
      }
      return data;
    }

    function setStatus(text, kind = '') {
      status.textContent = text;
      status.className = `small mt-2 mb-0 ${kind ? `text-${kind}` : ''}`;
    }

    function selectedProvider() {
      return providerApi.checked ? 'api' : 'ollama';
    }

    function showProvider() {
      const api = selectedProvider() === 'api';
      ollamaSection.hidden = api;
      apiSection.hidden = !api;
    }

    function updateBadge() {
      if (!saved) return;
      if (saved.provider === 'api') {
        badge.className = 'badge text-bg-warning';
        badge.textContent = `External API · ${saved.api_model}`;
      } else {
        badge.className = 'badge text-bg-success';
        badge.textContent = `Local · ${saved.ollama_model}`;
      }
    }

    function formatGb(bytes) {
      return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
    }

    // ---- API presets ----
    API_PRESETS.forEach(preset => apiPreset.add(new Option(preset.label, preset.url)));

    function matchPreset() {
      const match = API_PRESETS.find(preset => preset.url && preset.url === apiUrl.value.trim().replace(/\/+$/, ''));
      apiPreset.value = match ? match.url : '';
    }

    apiPreset.addEventListener('change', () => {
      if (apiPreset.value) apiUrl.value = apiPreset.value;
      apiUrl.focus();
    });
    apiUrl.addEventListener('input', matchPreset);

    // ---- Ollama models ----
    function renderModelSelect(installed) {
      const current = saved?.ollama_model;
      ollamaModel.replaceChildren();

      installed.forEach(model => {
        const details = [model.parameter_size, `${model.size_gb} GB`].filter(Boolean).join(', ');
        ollamaModel.add(new Option(`${model.name} (${details})`, model.name));
      });

      if (current && !installed.some(model => model.name === current)) {
        ollamaModel.add(new Option(`${current} (not downloaded yet)`, current), 0);
      }
      if (current) ollamaModel.value = current;
    }

    function renderRecommended(models, memory) {
      memoryInfo.textContent = memory
        ? `This computer has about ${memory} GB of memory. Models marked "Fits" should run well.`
        : 'Models that need less memory answer faster.';

      recommendedList.replaceChildren();

      models.forEach(model => {
        const row = document.createElement('div');
        row.className = 'list-group-item d-flex align-items-center flex-wrap gap-2';

        const text = document.createElement('div');
        text.className = 'me-auto';
        const name = document.createElement('div');
        name.style.fontWeight = '500';
        name.textContent = model.name;
        const description = document.createElement('div');
        description.className = 'small text-muted';
        description.textContent = `${model.label} · about ${model.download_gb} GB download · needs ${model.min_ram_gb} GB memory`;
        text.append(name, description);

        const fit = document.createElement('span');
        fit.className = `badge ${model.fits ? 'text-bg-success' : 'text-bg-secondary'}`;
        fit.textContent = model.fits ? 'Fits' : 'May be too large';

        const action = document.createElement('button');
        action.type = 'button';
        action.className = 'btn btn-sm btn-outline-primary';
        if (model.installed) {
          action.textContent = 'Use';
          action.addEventListener('click', () => {
            ollamaModel.value = model.name;
            setStatus(`Selected ${model.name}. Click Save to use it.`);
          });
        } else {
          action.textContent = 'Download';
          action.addEventListener('click', () => pullModel(model.name));
        }

        row.append(text, fit, action);
        recommendedList.appendChild(row);
      });
    }

    async function loadModels() {
      refreshButton.disabled = true;
      ollamaInfo.textContent = 'Looking for installed models…';
      try {
        const data = await request('/assistant/ollama/models');
        renderModelSelect(data.installed);
        renderRecommended(data.recommended, data.system_memory_gb);

        if (!data.reachable) {
          ollamaInfo.className = 'form-text text-danger';
          ollamaInfo.textContent = `${data.error} Start Ollama, then click Refresh.`;
        } else {
          ollamaInfo.className = 'form-text';
          ollamaInfo.textContent = data.installed.length
            ? `${data.installed.length} model(s) installed.`
            : 'No models installed yet. Download one below.';
        }
      } catch (error) {
        ollamaInfo.className = 'form-text text-danger';
        ollamaInfo.textContent = error.message;
      } finally {
        refreshButton.disabled = false;
      }
    }

    // ---- Model download ----
    function showPull(state) {
      pullProgress.hidden = false;
      const percent = state.total ? Math.round((state.completed / state.total) * 100) : 0;
      pullBar.style.width = `${percent}%`;

      if (state.error) {
        pullBar.classList.add('bg-danger');
        pullText.textContent = `Download of ${state.model} failed: ${state.error}`;
      } else if (state.done) {
        pullBar.classList.remove('bg-danger');
        pullBar.style.width = '100%';
        pullText.textContent = `${state.model} is downloaded and ready to use.`;
      } else {
        pullBar.classList.remove('bg-danger');
        pullText.textContent = state.total
          ? `Downloading ${state.model}… ${percent}% (${formatGb(state.completed)} of ${formatGb(state.total)})`
          : `Downloading ${state.model}… ${state.status}`;
      }
    }

    async function pollPull(initial = false) {
      clearTimeout(pullTimer);
      try {
        const state = await request('/assistant/ollama/pull');
        if (!state.model || (initial && !state.running)) return;
        showPull(state);

        if (state.running) {
          pullTimer = setTimeout(pollPull, 1000);
        } else {
          pullCustomButton.disabled = false;
          if (state.done && !state.error) {
            await loadModels();
            ollamaModel.value = state.model;
            setStatus(`${state.model} downloaded. Click Save to use it.`, 'success');
          }
        }
      } catch (error) {
        pullText.textContent = error.message;
        pullCustomButton.disabled = false;
      }
    }

    async function pullModel(name) {
      name = name.trim();
      if (!name) {
        setStatus('Enter a model name to download.', 'danger');
        return;
      }
      pullCustomButton.disabled = true;
      setStatus('');
      try {
        await saveOllamaUrlIfChanged();
        showPull(await request('/assistant/ollama/pull', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ model: name }),
        }));
        pollPull();
      } catch (error) {
        pullCustomButton.disabled = false;
        setStatus(error.message, 'danger');
      }
    }

    // ---- Load / save ----
    function fillForm(settings) {
      saved = settings;
      providerOllama.checked = settings.provider === 'ollama';
      providerApi.checked = settings.provider === 'api';
      ollamaUrl.value = settings.ollama_url;
      apiUrl.value = settings.api_url;
      apiModel.value = settings.api_model;
      apiKey.value = '';
      apiKey.placeholder = settings.api_key_set ? 'Saved (leave empty to keep it)' : 'Paste your API key';
      apiKeyClearWrap.hidden = !settings.api_key_set;
      apiKeyClear.checked = false;
      matchPreset();
      showProvider();
      updateBadge();
    }

    async function saveOllamaUrlIfChanged() {
      const url = ollamaUrl.value.trim();
      if (saved && url && url.replace(/\/+$/, '') !== saved.ollama_url) {
        fillForm(await request('/assistant/settings', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ollama_url: url }),
        }));
      }
    }

    async function save() {
      const body = {
        provider: selectedProvider(),
        ollama_url: ollamaUrl.value.trim(),
        api_url: apiUrl.value.trim(),
        api_model: apiModel.value.trim(),
      };
      if (ollamaModel.value) body.ollama_model = ollamaModel.value;
      if (apiKeyClear.checked) body.api_key = '';
      else if (apiKey.value.trim()) body.api_key = apiKey.value.trim();

      saveButton.disabled = true;
      try {
        const urlChanged = saved && body.ollama_url.replace(/\/+$/, '') !== saved.ollama_url;
        fillForm(await request('/assistant/settings', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        }));
        setStatus('Saved.', 'success');
        if (urlChanged) loadModels();
      } catch (error) {
        setStatus(error.message, 'danger');
      } finally {
        saveButton.disabled = false;
      }
    }

    async function test() {
      testButton.disabled = true;
      setStatus('Testing… the first answer from a local model can take a minute.');
      try {
        const data = await request('/assistant/test', { method: 'POST' });
        setStatus(`It works: ${data.model} answered "${data.answer.slice(0, 60)}".`, 'success');
      } catch (error) {
        setStatus(error.message, 'danger');
      } finally {
        testButton.disabled = false;
      }
    }

    providerOllama.addEventListener('change', showProvider);
    providerApi.addEventListener('change', showProvider);
    refreshButton.addEventListener('click', async () => {
      try {
        await saveOllamaUrlIfChanged();
      } catch (error) {
        setStatus(error.message, 'danger');
        return;
      }
      loadModels();
    });
    pullCustomButton.addEventListener('click', () => pullModel(customModel.value));
    customModel.addEventListener('keydown', event => {
      if (event.key === 'Enter') {
        event.preventDefault();
        pullModel(customModel.value);
      }
    });
    saveButton.addEventListener('click', save);
    testButton.addEventListener('click', test);

    request('/assistant/settings')
      .then(settings => {
        fillForm(settings);
        loadModels();
        pollPull(true);  // shows a download that is still running after a page reload
      })
      .catch(error => setStatus(`Could not load the assistant settings: ${error.message}`, 'danger'));
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeAssistantSettings, { once: true });
  } else {
    initializeAssistantSettings();
  }
})();
