// src/frontend/core/ui.js
// Standard shared UI components, toasts, modal confirmations, pagination, and error renders

export function notify(message, { kind = 'info', duration = 3500 } = {}) {
  let toastContainer = document.getElementById('toastContainer');
  if (!toastContainer) {
    toastContainer = document.createElement('div');
    toastContainer.id = 'toastContainer';
    toastContainer.className = 'toast-container';
    document.body.appendChild(toastContainer);
  }

  const toast = document.createElement('div');
  toast.className = `toast toast-${kind}`;
  toast.setAttribute('role', 'alert');
  toast.textContent = message;

  toastContainer.appendChild(toast);

  setTimeout(() => {
    toast.classList.add('toast-fading');
    setTimeout(() => {
      if (toast.parentNode) {
        toast.parentNode.removeChild(toast);
      }
    }, 300);
  }, duration);
}

export function confirmAction(options = {}) {
  const opts = typeof options === 'string' ? { message: options } : (options || {});
  const { title = 'Confirm Action', message, confirmLabel = 'Confirm', destructive = false } = opts;
  return new Promise((resolve) => {
    const previousActiveElement = document.activeElement;

    const backdrop = document.createElement('div');
    backdrop.className = 'dialog-backdrop';

    const dialog = document.createElement('div');
    dialog.className = 'dialog';
    dialog.setAttribute('role', 'dialog');
    dialog.setAttribute('aria-modal', 'true');
    dialog.setAttribute('aria-label', title);

    const h3 = document.createElement('h3');
    h3.textContent = title;
    dialog.appendChild(h3);

    const p = document.createElement('p');
    p.textContent = message;
    dialog.appendChild(p);

    const actions = document.createElement('div');
    actions.className = 'dialog-actions';

    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'btn btn-secondary';
    cancelBtn.textContent = 'Cancel';
    cancelBtn.type = 'button';

    const confirmBtn = document.createElement('button');
    confirmBtn.className = destructive ? 'btn btn-danger' : 'btn btn-primary';
    confirmBtn.textContent = confirmLabel;
    confirmBtn.type = 'button';

    actions.appendChild(cancelBtn);
    actions.appendChild(confirmBtn);
    dialog.appendChild(actions);
    backdrop.appendChild(dialog);
    document.body.appendChild(backdrop);

    confirmBtn.focus();

    function cleanup(result) {
      if (backdrop.parentNode) {
        document.body.removeChild(backdrop);
      }
      if (previousActiveElement && typeof previousActiveElement.focus === 'function') {
        try {
          previousActiveElement.focus();
        } catch (_) {}
      }
      resolve(result);
    }

    cancelBtn.addEventListener('click', () => cleanup(false));
    confirmBtn.addEventListener('click', () => cleanup(true));
    backdrop.addEventListener('click', (e) => {
      if (e.target === backdrop) cleanup(false);
    });

    // Keyboard navigation: Escape to cancel, Tab loop for focus trapping
    dialog.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        cleanup(false);
      } else if (e.key === 'Tab') {
        const focusable = [cancelBtn, confirmBtn];
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    });
  });
}

export function renderPagination(container, { page = 1, pageSize = 20, total = 0, onChange, hasMore } = {}) {
  container.innerHTML = '';
  const totalPages = Math.ceil(total / pageSize) || 1;
  const isSinglePage = totalPages <= 1 && (hasMore === undefined || !hasMore);
  if (isSinglePage) return;

  const wrapper = document.createElement('nav');
  wrapper.className = 'pagination';
  wrapper.setAttribute('aria-label', 'Pagination Navigation');

  const prevBtn = document.createElement('button');
  prevBtn.className = 'page-btn';
  prevBtn.textContent = '← Previous';
  prevBtn.setAttribute('aria-label', 'Previous Page');
  prevBtn.disabled = page <= 1;
  prevBtn.onclick = () => onChange && onChange(page - 1);
  wrapper.appendChild(prevBtn);

  const info = document.createElement('span');
  info.className = 'page-info';
  const totalDisplay = total > 0 ? ` of ${totalPages} (${total} items)` : '';
  info.textContent = `Page ${page}${totalDisplay}`;
  wrapper.appendChild(info);

  const nextBtn = document.createElement('button');
  nextBtn.className = 'page-btn';
  nextBtn.textContent = 'Next →';
  nextBtn.setAttribute('aria-label', 'Next Page');
  nextBtn.disabled = hasMore !== undefined ? !hasMore : page >= totalPages;
  nextBtn.onclick = () => onChange && onChange(page + 1);
  wrapper.appendChild(nextBtn);

  container.appendChild(wrapper);
}

export function renderError(container, error, { onRetry } = {}) {
  container.innerHTML = '';
  const div = document.createElement('div');
  div.className = 'notice notice-error';

  const title = document.createElement('h3');
  title.textContent = 'Something went wrong';
  div.appendChild(title);

  const p = document.createElement('p');
  p.textContent = error && error.message ? error.message : String(error);
  div.appendChild(p);

  if (onRetry) {
    const retryBtn = document.createElement('button');
    retryBtn.className = 'btn btn-secondary';
    retryBtn.textContent = 'Try Again';
    retryBtn.onclick = onRetry;
    div.appendChild(retryBtn);
  }

  container.appendChild(div);
}

export function renderEmpty(container, { title = 'No results found', description = 'There is nothing to display here.', action } = {}) {
  container.innerHTML = '';
  const div = document.createElement('div');
  div.className = 'empty-state';

  const h3 = document.createElement('h3');
  h3.textContent = title;
  div.appendChild(h3);

  const p = document.createElement('p');
  p.textContent = description;
  div.appendChild(p);

  if (action) {
    const btn = document.createElement('button');
    btn.className = 'btn btn-primary';
    btn.textContent = action.label;
    btn.onclick = action.onClick;
    div.appendChild(btn);
  }

  container.appendChild(div);
}
