// src/frontend/public/auth_views.js
// Sign In, Public Registration, and Scholar Profile Management views

import { api } from '../core/api.js';
import { getSession, refreshSession } from '../core/session.js';
import { navigate } from '../core/router.js';
import { notify } from '../core/ui.js';

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const USERNAME_REGEX = /^[a-z0-9_]{3,30}$/;

export async function renderLogin(container, routeContext) {
  const { query } = routeContext;
  const nextPath = query.get('next') || '/library';

  document.title = 'Sign In — Folio';

  container.innerHTML = `
    <div class="public-page" style="max-width: 440px; margin: 2.5rem auto;">
      <div class="auth-card">
        <h2 class="auth-title">Welcome to Folio</h2>
        <p class="auth-subtitle">Sign in to access your scholar library account</p>

        <form id="loginForm" class="auth-form" novalidate>
          <div class="field">
            <label class="label" for="loginEmail">Email Address</label>
            <input class="input" type="email" id="loginEmail" placeholder="reader@folio.test" required autocomplete="email" aria-describedby="loginEmailError" />
            <span class="field-error-text" id="loginEmailError" style="display: none;" role="alert"></span>
          </div>

          <div class="field">
            <label class="label" for="loginPassword">Password</label>
            <input class="input" type="password" id="loginPassword" placeholder="••••••••" required autocomplete="current-password" aria-describedby="loginPasswordError" />
            <span class="field-error-text" id="loginPasswordError" style="display: none;" role="alert"></span>
          </div>

          <div id="loginError" class="notice notice-error" style="display: none; margin-bottom: 1.25rem;"></div>

          <button type="submit" class="btn btn-primary" id="loginSubmitBtn" style="width: 100%;">Sign In</button>
        </form>

        <div class="auth-footer-links">
          <span>Need an account? <a href="#/register">Join Folio</a></span>
          <hr style="border: none; border-top: 1px solid var(--color-border); margin: 1.25rem 0;" />
          <div style="font-size: 0.8rem; color: var(--color-muted); line-height: 1.6;">
            <strong>Local Demonstration Accounts:</strong><br />
            <code>admin@folio.test</code> (Super Admin)<br />
            <code>content@folio.test</code> (Content Manager)<br />
            <code>moderator@folio.test</code> (Moderator)<br />
            <code>seo@folio.test</code> (Data & SEO Specialist)<br />
            <code>reader@folio.test</code> (Reader)<br />
            Password: <code>FolioDemo2026!</code>
          </div>
        </div>
      </div>
    </div>
  `;

  const form = container.querySelector('#loginForm');
  const emailInput = container.querySelector('#loginEmail');
  const passwordInput = container.querySelector('#loginPassword');
  const emailError = container.querySelector('#loginEmailError');
  const passwordError = container.querySelector('#loginPasswordError');
  const errorBox = container.querySelector('#loginError');
  const submitBtn = container.querySelector('#loginSubmitBtn');

  emailInput.oninput = () => {
    emailError.style.display = 'none';
    emailInput.classList.remove('input-error');
  };
  passwordInput.oninput = () => {
    passwordError.style.display = 'none';
    passwordInput.classList.remove('input-error');
  };

  form.onsubmit = async (e) => {
    e.preventDefault();
    errorBox.style.display = 'none';
    emailError.style.display = 'none';
    passwordError.style.display = 'none';
    emailInput.classList.remove('input-error');
    passwordInput.classList.remove('input-error');

    const email = emailInput.value.trim();
    const password = passwordInput.value;

    let hasClientError = false;
    if (!email) {
      emailError.textContent = 'Email address is required.';
      emailError.style.display = 'block';
      emailInput.classList.add('input-error');
      hasClientError = true;
    } else if (!EMAIL_REGEX.test(email)) {
      emailError.textContent = 'Please enter a valid email address.';
      emailError.style.display = 'block';
      emailInput.classList.add('input-error');
      hasClientError = true;
    }

    if (!password) {
      passwordError.textContent = 'Password is required.';
      passwordError.style.display = 'block';
      passwordInput.classList.add('input-error');
      hasClientError = true;
    }

    if (hasClientError) return;

    submitBtn.disabled = true;
    submitBtn.textContent = 'Signing in...';

    try {
      await api('/auth/login', {
        method: 'POST',
        body: { email, password },
      });
      await refreshSession();
      notify('Signed in successfully.', { kind: 'success' });

      // Safe internal hash navigation (prevent open redirects)
      const safeNext = (nextPath.startsWith('/') && !nextPath.startsWith('//') && !nextPath.includes('://'))
        ? nextPath
        : '/library';
      navigate(safeNext);
    } catch (err) {
      errorBox.textContent = err.message || 'Invalid email or password.';
      errorBox.style.display = 'block';

      if (err.fields) {
        if (err.fields.email) {
          emailError.textContent = err.fields.email.join(' ');
          emailError.style.display = 'block';
          emailInput.classList.add('input-error');
        }
        if (err.fields.password) {
          passwordError.textContent = err.fields.password.join(' ');
          passwordError.style.display = 'block';
          passwordInput.classList.add('input-error');
        }
      }

      submitBtn.disabled = false;
      submitBtn.textContent = 'Sign In';
    }
  };

  return function routeCleanup() {
    document.title = 'Folio: Knowledge & Research Library';
  };
}

