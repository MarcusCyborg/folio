# scripts/test_motion_runner.py
import socket
import threading
import http.server
import time
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from playwright.sync_api import sync_playwright
import tests.frontend.public.test_motion_and_lifecycle as m


def run():
    port = m.get_free_port()
    server = http.server.ThreadingHTTPServer(('127.0.0.1', port), m.QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server_url = f'http://127.0.0.1:{port}'
    print(f'Server started at {server_url}', flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        tests = [
            # Finding A (P1): Initial load + in-place search lifecycle
            m.test_a1_a5_search_during_initial_load_normal_and_reduced_motion,
            m.test_a2_query_change_while_categories_pending,
            m.test_a3_leave_library_before_initial_load_completes,
            m.test_a4_out_of_order_search_responses_latest_wins,
            # Finding B (P1): Transition / fallback mount ownership & cancellation
            m.test_b1_fallback_transition_stale_mount_does_not_overwrite_login,
            m.test_b2_rapid_navigation_detail_a_detail_b_library,
            m.test_b3_native_view_transition_superseded_by_new_navigation,
            m.test_b4_reduced_motion_no_stale_commit,
            m.test_b5_mount_callback_not_executed_twice_on_error,
            # Finding C (P2): Prefetch handoff, error recovery, and telemetry
            m.test_c1_single_click_opens_detail_with_one_get_and_no_pageerror,
            m.test_c2_abandoned_prefetch_does_not_overwrite_or_throw_pageerror,
            m.test_c3_detail_request_error_renders_error_state_and_retry_works,
            m.test_c4_c5_telemetry_single_fire_and_no_late_abandoned_view,
            # Finding D (P2): Filter chip DOM identity, exit animation, reflow, and focus
            m.test_d1_remove_one_chip_preserves_focus_and_dom_identity,
            m.test_d2_remove_last_query_chip_clears_url_and_focuses_input,
            m.test_d3_adding_new_filter_only_animates_new_chip_entrance,
            m.test_d4_rapid_multi_chip_removal_consistent_no_ghost_chips,
            m.test_d5_reduced_motion_and_live_toggle_during_chip_exit,
            m.test_d6_chip_exit_animation_real_evidence,
            # Section 6 & Core Lifecycle Invariants
            m.test_regression_shared_element_title_captured_in_snapshot,
            m.test_back_forward_long_list_scroll_and_focus_restoration,
            m.test_regression_stale_response_does_not_overwrite_navigated_document,
            m.test_regression_slow_network_does_not_timeout_view_transition,
            m.test_regression_multi_chip_keyboard_removal_preserves_focus,
            m.test_regression_single_chip_keyboard_removal_clears_search_input,
            m.test_regression_mobile_close_and_resize_inert_state,
            m.test_regression_reset_filters_button_selector_and_visibility,
            m.test_regression_indicator_after_reduced_motion_toggle,
            m.test_regression_second_pending_fade_lowers_opacity,
            m.test_regression_view_transitions_fallback_real_absence,
            m.test_regression_reading_progress_numeric_interpolation,
            m.test_regression_like_button_duplicate_guard_and_failure,
            m.test_in_place_query_update_preserves_focus_and_input,
            m.test_back_forward_navigation_state_persistence,
            m.test_date_accordion_inert_when_closed,
            m.test_toc_smooth_scroll_and_heading_highlight,
            m.test_responsive_viewports_no_overflow,
            # Issues 1, 2, and 3: UI failure state, reflow completion & font loading
            m.test_issue1_search_failure_ui_state_and_retry_recovery,
            m.test_retry_from_old_query_cannot_supersede_pending_search,
            m.test_retry_callback_is_single_use_and_expires_on_navigation,
            m.test_issue2_filter_chip_reflow_completion_and_idempotence,
            m.test_chip_exit_waits_for_animation_clock,
            m.test_issue3_font_loading_without_rewrite,
        ]

        passed = 0
        failed = 0
        for t in tests:
            print(f'Starting {t.__name__}...', flush=True)
            t0 = time.time()
            try:
                t(server_url, browser)
                dt = time.time() - t0
                print(f'  [PASS] {t.__name__} ({dt:.2f}s)', flush=True)
                passed += 1
            except Exception as e:
                dt = time.time() - t0
                print(f'  [FAIL] {t.__name__} ({dt:.2f}s): {type(e).__name__} - {e}', flush=True)
                failed += 1

        browser.close()

    server.shutdown()
    print(f'\nFinished: {passed} passed, {failed} failed.', flush=True)
    return failed


if __name__ == '__main__':
    sys.exit(run())
