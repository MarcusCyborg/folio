// src/frontend/public/mentions.js
// Accessible @username Autocomplete for Comments and Peer Notes

import { api } from '../core/api.js';

export function attachMentionsAutocomplete(textarea, wrapperElement) {
  let popupEl = null;
  let currentMatches = [];
  let selectedIndex = 0;
  let debounceTimer = null;
  let activeQuery = '';
  let matchStartIndex = -1;
  let currentAbortController = null;
  let requestSequence = 0;

  function createPopup() {
    if (popupEl) return popupEl;
    popupEl = document.createElement('div');
    popupEl.className = 'mentions-autocomplete-popup';
    popupEl.setAttribute('role', 'listbox');
    popupEl.setAttribute('aria-label', 'User mentions');
    popupEl.style.display = 'none';

    // Position relative to wrapperElement or textarea parent
    const parent = wrapperElement || textarea.parentElement;
    if (window.getComputedStyle(parent).position === 'static') {
      parent.style.position = 'relative';
    }
    parent.appendChild(popupEl);
    return popupEl;
  }

  function hidePopup() {
    if (popupEl) {
      popupEl.style.display = 'none';
      popupEl.innerHTML = '';
    }
    currentMatches = [];
    selectedIndex = 0;
    activeQuery = '';
    matchStartIndex = -1;
  }

  function renderMatches() {
    if (!popupEl) createPopup();
    if (currentMatches.length === 0) {
      hidePopup();
      return;
    }

    popupEl.innerHTML = '';
    currentMatches.forEach((user, idx) => {
      const item = document.createElement('div');
      item.className = `mention-autocomplete-item ${idx === selectedIndex ? 'selected' : ''}`;
      item.setAttribute('role', 'option');
      item.setAttribute('aria-selected', idx === selectedIndex ? 'true' : 'false');
      item.innerHTML = `
        <span class="mention-item-handle">@${escapeText(user.username)}</span>
        <span class="mention-item-name">${escapeText(user.display_name)}</span>
      `;

      item.onmousedown = (e) => {
        e.preventDefault(); // Prevent textarea blur
        selectUser(user);
      };

      popupEl.appendChild(item);
    });

    popupEl.style.display = 'block';
  }

  function getLiveMentionContext() {
    const cursorPos = textarea.selectionStart;
    if (typeof cursorPos !== 'number' || textarea.selectionEnd !== cursorPos) {
      return null;
    }
    const textBeforeCursor = textarea.value.slice(0, cursorPos);
    const match = textBeforeCursor.match(/@([a-z0-9_]{2,30})$/i);
    if (!match) {
      return null;
    }
    return {
      query: match[1],
      startIndex: cursorPos - match[0].length,
      cursorPos,
    };
  }

  function selectUser(user) {
    const live = getLiveMentionContext();
    if (!live || live.query !== activeQuery || live.startIndex !== matchStartIndex) {
      hidePopup();
      return;
    }
    const text = textarea.value;
    const before = text.slice(0, live.startIndex);
    const after = text.slice(textarea.selectionEnd);
    const insertText = `@${user.username} `;
    
    textarea.value = before + insertText + after;
    const newCursorPos = before.length + insertText.length;
    textarea.selectionStart = newCursorPos;
    textarea.selectionEnd = newCursorPos;
    textarea.focus();

    hidePopup();

    // Trigger input event for any validation listeners
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
  }

  async function checkMentionsQuery(expectedSeq) {
    const live = getLiveMentionContext();
    if (!live) {
      hidePopup();
      return;
    }

    activeQuery = live.query;
    matchStartIndex = live.startIndex;
    const querySnapshot = activeQuery;
    const startSnapshot = matchStartIndex;
    const seq = expectedSeq || ++requestSequence;

    if (currentAbortController) {
      currentAbortController.abort();
    }
    currentAbortController = new AbortController();

    try {
      const users = await api('/users/mentions', {
        query: { q: querySnapshot, page: 1, page_size: 5 },
        signal: currentAbortController.signal,
      });

      const currentLive = getLiveMentionContext();
      if (
        seq !== requestSequence ||
        !currentLive ||
        currentLive.query !== querySnapshot ||
        currentLive.startIndex !== startSnapshot
      ) {
        hidePopup();
        return;
      }

      if (!Array.isArray(users) || users.length === 0) {
        hidePopup();
        return;
      }

      activeQuery = querySnapshot;
      matchStartIndex = startSnapshot;
      currentMatches = users;
      selectedIndex = 0;
      renderMatches();
    } catch (err) {
      if (err.name === 'AbortError') return;
      if (seq === requestSequence) {
        hidePopup();
      }
    }
  }

  function onInput() {
    clearTimeout(debounceTimer);
    const seq = ++requestSequence;
    if (currentAbortController) {
      currentAbortController.abort();
      currentAbortController = null;
    }

    const live = getLiveMentionContext();
    if (!live) {
      hidePopup();
      return;
    }
    if (live.query !== activeQuery || live.startIndex !== matchStartIndex) {
      hidePopup();
    }

    debounceTimer = setTimeout(() => {
      checkMentionsQuery(seq);
    }, 150);
  }

  function onCursorSync() {
    if (!popupEl || popupEl.style.display === 'none') return;
    const live = getLiveMentionContext();
    if (!live || live.query !== activeQuery || live.startIndex !== matchStartIndex) {
      hidePopup();
    }
  }

  function onKeyDown(e) {
    if (!popupEl || popupEl.style.display === 'none' || currentMatches.length === 0) {
      return;
    }

    const live = getLiveMentionContext();
    if (!live || live.query !== activeQuery || live.startIndex !== matchStartIndex) {
      hidePopup();
      return;
    }

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      selectedIndex = (selectedIndex + 1) % currentMatches.length;
      renderMatches();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      selectedIndex = (selectedIndex - 1 + currentMatches.length) % currentMatches.length;
      renderMatches();
    } else if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault();
      if (currentMatches[selectedIndex]) {
        selectUser(currentMatches[selectedIndex]);
      }
    } else if (e.key === 'Escape') {
      e.preventDefault();
      hidePopup();
    }
  }

  function onBlur() {
    // Delay hiding so mousedown on item can execute
    setTimeout(hidePopup, 200);
  }

  textarea.addEventListener('input', onInput);
  textarea.addEventListener('keyup', onCursorSync);
  textarea.addEventListener('click', onCursorSync);
  textarea.addEventListener('keydown', onKeyDown);
  textarea.addEventListener('blur', onBlur);

  return function cleanup() {
    clearTimeout(debounceTimer);
    if (currentAbortController) currentAbortController.abort();
    textarea.removeEventListener('input', onInput);
    textarea.removeEventListener('keyup', onCursorSync);
    textarea.removeEventListener('click', onCursorSync);
    textarea.removeEventListener('keydown', onKeyDown);
    textarea.removeEventListener('blur', onBlur);
    if (popupEl && popupEl.parentNode) {
      popupEl.parentNode.removeChild(popupEl);
    }
  };
}

function escapeText(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}