export async function renderRegister(container, routeContext) {
  document.title = 'Create Account — Folio';

  container.innerHTML = `
    <div class="public-page" style="max-width: 480px; margin: 2.5rem auto;">
      <div class="auth-card">
        <h2 class="auth-title">Join Folio Library</h2>
        <p class="auth-subtitle">Create your personal scholar account</p>

        <div id="regDisabledNotice" class="notice notice-warning" style="display: none; margin-bottom: 1.5rem;">
          <strong>Registration Closed:</strong> Public user registration is currently disabled by administrator.
        </div>

        <form id="registerForm" class="auth-form" novalidate>
          <div class="field">
            <label class="label" for="regEmail">Email Address</label>
            <input class="input" type="email" id="regEmail" placeholder="your.name@institution.edu" required autocomplete="email" aria-describedby="regEmailError" />
            <span class="field-error-text" id="regEmailError" style="display: none;" role="alert"></span>
          </div>

          <div class="field">
            <label class="label" for="regUsername">Username</label>
            <input class="input" type="text" id="regUsername" placeholder="researcher_handle" required autocomplete="username" aria-describedby="regUsernameError" />
            <span style="font-size: 0.75rem; color: var(--color-muted);">3–30 lowercase letters, numbers, or underscores</span>
            <span class="field-error-text" id="regUsernameError" style="display: none;" role="alert"></span>
          </div>

          <div class="field">
            <label class="label" for="regDisplayName">Full Display Name</label>
            <input class="input" type="text" id="regDisplayName" placeholder="Dr. Jane Doe" required autocomplete="name" aria-describedby="regDisplayNameError" />
            <span class="field-error-text" id="regDisplayNameError" style="display: none;" role="alert"></span>
          </div>

          <div class="field">
            <label class="label" for="regPassword">Password</label>
            <input class="input" type="password" id="regPassword" placeholder="••••••••••••" required autocomplete="new-password" aria-describedby="regPasswordError" />
            <span style="font-size: 0.75rem; color: var(--color-muted);">Minimum 10 characters</span>
            <span class="field-error-text" id="regPasswordError" style="display: none;" role="alert"></span>
          </div>

          <div id="registerError" class="notice notice-error" style="display: none; margin-bottom: 1.25rem;"></div>

          <button type="submit" class="btn btn-primary" id="registerSubmitBtn" style="width: 100%;">Create Account</button>
        </form>

        <div class="auth-footer-links">
          <span>Already have an account? <a href="#/login">Sign in</a></span>
        </div>
      </div>
    </div>
  `;

  const form = container.querySelector('#registerForm');
  const emailInput = container.querySelector('#regEmail');
  const usernameInput = container.querySelector('#regUsername');
  const displayInput = container.querySelector('#regDisplayName');
  const passwordInput = container.querySelector('#regPassword');
  const emailError = container.querySelector('#regEmailError');
  const usernameError = container.querySelector('#regUsernameError');
  const displayError = container.querySelector('#regDisplayNameError');
  const passwordError = container.querySelector('#regPasswordError');
  const errorBox = container.querySelector('#registerError');
  const submitBtn = container.querySelector('#registerSubmitBtn');
  const disabledNotice = container.querySelector('#regDisabledNotice');

  function clearErrors() {
    errorBox.style.display = 'none';
    [emailError, usernameError, displayError, passwordError].forEach(el => el.style.display = 'none');
    [emailInput, usernameInput, displayInput, passwordInput].forEach(el => el.classList.remove('input-error'));
  }

  [emailInput, usernameInput, displayInput, passwordInput].forEach(input => {
    input.oninput = clearErrors;
  });

  form.onsubmit = async (e) => {
    e.preventDefault();
    clearErrors();

    const email = emailInput.value.trim();
    const username = usernameInput.value.trim();
    const displayName = displayInput.value.trim();
    const password = passwordInput.value;

    let hasClientError = false;

    if (!email) {
      emailError.textContent = 'Email address is required.';
      emailError.style.display = 'block';
      emailInput.classList.add('input-error');
      hasClientError = true;
    } else if (!EMAIL_REGEX.test(email)) {
      emailError.textContent = 'Please enter a valid email address.';
      emailError.style.display = 'block';
      emailInput.classList.add('input-error');
      hasClientError = true;
    }

    if (!username) {
      usernameError.textContent = 'Username is required.';
      usernameError.style.display = 'block';
      usernameInput.classList.add('input-error');
      hasClientError = true;
    } else if (!USERNAME_REGEX.test(username)) {
      usernameError.textContent = 'Username must be 3–30 lowercase letters, numbers, or underscores.';
      usernameError.style.display = 'block';
      usernameInput.classList.add('input-error');
      hasClientError = true;
    }

    if (!displayName) {
      displayError.textContent = 'Display name is required.';
      displayError.style.display = 'block';
      displayInput.classList.add('input-error');
      hasClientError = true;
    } else if (displayName.length > 80) {
      displayError.textContent = 'Display name cannot exceed 80 characters.';
      displayError.style.display = 'block';
      displayInput.classList.add('input-error');
      hasClientError = true;
    }

    if (!password) {
      passwordError.textContent = 'Password is required.';
      passwordError.style.display = 'block';
      passwordInput.classList.add('input-error');
      hasClientError = true;
    } else if (password.length < 10) {
      passwordError.textContent = 'Password must be at least 10 characters long.';
      passwordError.style.display = 'block';
      passwordInput.classList.add('input-error');
      hasClientError = true;
    }

    if (hasClientError) return;

    submitBtn.disabled = true;
    submitBtn.textContent = 'Creating account...';

    try {
      await api('/auth/register', {
        method: 'POST',
        body: {
          email,
          username,
          display_name: displayName,
          password,
        },
      });
      await refreshSession();
      notify('Account created! Welcome to Folio.', { kind: 'success' });
      navigate('/library');
    } catch (err) {
      errorBox.textContent = err.message || 'Failed to register account.';
      errorBox.style.display = 'block';

      if (err.fields) {
        if (err.fields.email) {
          emailError.textContent = err.fields.email.join(' ');
          emailError.style.display = 'block';
          emailInput.classList.add('input-error');
        }
        if (err.fields.username) {
          usernameError.textContent = err.fields.username.join(' ');
          usernameError.style.display = 'block';
          usernameInput.classList.add('input-error');
        }
        if (err.fields.display_name) {
          displayError.textContent = err.fields.display_name.join(' ');
          displayError.style.display = 'block';
          displayInput.classList.add('input-error');
        }
        if (err.fields.password) {
          passwordError.textContent = err.fields.password.join(' ');
          passwordError.style.display = 'block';
          passwordInput.classList.add('input-error');
        }
      }

      submitBtn.disabled = false;
      submitBtn.textContent = 'Create Account';
    }
  };

  // Check registration_enabled setting asynchronously after submit handler is bound
  try {
    const settings = await api('/settings/public');
    if (settings && settings.registration_enabled === false) {
      disabledNotice.style.display = 'block';
      submitBtn.disabled = true;
      emailInput.disabled = true;
      usernameInput.disabled = true;
      displayInput.disabled = true;
      passwordInput.disabled = true;
    }
  } catch (err) {
    console.warn('Could not check public settings:', err);
  }

  return function routeCleanup() {
    document.title = 'Folio: Knowledge & Research Library';
  };
}

