// src/frontend/core/math.js
// Self-hosted KaTeX Math Renderer with strict trust: false XSS protection

const KATEX_DELIMITERS = [
  { left: '$$', right: '$$', display: true },
  { left: '\\[', right: '\\]', display: true },
  { left: '\\(', right: '\\)', display: false },
];

const IGNORED_TAGS = ['script', 'noscript', 'style', 'textarea', 'pre', 'code', 'option'];

function invokeKatexRender(container) {
  if (!container || !container.isConnected) return;
  if (typeof window === 'undefined') return;

  if (typeof window.renderMathInElement === 'function') {
    window.renderMathInElement(container, {
      delimiters: KATEX_DELIMITERS,
      ignoredTags: IGNORED_TAGS,
      throwOnError: false,
      strict: 'ignore',
      trust: false,
    });
    return;
  }

  if (window.katex && typeof window.katex.render === 'function') {
    container.querySelectorAll('.math-display, .math-inline').forEach((el) => {
      const isDisplay = el.classList.contains('math-display');
      let tex = (el.textContent || '').trim();
      if (isDisplay && tex.startsWith('$$') && tex.endsWith('$$') && tex.length >= 4) {
        tex = tex.slice(2, -2).trim();
      } else if (!isDisplay && tex.startsWith('\\(') && tex.endsWith('\\)') && tex.length >= 4) {
        tex = tex.slice(2, -2).trim();
      }
      if (!tex) return;
      try {
        window.katex.render(tex, el, {
          displayMode: isDisplay,
          throwOnError: false,
          strict: 'ignore',
          trust: false,
        });
      } catch (_) {}
    });
  }
}

export function renderMathInContainer(container) {
  if (!container) return;
  if (typeof window === 'undefined') return;

  if (typeof window.renderMathInElement === 'function' || (window.katex && typeof window.katex.render === 'function')) {
    invokeKatexRender(container);
    return;
  }

  // Handle deferred script loading on initial page load
  let attempts = 0;
  const timer = setInterval(() => {
    attempts += 1;
    if (!container.isConnected || attempts > 40) {
      clearInterval(timer);
      return;
    }
    if (typeof window.renderMathInElement === 'function' || (window.katex && typeof window.katex.render === 'function')) {
      clearInterval(timer);
      invokeKatexRender(container);
    }
  }, 50);
}
