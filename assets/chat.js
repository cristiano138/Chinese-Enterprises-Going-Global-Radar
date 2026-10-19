() => {
  if (window.__crChatInitialized) return;
  window.__crChatInitialized = true;
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
}
