() => {
  if (window.__crChatInitialized) return;
  window.__crChatInitialized = true;
  // Gradio's waveform replaces blob URLs with uploaded URLs and cancels the old preview.
  // Handle only that expected cancellation; ASR and unrelated errors remain visible.
  window.addEventListener('unhandledrejection', event => {
    const reason = event.reason;
    if (reason?.name === 'AbortError' && /\/assets\/StaticAudio-/.test(reason.stack || '')) {
      event.preventDefault();
    }
  });
  // Only new business answers move the viewport. Expanding evidence, filtering,
  // and updating a task keep the same result ID and preserve reading position.
  let lastResult = null;
  let scheduled = false;
  const followResult = () => {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => {
      scheduled = false;
      const header = document.querySelector('.cr-result-header[data-result-id]');
      if (header && header.dataset.resultId !== lastResult) {
        lastResult = header.dataset.resultId;
        header.scrollIntoView({block:'start', behavior:'instant'});
      }
    });
  };
  try { new MutationObserver(followResult).observe(document.body, {childList:true, subtree:true}); } catch (_) {}
  const key = 'compliance-radar-intro-v1';
  let played = true;
  try { played = sessionStorage.getItem(key) === 'played'; sessionStorage.setItem(key, 'played'); } catch (_) {}
  const finish = () => document.querySelectorAll('.cr-intro').forEach(node => {
    node.classList.remove('cr-play'); node.setAttribute('aria-hidden', 'true');
  });
  let attempts = 0;
  const setup = () => {
    const intro = document.querySelector('.cr-intro');
    if (!intro && attempts++ < 30) { setTimeout(setup, 100); return; }
    if (!intro) return;
    if (!played && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      intro.classList.add('cr-play'); intro.setAttribute('aria-hidden', 'false');
    }
    const skip = intro.querySelector('button');
    if (skip) skip.addEventListener('click', finish);
    document.addEventListener('focusin', e => { if (e.target.closest('#cr-input')) finish(); });
    document.addEventListener('input', finish, {once:true});
    document.addEventListener('keydown', e => { if (e.key === 'Escape') finish(); });
    setTimeout(finish, 1850);
  };
  setup();

  // Presentation only: preserve Gradio components and their original handlers.
  const panelIds = ['cr-discover','cr-settings','cr-result-filter','cr-history',
    'cr-export-panel','cr-voice','cr-coverage','cr-tutorial'];
  let openPanel = null;
  let panelOperation = null;
  const closePanels = () => {
    panelIds.forEach(id => document.getElementById(id)?.classList.remove('cr-pop-open'));
    document.querySelectorAll('[data-cr-panel]').forEach(b => b.setAttribute('aria-pressed','false'));
    openPanel = null;
  };
  const wirePanels = () => {
    panelIds.forEach(id => document.getElementById(id)?.classList.add('cr-popover'));
    const composer = document.getElementById('cr-composer');
    if (composer) document.documentElement.style.setProperty('--cr-dock-height', `${composer.getBoundingClientRect().height}px`);
    const hasResult = !!document.querySelector('.cr-result-header');
    document.body.classList.toggle('cr-has-result', hasResult);
    document.querySelectorAll('[data-cr-panel]').forEach(button => {
      const panel = document.getElementById(button.dataset.crPanel);
      const unavailable = !panel || panel.classList.contains('hidden');
      button.disabled = unavailable;
      button.title = unavailable ? '请先生成一份查询结果' : button.textContent.trim();
    });
  };
  document.addEventListener('click', event => {
    const toggle = event.target.closest('[data-cr-panel]');
    if (toggle) {
      const id = toggle.dataset.crPanel;
      const wasOpen = openPanel === id;
      closePanels();
      if (!wasOpen) {
        const panel = document.getElementById(id);
        if (!panel) return;
        panel.classList.add('cr-pop-open');
        panel.setAttribute('role','region');
        const heading = panel.querySelector(':scope > button');
        const contents = heading?.nextElementSibling;
        if (heading && (heading.getAttribute('aria-expanded') === 'false' ||
            (contents && getComputedStyle(contents).display === 'none'))) heading.click();
        toggle.setAttribute('aria-pressed','true');
        openPanel = id;
      }
      return;
    }
    if (event.target.closest('[data-cr-reset]')) {
      document.querySelector('#cr-reset')?.click(); closePanels(); return;
    }
    if (event.target.closest('#cr-send')) { closePanels(); return; }
    const operation = event.target.closest('.cr-popover button');
    if (operation && openPanel && !operation.matches('.label-wrap')) panelOperation = openPanel;
    if (!event.target.closest('.cr-popover') && !event.target.closest('#cr-actionbar')) closePanels();
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') closePanels();
  });
  // Close completed operation panels only after their output really changes.
  let lastStatus = document.querySelector('#cr-status')?.textContent || '';
  let lastClause = '';
  const updatePresentation = () => {
    wirePanels();
    const status = document.querySelector('#cr-status')?.textContent || '';
    const clause = document.querySelector('#cr-clause-result')?.textContent || '';
    if (status !== lastStatus && status.trim() && panelOperation === openPanel &&
        ['cr-settings','cr-history','cr-voice'].includes(openPanel)) {
      panelOperation = null; closePanels();
    }
    if (clause !== lastClause && clause.trim() && openPanel === 'cr-coverage') {
      // Keep retrieved clauses readable; close explicitly with the same toggle/Escape.
    }
    lastStatus = status; lastClause = clause;
  };
  let pendingLayout = false;
  new MutationObserver(() => {
    if (pendingLayout) return;
    pendingLayout = true;
    requestAnimationFrame(() => { pendingLayout = false; updatePresentation(); });
  }).observe(document.body, {childList:true,subtree:true,characterData:true});
  window.addEventListener('resize', wirePanels);
  wirePanels();
}
