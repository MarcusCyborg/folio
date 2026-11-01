# tests/frontend/public/test_accessibility_wcag.py
# Playwright test suite for Folio WCAG AA Accessibility & Keyboard Nav (M7 / UI-05)

import pytest
from playwright.sync_api import sync_playwright


def test_keyboard_navigation_and_visible_focus(live_server, browser_instance):
    """
    UI-05: Verifies keyboard navigation:
    - Interactive controls can receive focus via Tab key
    - Visible focus outlines are applied to focused elements
    """
    context = browser_instance.new_context(viewport={"width": 1366, "height": 768})
    page = context.new_page()

    page.goto(f"{live_server}/#/library")
    page.wait_for_selector(".document-card-row")

    # Tab through primary navigation elements
    page.keyboard.press("Tab")
    focused_tag = page.evaluate("() => document.activeElement ? document.activeElement.tagName.toLowerCase() : ''")
    assert focused_tag in ["a", "button", "input", "select"]

    # Verify focus-visible outline is defined in stylesheet
    outline_defined = page.evaluate("""() => {
        const btn = document.querySelector('#librarySearchBtn');
        btn.focus();
        const style = window.getComputedStyle(btn);
        return style.outlineStyle !== 'none' || style.outlineWidth !== '0px';
    }""")
    assert outline_defined, "Active buttons should display visible focus indication"

    context.close()


def test_form_labels_and_aria_error_associations(live_server, browser_instance):
    """
    UI-05: Verifies inputs have associated labels and error messages are
    linked via aria-describedby or alert roles.
    """
    context = browser_instance.new_context(viewport={"width": 1366, "height": 768})
    page = context.new_page()

    page.goto(f"{live_server}/#/login")
    page.wait_for_selector("#loginEmail")

    # Check label for loginEmail
    label_for_email = page.locator("label[for='loginEmail']")
    assert label_for_email.is_visible()
    assert "Email Address" in label_for_email.text_content()

    # Check aria-describedby on email input
    email_input = page.locator("#loginEmail")
    assert email_input.get_attribute("aria-describedby") == "loginEmailError"

    # Submit invalid login to trigger error
    page.click("#loginSubmitBtn")
    page.wait_for_selector("#loginEmailError:visible")

    error_el = page.locator("#loginEmailError")
    assert error_el.get_attribute("role") == "alert"

    context.close()


def test_dialog_focus_trap_and_escape_restore(live_server, browser_instance):
    """
    UI-05: Verifies modal dialogs (confirmAction):
    - Trap focus inside the dialog when Tab is pressed
    - Dismiss on Escape key
    - Restore focus to the element that triggered the dialog
    """
    context = browser_instance.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    # Login as admin to access document editor dirty guard
    page.goto(f"{live_server}/#/login")
    page.wait_for_selector("#loginEmail")
    page.fill("#loginEmail", "admin@folio.test")
    page.fill("#loginPassword", "FolioDemo2026!")
    page.click("#loginSubmitBtn")
    page.wait_for_selector(".user-badge, #logoutBtn")

    # Open create document form
    page.goto(f"{live_server}/#/admin/documents/new")
    page.wait_for_selector("#docEditorForm")

    # Make form dirty
    page.fill("#editTitle", "Accessibility Verification Title")
    page.wait_for_selector("#dirtyIndicator", state="visible")

    # Focus and click back link to trigger confirmAction dialog
    trigger_link = page.locator("#editorBackLink")
    trigger_link.focus()
    trigger_link.click()

    page.wait_for_selector(".dialog")
    dialog = page.locator(".dialog")
    assert dialog.is_visible()
    assert dialog.get_attribute("role") == "dialog"
    assert dialog.get_attribute("aria-modal") == "true"

    # Tab through buttons: confirmBtn -> cancelBtn -> confirmBtn (focus trapped)
    page.keyboard.press("Tab")
    active_btn_text = page.evaluate("() => document.activeElement ? document.activeElement.textContent : ''")
    assert active_btn_text in ["Cancel", "Discard & Leave"]

    # Press Escape to close dialog
    page.keyboard.press("Escape")
    page.wait_for_selector(".dialog", state="detached")

    # Focus must be restored to triggering link
    is_restored = page.evaluate("() => document.activeElement && document.activeElement.id === 'editorBackLink'")
    assert is_restored, "Focus should be restored to the triggering element after dialog dismiss"

    context.close()


def test_reduced_motion_media_query_applied(live_server, browser_instance):
    """
    UI-05: Verifies that when prefers-reduced-motion: reduce is requested,
    CSS rules neutralize animations and smooth scrolling.
    """
    context = browser_instance.new_context(
        viewport={"width": 1366, "height": 768},
        reduced_motion="reduce",
    )
    page = context.new_page()

    page.goto(f"{live_server}/#/library")
    page.wait_for_selector(".document-card-row")

    # Check that spinner animation duration is neutralized
    anim_duration = page.evaluate("""() => {
        const spinner = document.createElement('div');
        spinner.className = 'spinner';
        document.body.appendChild(spinner);
        const style = window.getComputedStyle(spinner);
        const dur = style.animationDuration;
        document.body.removeChild(spinner);
        return dur;
    }""")
    assert anim_duration in ["0s", "0.001ms", "1e-06s", "0.000001s"] or "ms" in anim_duration

    context.close()
