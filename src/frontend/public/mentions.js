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

  function selectUser(user) {
    if (matchStartIndex < 0) return;
    const text = textarea.value;
    const before = text.slice(0, matchStartIndex);
    const after = text.slice(textarea.selectionEnd);
    const insertText = `@${user.username} `;
    
    textarea.value = before + insertText + after;
    const newCursorPos = before.length + insertText.length;
    textarea.selectionStart = newCursorPos;
    textarea.selectionEnd = newCursorPos;
    textarea.focus();

    // Trigger input event for any validation listeners
    textarea.dispatchEvent(new Event('input', { bubbles: true }));

    hidePopup();
  }

  async function checkMentionsQuery() {
    const cursorPos = textarea.selectionStart;
    const textBeforeCursor = textarea.value.slice(0, cursorPos);

    // Look for @username query pattern before cursor
    const match = textBeforeCursor.match(/@([a-z0-9_]{2,30})$/i);
    if (!match) {
      hidePopup();
      return;
    }

    activeQuery = match[1];
    matchStartIndex = cursorPos - match[0].length;

    try {
      const users = await api('/users/mentions', {
        query: { q: activeQuery, page: 1, page_size: 5 },
      });

      if (!Array.isArray(users) || users.length === 0) {
        hidePopup();
        return;
      }

      currentMatches = users;
      selectedIndex = 0;
      renderMatches();
    } catch (err) {
      // Mentions lookup requires authentication or may fail gracefully
      hidePopup();
    }
  }

  function onInput() {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(checkMentionsQuery, 150);
  }

  function onKeyDown(e) {
    if (!popupEl || popupEl.style.display === 'none' || currentMatches.length === 0) {
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
  textarea.addEventListener('keydown', onKeyDown);
  textarea.addEventListener('blur', onBlur);

  return function cleanup() {
    clearTimeout(debounceTimer);
    textarea.removeEventListener('input', onInput);
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