export async function renderProfile(container, routeContext) {
  const session = getSession();
  if (!session.user) {
    navigate('/login?next=/profile');
    return;
  }
  const user = session.user;

  document.title = 'Scholar Profile — Folio';

  const memberSince = new Date(user.created_at).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });

  const permsHtml = (user.permissions || []).map(p =>
    `<span class="badge badge-teal">${escapeText(p)}</span>`
  ).join(' ');

  // Check if commenting privileges are suspended
  const now = new Date();
  const suspensionDate = user.commenting_suspended_until ? new Date(user.commenting_suspended_until) : null;
  const isSuspended = suspensionDate && suspensionDate > now;

  container.innerHTML = `
    <div class="public-page" style="max-width: 680px; margin: 2rem auto;">
      <h2 style="font-family: var(--font-reading); font-size: 1.75rem; margin-bottom: 0.5rem;">Scholar Profile</h2>
      <p style="color: var(--color-muted); margin-bottom: 2rem;">Manage your scholar identity, biographical affiliations, and security credentials</p>

      ${isSuspended ? `
        <div class="notice notice-error" style="margin-bottom: 2rem;">
          <strong>Commenting Privilege Notice:</strong> Your commenting and discussion privileges are currently suspended by a moderator until <strong>${suspensionDate.toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' })}</strong>.
        </div>
      ` : ''}

      <!-- Account Summary Card -->
      <div class="profile-card">
        <h3>Account Overview</h3>
        <div class="profile-meta-grid">
          <div><label class="label">Username</label><span>@${escapeText(user.username)}</span></div>
          <div><label class="label">Email Address</label><span>${escapeText(user.email)}</span></div>
          <div><label class="label">Platform Role</label><span class="role-chip">${escapeText(user.role_key.replace('_', ' '))}</span></div>
          <div><label class="label">Member Since</label><span>${memberSince}</span></div>
        </div>
        ${permsHtml ? `
          <div style="margin-top: 1.25rem;">
            <label class="label">Effective Permissions</label>
            <div style="display: flex; flex-wrap: wrap; gap: 0.35rem; margin-top: 0.35rem;">${permsHtml}</div>
          </div>
        ` : ''}
      </div>

      <!-- Update Display Profile -->
      <div class="profile-card" style="margin-top: 2rem;">
        <h3>Edit Public Details</h3>
        <form id="profileForm">
          <div class="field">
            <label class="label" for="profDisplayName">Display Name</label>
            <input class="input" type="text" id="profDisplayName" value="${escapeAttr(user.display_name)}" maxlength="80" required />
            <span class="field-error-text" id="profDisplayError" style="display: none;"></span>
          </div>
          <div class="field">
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <label class="label" for="profBio">Bio / Academic Affiliation (optional)</label>
              <span id="bioCharCounter" style="font-size: 0.75rem; color: var(--color-muted);">${(user.bio || '').length} / 1000</span>
            </div>
            <textarea class="textarea" id="profBio" rows="3" maxlength="1000" placeholder="Field of research, university, or scholarship interests...">${escapeText(user.bio || '')}</textarea>
          </div>
          <div id="profileErrorNotice" class="notice notice-error" style="display: none; margin-bottom: 1rem;"></div>
          <button type="submit" class="btn btn-primary btn-sm" id="saveProfileBtn">Save Profile</button>
        </form>
      </div>

      <!-- Change Password -->
      <div class="profile-card" style="margin-top: 2rem;">
        <h3>Security & Password</h3>
        <form id="passwordForm">
          <div class="field">
            <label class="label" for="currentPwd">Current Password</label>
            <input class="input" type="password" id="currentPwd" required autocomplete="current-password" />
            <span class="field-error-text" id="currentPwdError" style="display: none;"></span>
          </div>
          <div class="field">
            <label class="label" for="newPwd">New Password</label>
            <input class="input" type="password" id="newPwd" required minlength="10" autocomplete="new-password" />
            <span style="font-size: 0.75rem; color: var(--color-muted);">Minimum 10 characters</span>
            <span class="field-error-text" id="newPwdError" style="display: none;"></span>
          </div>
          <div class="field">
            <label class="label" for="confirmNewPwd">Confirm New Password</label>
            <input class="input" type="password" id="confirmNewPwd" required autocomplete="new-password" />
            <span class="field-error-text" id="confirmPwdError" style="display: none;"></span>
          </div>
          <div id="passwordErrorNotice" class="notice notice-error" style="display: none; margin-bottom: 1rem;"></div>
          <button type="submit" class="btn btn-secondary btn-sm" id="changePwdBtn">Update Password</button>
        </form>
      </div>
    </div>
  `;

  // Profile Form Handler
  const profForm = container.querySelector('#profileForm');
  const profDisplayName = container.querySelector('#profDisplayName');
  const profBio = container.querySelector('#profBio');
  const bioCounter = container.querySelector('#bioCharCounter');
  const profErrorNotice = container.querySelector('#profileErrorNotice');
  const profDisplayError = container.querySelector('#profDisplayError');
  const saveProfBtn = container.querySelector('#saveProfileBtn');

  profBio.oninput = () => {
    bioCounter.textContent = `${profBio.value.length} / 1000`;
  };

  profForm.onsubmit = async (e) => {
    e.preventDefault();
    profErrorNotice.style.display = 'none';
    profDisplayError.style.display = 'none';
    profDisplayName.classList.remove('input-error');

    const displayName = profDisplayName.value.trim();
    const bio = profBio.value.trim();

    if (!displayName) {
      profDisplayError.textContent = 'Display name cannot be blank.';
      profDisplayError.style.display = 'block';
      profDisplayName.classList.add('input-error');
      return;
    }

    saveProfBtn.disabled = true;
    saveProfBtn.textContent = 'Saving...';

    try {
      await api('/auth/profile', {
        method: 'PATCH',
        body: { display_name: displayName, bio },
      });
      await refreshSession();
      notify('Profile updated successfully.', { kind: 'success' });
    } catch (err) {
      profErrorNotice.textContent = err.message || 'Failed to update profile';
      profErrorNotice.style.display = 'block';
    } finally {
      saveProfBtn.disabled = false;
      saveProfBtn.textContent = 'Save Profile';
    }
  };

  // Password Form Handler
  const pwdForm = container.querySelector('#passwordForm');
  const currentPwdInput = container.querySelector('#currentPwd');
  const newPwdInput = container.querySelector('#newPwd');
  const confirmPwdInput = container.querySelector('#confirmNewPwd');
  const currentPwdError = container.querySelector('#currentPwdError');
  const newPwdError = container.querySelector('#newPwdError');
  const confirmPwdError = container.querySelector('#confirmPwdError');
  const pwdErrorNotice = container.querySelector('#passwordErrorNotice');
  const changePwdBtn = container.querySelector('#changePwdBtn');

  pwdForm.onsubmit = async (e) => {
    e.preventDefault();
    pwdErrorNotice.style.display = 'none';
    currentPwdError.style.display = 'none';
    newPwdError.style.display = 'none';
    confirmPwdError.style.display = 'none';
    [currentPwdInput, newPwdInput, confirmPwdInput].forEach(el => el.classList.remove('input-error'));

    const currentPassword = currentPwdInput.value;
    const newPassword = newPwdInput.value;
    const confirmPassword = confirmPwdInput.value;

    let hasPwdError = false;
    if (!currentPassword) {
      currentPwdError.textContent = 'Current password is required.';
      currentPwdError.style.display = 'block';
      currentPwdInput.classList.add('input-error');
      hasPwdError = true;
    }

    if (!newPassword || newPassword.length < 10) {
      newPwdError.textContent = 'New password must be at least 10 characters long.';
      newPwdError.style.display = 'block';
      newPwdInput.classList.add('input-error');
      hasPwdError = true;
    }

    if (newPassword !== confirmPassword) {
      confirmPwdError.textContent = 'Passwords do not match.';
      confirmPwdError.style.display = 'block';
      confirmPwdInput.classList.add('input-error');
      hasPwdError = true;
    }

    if (hasPwdError) return;

    changePwdBtn.disabled = true;
    changePwdBtn.textContent = 'Updating...';

    try {
      await api('/auth/password', {
        method: 'POST',
        body: { current_password: currentPassword, new_password: newPassword },
      });
      await refreshSession();
      currentPwdInput.value = '';
      newPwdInput.value = '';
      confirmPwdInput.value = '';
      notify('Password changed securely. Other sessions revoked.', { kind: 'success' });
    } catch (err) {
      pwdErrorNotice.textContent = err.message || 'Failed to update password';
      pwdErrorNotice.style.display = 'block';
    } finally {
      changePwdBtn.disabled = false;
      changePwdBtn.textContent = 'Update Password';
    }
  };

  return function routeCleanup() {
    document.title = 'Folio: Knowledge & Research Library';
  };
}

function escapeText(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function escapeAttr(str) {
  if (!str) return '';
  return str.replace(/"/g, '&quot;');
}
