// "Ask Wally" chat panel: a floating button that opens a chat about the user's spending.
(() => {
  const API_URL = '/api';
  const STORAGE_KEY = 'wally-assistant-history';
  const MAX_STORED = 30;
  const HISTORY_SENT = 6;
  const SUGGESTIONS = [
    'How much did I spend on food this month?',
    'Which budget is closest to its limit?',
    'How much do my subscriptions cost per month?',
  ];

  const STYLE = `
    .wa-button {
      position: fixed; right: 20px; bottom: 20px; z-index: 1040;
      display: inline-flex; align-items: center; gap: 0.4rem;
      border: none; border-radius: 999px; padding: 0.65rem 1rem;
      background: var(--bs-primary, #0d6efd); color: #fff; font-weight: 500;
      box-shadow: 0 4px 14px rgba(0, 0, 0, 0.2); cursor: pointer;
    }
    .wa-panel {
      position: fixed; right: 20px; bottom: 76px; z-index: 1045;
      width: 380px; max-width: calc(100vw - 32px); height: 520px; max-height: calc(100vh - 110px);
      display: flex; flex-direction: column;
      background: var(--bs-body-bg, #fff); color: var(--bs-body-color, #212529);
      border: 1px solid var(--bs-border-color, #dee2e6); border-radius: 12px;
      box-shadow: 0 8px 28px rgba(0, 0, 0, 0.22); overflow: hidden;
    }
    .wa-panel[hidden] { display: none; }
    .wa-header {
      display: flex; align-items: center; gap: 0.5rem; padding: 0.7rem 0.9rem;
      border-bottom: 1px solid var(--bs-border-color, #dee2e6);
    }
    .wa-title { font-weight: 600; }
    .wa-model { font-size: 0.75rem; color: var(--bs-secondary-color, #6c757d); }
    .wa-header .btn-close { margin-left: auto; }
    .wa-messages { flex: 1; overflow-y: auto; padding: 0.9rem; display: flex; flex-direction: column; gap: 0.6rem; }
    .wa-message { max-width: 85%; padding: 0.5rem 0.75rem; border-radius: 12px; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 0.92rem; }
    .wa-user { align-self: flex-end; background: var(--bs-primary, #0d6efd); color: #fff; }
    .wa-assistant { align-self: flex-start; background: var(--bs-tertiary-bg, #f1f3f5); }
    .wa-error { align-self: stretch; max-width: 100%; background: var(--bs-warning-bg-subtle, #fff3cd); color: var(--bs-warning-text-emphasis, #664d03); }
    .wa-thinking { align-self: flex-start; font-size: 0.85rem; color: var(--bs-secondary-color, #6c757d); }
    .wa-intro { font-size: 0.9rem; color: var(--bs-secondary-color, #6c757d); }
    .wa-suggestion {
      display: block; width: 100%; text-align: left; margin-top: 0.4rem; font-size: 0.88rem;
      border: 1px solid var(--bs-border-color, #dee2e6); border-radius: 8px; padding: 0.4rem 0.6rem;
      background: transparent; color: inherit; cursor: pointer;
    }
    .wa-form { display: flex; gap: 0.5rem; padding: 0.7rem; border-top: 1px solid var(--bs-border-color, #dee2e6); }
    .wa-form input { flex: 1; }
    .wa-footer { display: flex; justify-content: space-between; padding: 0 0.8rem 0.5rem; font-size: 0.75rem; }
    .wa-footer a, .wa-footer button { color: var(--bs-secondary-color, #6c757d); }
    .wa-footer button { border: none; background: none; padding: 0; text-decoration: underline; cursor: pointer; }
    @media (max-width: 576px) {
      .wa-panel { right: 8px; left: 8px; width: auto; max-width: none; bottom: 72px; }
      .wa-button { right: 12px; bottom: 12px; }
    }
  `;

  const ICON = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>';

  let history = loadHistory();
  let busy = false;

  function loadHistory() {
    try {
      const saved = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || '[]');
      return Array.isArray(saved) ? saved : [];
    } catch {
      return [];
    }
  }

  function saveHistory() {
    history = history.slice(-MAX_STORED);
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(history));
    } catch {
      // Storage can be unavailable (private mode); the chat still works for this page.
    }
  }

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function build() {
    const style = element('style');
    style.textContent = STYLE;
    document.head.appendChild(style);

    const button = element('button', 'wa-button');
    button.type = 'button';
    button.setAttribute('aria-expanded', 'false');
    button.setAttribute('aria-controls', 'waPanel');
    button.innerHTML = `${ICON}<span>Ask Wally</span>`;

    const panel = element('section', 'wa-panel');
    panel.id = 'waPanel';
    panel.hidden = true;
    panel.setAttribute('aria-label', 'Ask Wally assistant');

    const header = element('div', 'wa-header');
    const titles = element('div');
    titles.append(element('div', 'wa-title', 'Ask Wally'));
    const model = element('div', 'wa-model', 'Answers use only your Wally data');
    titles.append(model);
    const close = element('button', 'btn-close');
    close.type = 'button';
    close.setAttribute('aria-label', 'Close');
    header.append(titles, close);

    const messages = element('div', 'wa-messages');
    messages.setAttribute('aria-live', 'polite');

    const form = element('form', 'wa-form');
    const input = element('input', 'form-control form-control-sm');
    input.type = 'text';
    input.maxLength = 500;
    input.placeholder = 'Ask about your spending…';
    input.setAttribute('aria-label', 'Your question');
    const send = element('button', 'btn btn-sm btn-primary', 'Send');
    send.type = 'submit';
    form.append(input, send);

    const footer = element('div', 'wa-footer');
    const clear = element('button', '', 'Clear chat');
    clear.type = 'button';
    const settingsLink = element('a', '', 'Assistant settings');
    settingsLink.href = '/settings#assistantSettings';
    footer.append(clear, settingsLink);

    panel.append(header, messages, form, footer);
    document.body.append(button, panel);

    function render(pending) {
      messages.replaceChildren();

      if (history.length === 0) {
        messages.append(element('div', 'wa-intro', 'Ask a question about your spending, budgets or subscriptions. For example:'));
        SUGGESTIONS.forEach(text => {
          const suggestion = element('button', 'wa-suggestion', text);
          suggestion.type = 'button';
          suggestion.addEventListener('click', () => ask(text));
          messages.append(suggestion);
        });
      }

      history.forEach(item => {
        const className = item.error ? 'wa-error' : item.role === 'user' ? 'wa-user' : 'wa-assistant';
        messages.append(element('div', `wa-message ${className}`, item.content));
      });

      if (pending) messages.append(element('div', 'wa-thinking', 'Thinking…'));
      messages.scrollTop = messages.scrollHeight;
    }

    async function ask(question) {
      question = question.trim();
      if (!question || busy) return;

      // Only real answers are sent back as context, not error messages.
      const previous = history.filter(item => !item.error).slice(-HISTORY_SENT)
        .map(({ role, content }) => ({ role, content }));

      history.push({ role: 'user', content: question });
      saveHistory();
      busy = true;
      send.disabled = true;
      input.value = '';
      render(true);

      try {
        const response = await fetch(`${API_URL}/assistant`, {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ question, history: previous }),
        });
        const data = await response.json().catch(() => null);

        if (response.ok) {
          history.push({ role: 'assistant', content: data.answer });
          model.textContent = `Model: ${data.model}`;
        } else if (response.status === 401) {
          history.push({ role: 'assistant', error: true, content: 'Please sign in again to use the assistant.' });
        } else {
          const detail = typeof data?.detail === 'string'
            ? data.detail
            : 'The AI assistant is not available right now. Please try again later.';
          history.push({ role: 'assistant', error: true, content: detail });
        }
      } catch {
        history.push({ role: 'assistant', error: true, content: 'The AI assistant is not available right now. Check your connection and try again.' });
      } finally {
        busy = false;
        send.disabled = false;
        saveHistory();
        render(false);
        input.focus();
      }
    }

    function toggle(open) {
      panel.hidden = !open;
      button.setAttribute('aria-expanded', String(open));
      if (open) {
        render(busy);
        input.focus();
      }
    }

    button.addEventListener('click', () => toggle(panel.hidden));
    close.addEventListener('click', () => toggle(false));
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && !panel.hidden) toggle(false);
    });
    form.addEventListener('submit', event => {
      event.preventDefault();
      ask(input.value);
    });
    clear.addEventListener('click', () => {
      history = [];
      saveHistory();
      render(false);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', build, { once: true });
  } else {
    build();
  }
})();
