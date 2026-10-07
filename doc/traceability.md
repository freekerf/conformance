# Traceability: white-box characterization -> portable comparison

Every test of `tests/whitebox/` (the C# core; importers are milestone M2) is one row: the
behaviour it pins, whether that behaviour is **observable** through the `HostAdapter`
(device traffic and coarse host state) or the golden `analyze` JSON, which portable test
compares it between LaserGRBL and FreeKerf, which FreeKerf (Rust) test covers it, and the
related `DIV-NNN` entry of FreeKerf's [`doc/divergences.md`](https://github.com/freekerf/freekerf/blob/main/doc/divergences.md).

`tests/test_traceability.py` keeps this file honest: every white-box test is listed once,
every portable reference exists and the counts below match the rows.

## Summary

- White-box tests (rows): **418**
- Behaviours observable through the HostAdapter or `analyze`: **206**
- Observable and compared between the two hosts: **64 before** this work -> **182 now**
  (179 by fixed protocol or golden tests, 3 only by the differential layer)
- Observable but not compared yet: **24** (listed at the end, with the reason)
- Rows with a FreeKerf (Rust) test: 224

| Area | Rows | Observable | Compared before | Compared now |
| --- | ---: | ---: | ---: | ---: |
| Streaming and buffer accounting | 14 | 11 | 5 | 11 |
| Job lifecycle and resume | 42 | 25 | 7 | 25 |
| Custom code | 10 | 7 | 1 | 7 |
| Immediate commands and permissions | 10 | 8 | 3 | 7 |
| Responses, banners and status | 38 | 31 | 5 | 30 |
| Overrides | 3 | 1 | 1 | 1 |
| Jog | 21 | 17 | 0 | 16 |
| Configuration ($$, $I, settings table) | 52 | 25 | 2 | 18 |
| Connection and transport | 19 | 2 | 2 | 2 |
| Firmware variants | 23 | 23 | 2 | 11 |
| G-code parsing and analysis | 115 | 56 | 36 | 54 |
| Application glue | 10 | 0 | 0 | 0 |
| Settings persistence | 19 | 0 | 0 | 0 |
| Laser life counters | 24 | 0 | 0 | 0 |
| Emulator | 18 | 0 | 0 | 0 |
| **Total** | **418** | **206** | **64** | **182** |

Reading the portable column: `test_x.py::name` is a protocol test (`tests/protocol/`),
`golden:case` a golden G-code case (`fixtures/gcode/case.nc`), `diff:gcode` / `diff:protocol`
the generators of the differential layer (`tests/differential/`, `make test-diff`). A test or
case marked `rust_divergence("DIV-NNN")` passes on the C# host and is an expected failure on
the Rust host. Rust tests are `file.rs::function` (`host_behaviour.rs` and `protocol.rs` are in
`crates/core/freekerf-protocol/tests/`; the others are unit tests of the module with that name).

Notes on "not observable":

1. C# object model, exception paths with injected faults, console text, UI (dialogs, events,
   hotkeys) and persistence formats are LaserGRBL implementation details, not wire behaviour.
2. Mono's `SerialPort` on a PTY does not see a hang-up (the read error is retried by the CH340
   workaround) and its `Close` blocks while the reader waits in `poll()`; the connection timeout
   and a lost port cannot be reproduced over a PTY with the C# host (FreeKerf covers them).
3. The C# emulator is a device; FreeKerf's emulator is a different design (see DIVERGENCES).
4. The time projection (projected time, counters) is not observed by the HostAdapter.
5. The laser life counters live in a file and in dialogs, not on the wire.

## Streaming and buffer accounting

| White-box test | Behaviour | Observable | Portable | Rust | DIV |
| --- | --- | --- | --- | --- | --- |
| `test_core_tx.py::test_stream_waits_when_rx_buffer_full` | Buffered mode waits when the next line does not fit the RX budget; an ok frees its bytes | yes | `test_protocol.py::test_stream_waits_when_rx_buffer_full`, `test_protocol.py::test_stream_never_overflows_the_127_byte_rx_buffer`, `diff:protocol` | `protocol.rs::stream_waits_when_rx_buffer_full`, `buffer_properties.rs::rx_buffer_never_overflows` | — |
| `test_core_tx.py::test_line_that_exactly_fills_buffer_is_sent` | A line of exactly the free bytes is sent | yes | `test_jobs.py::test_line_that_exactly_fills_the_rx_buffer_is_sent` | — | — |
| `test_core_tx.py::test_line_bigger_than_buffer_is_never_sent` | A line longer than the buffer is never sent (the job stays stuck on it) | yes | `test_jobs.py::test_line_bigger_than_the_rx_buffer_is_never_sent` | — | — |
| `test_core_tx.py::test_all_lines_streamed_in_order` | Every queued line is streamed in order, compressed | yes | `test_protocol.py::test_stream_sends_header_job_and_footer_in_order`, `diff:protocol` | `protocol.rs::stream_sends_header_job_and_footer_in_order` | — |
| `test_core_tx.py::test_synchronous_mode_sends_one_line_at_a_time` | Synchronous mode keeps one line in flight | yes | `test_protocol.py::test_synchronous_mode_keeps_one_line_in_flight`, `diff:protocol` | `protocol.rs::synchronous_mode_keeps_one_line_in_flight` | — |
| `test_core_tx.py::test_eeprom_write_is_sent_synchronously` | A `$N=V` line is sent alone (nothing else until it is answered) | yes | `test_jobs.py::test_settings_write_is_sent_alone` | `host_behaviour.rs::eeprom_writes_go_one_at_a_time_and_update_the_table` | — |
| `test_core_tx.py::test_send_error_is_logged_and_command_dropped` | A write error leaves the line pending | no: C# exception path (injected fault) | — | — | — |
| `test_core_tx.py::test_sent_command_window` | Window over the sent-commands log | no: console text only | — | — | — |
| `test_core_tx.py::test_enqueue_stores_a_clone` | The queue holds clones | no: C# object model, not behaviour | — | — | DIV-002 |
| `test_core_rx.py::test_ok_completes_oldest_pending_and_frees_buffer` | `ok` completes the oldest pending line and frees its bytes | yes | `test_protocol.py::test_stream_waits_when_rx_buffer_full`, `diff:protocol` | `protocol.rs::stream_waits_when_rx_buffer_full` | — |
| `test_core_rx.py::test_response_without_pending_command_is_ignored` | An `ok` with nothing pending is ignored | yes | `test_responses.py::test_ok_without_a_pending_line_is_ignored` | `host_behaviour.rs::ip_messages_alarms_and_broken_oks` | — |
| `test_core_rx.py::test_used_buffer_never_goes_negative` | Used buffer never goes below 0 | yes | `test_responses.py::test_ok_without_a_pending_line_is_ignored` | `buffer_properties.rs::rx_buffer_never_overflows` | — |
| `test_core_rx.py::test_broken_ok_counts_as_ok_and_logs_warning` | Any line containing `ok` acknowledges the oldest pending line (F-51) | yes | `test_responses.py::test_garbled_ok_still_acknowledges_the_line`, `test_responses.py::test_any_message_containing_ok_acknowledges_a_line` | `host_behaviour.rs::ip_messages_alarms_and_broken_oks` | DIV-051 |
| `test_core_rx.py::test_buffer_auto_size_only_accepts_known_values_once` | RX buffer size learnt from `Bf:`/`[OPT:]`, known sizes only, once | yes | `test_responses.py::test_rx_buffer_size_learnt_from_the_board`, `test_responses.py::test_rx_buffer_size_from_bf_without_machine_info_query`, `test_protocol.py::test_host_uses_the_rx_buffer_size_reported_by_the_board` | `protocol.rs::host_uses_the_rx_buffer_size_reported_by_the_board` | — |

## Job lifecycle and resume

| White-box test | Behaviour | Observable | Portable | Rust | DIV |
| --- | --- | --- | --- | --- | --- |
| `test_core_tx.py::test_run_program_sends_header_file_and_footer` | A job is header + program + footer; the end is logged | yes | `test_protocol.py::test_stream_sends_header_job_and_footer_in_order`, `diff:protocol` | `host_behaviour.rs::comment_lines_are_streamed_as_empty_lines_and_header_footer_wrap_the_job` | — |
| `test_core_tx.py::test_run_program_counts_errors` | `error:N` during a job is counted | yes | `test_protocol.py::test_error_mid_job_is_counted_and_streaming_continues`, `diff:protocol` | `host_behaviour.rs::errors_are_counted_and_decoded_in_the_console` | — |
| `test_core_tx.py::test_loop_count_repeats_program_with_passes_code` | Passes repeat the program with the passes code (comment lines streamed empty) | yes | `test_jobs.py::test_passes_repeat_the_program_with_the_passes_code`, `test_jobs.py::test_custom_passes_code_runs_between_passes`, `diff:protocol` | `host_behaviour.rs::loop_count_repeats_the_program_with_the_passes_code` | DIV-017 |
| `test_core_tx.py::test_loop_count_in_check_mode_runs_once` | In check mode the program runs once | yes | `test_jobs.py::test_passes_run_once_in_check_mode` | — | — |
| `test_core_tx.py::test_run_program_requires_idle_connected_and_empty_queue` | Run needs a program, Idle/Check and an empty queue | yes | `test_jobs.py::test_run_without_a_program_sends_nothing`, `test_jobs.py::test_run_is_ignored_while_manual_commands_are_queued` | `host_behaviour.rs::run_program_preconditions` | DIV-103 |
| `test_core_tx.py::test_run_program_swallows_exceptions` | Run swallows exceptions (null header) | no: C# exception path (injected fault) | — | — | — |
| `test_core_tx.py::test_abort_program_flushes_queue_and_turns_laser_off` | Abort flushes the queue and sends `M5`; not an issue | yes | `test_protocol.py::test_abort_job_flushes_and_turns_laser_off`, `diff:protocol` | `protocol.rs::abort_job_flushes_and_turns_laser_off` | — |
| `test_core_tx.py::test_abort_without_program_is_ignored` | Abort without a job does nothing | yes | `test_jobs.py::test_abort_without_a_job_sends_nothing` | `host_behaviour.rs::abort_without_job_is_refused` | DIV-103 |
| `test_core_tx.py::test_abort_exception_is_swallowed` | Abort swallows exceptions | no: C# exception path (injected fault) | — | — | — |
| `test_core_tx.py::test_resume_from_position_rebuilds_state` | Resume: `G90`, `M5 G0` to the position with F/S, settled modals, rest of the program; G20 not tracked | yes | `test_jobs.py::test_resume_from_a_position_rebuilds_position_power_and_modes`, `diff:protocol` | `host_behaviour.rs::resume_from_position_rebuilds_state` | DIV-018 |
| `test_core_tx.py::test_resume_with_homing_and_work_offset` | Resume with homing and the WCO of the interrupted job; empty modal command (F-19) | yes | `test_jobs.py::test_resume_with_homing_restores_the_work_offset_of_the_interrupted_job`, `test_jobs.py::test_resume_without_settled_modal_groups_sends_an_empty_line` | `host_behaviour.rs::resume_adds_the_motion_mode_homing_and_work_offset` | DIV-019 |
| `test_core_tx.py::test_resume_position_beyond_file_end` | Resume past the end moves to the last position | yes | `test_jobs.py::test_resume_beyond_the_end_moves_to_the_last_position` | — | — |
| `test_core_tx.py::test_resume_first_movement_without_g_gets_motion_mode` | The first resumed move gets its motion mode | yes | `test_jobs.py::test_resume_gives_the_first_move_its_motion_mode` | `host_behaviour.rs::resume_adds_the_motion_mode_homing_and_work_offset` | — |
| `test_core_tx.py::test_repeat_on_error_resends_failed_line_up_to_three_times` | RepeatOnError resends a failed line up to 3 times | yes | `test_protocol.py::test_error_mid_job_is_retried_in_repeat_on_error_mode`, `diff:protocol` | `protocol.rs::error_mid_job_is_retried_in_repeat_on_error_mode` | — |
| `test_core_tx.py::test_grbl_reset_during_program_flags_manual_reset` | Soft reset during a job: ManualReset (not an issue), queue flushed, override targets back to 100 | yes | `test_protocol.py::test_soft_reset_mid_job_stops_streaming`, `test_responses.py::test_overrides_are_not_pushed_back_after_a_soft_reset`, `diff:protocol` | `protocol.rs::soft_reset_mid_job_stops_streaming`, `host_behaviour.rs::resume_suggestion_after_an_interruption` | — |
| `test_core_tx.py::test_grbl_reset_not_allowed_when_disconnected` | Soft reset needs a connection | no: nothing reaches a device without a connection | — | `host_behaviour.rs::state_rules_of_immediate_commands` | DIV-102 |
| `test_core_tx.py::test_hang_detected_when_no_status_for_too_long` | No status report for 10 periods and 5 s while running: StopResponding | yes | `test_responses.py::test_no_status_for_too_long_during_a_job_is_reported` | `host_behaviour.rs::hang_is_detected_when_status_reports_stop` | — |
| `test_core_tx.py::test_buffer_stuck_is_unlocked_when_grbl_reports_empty_buffer` | Lost oks: after 10 s idle with `Bf:` empty the host answers the pending lines itself | yes | `test_responses.py::test_lost_oks_are_recovered_when_the_board_reports_an_empty_buffer` | `host_behaviour.rs::buffer_stuck_is_unlocked_when_the_board_reports_an_empty_buffer` | — |
| `test_core_tx.py::test_manual_buffer_stuck_unlock` | Manual 'unlock from buffer stuck' | no: UI command, no action in the HostAdapter or FreeKerf's registry | — | `host_behaviour.rs::manual_buffer_stuck_unlock` | — |
| `test_core_tx.py::test_close_com_during_program_flags_disconnect` | Port lost during a job: UnexpectedDisconnect | no: not reproducible over a PTY with Mono's SerialPort (see note 2) | — | `host_behaviour.rs::disconnect_during_a_job_is_reported_unless_user`, `driver.rs::hang_up_on_a_pty_disconnects` | — |
| `test_core_tx.py::test_close_com_by_user_is_not_reported` | User disconnect during a job: ManualDisconnect, not an issue | yes | `test_responses.py::test_disconnect_by_the_user_during_a_job_is_not_an_issue`, `test_protocol.py::test_disconnect_closes_the_line` | `host_behaviour.rs::disconnect_during_a_job_is_reported_unless_user` | — |
| `test_core_tx.py::test_close_com_exception_is_swallowed` | Close swallows exceptions | no: C# exception path (injected fault) | — | — | — |
| `test_core_tx.py::test_exiting_closes_everything` | Application exit closes the port | no: UI (dialogs, events, hotkeys) | — | — | — |
| `test_core_tx.py::test_exiting_tolerates_failures` | Exit tolerates missing threads | no: C# exception path (injected fault) | — | — | — |
| `test_core_tx.py::test_write_config_is_silently_skipped_when_not_idle` | Settings write/read outside Idle/Alarm silently does nothing (F-24) | yes | `test_jobs.py::test_write_settings_is_silently_skipped_during_a_job` | `host_behaviour.rs::manual_commands_are_refused_during_a_job` | DIV-024 |
| `test_core_tx.py::test_job_started_during_connect_time_refresh_is_lost` | A job started during the connect-time `$$`/`$I` is cut short (F-30) | yes | `test_jobs.py::test_job_started_during_the_connect_time_settings_read_is_cut_short` | `host_behaviour.rs::run_program_preconditions` | DIV-030 |
| `test_core_rx.py::test_welcome_during_running_program_is_an_unexpected_reset` | A banner during a job: UnexpectedReset, job over | yes | `test_responses.py::test_board_restart_during_a_job_is_an_unexpected_reset` | `host_behaviour.rs::unexpected_reset_during_a_job_is_reported` | — |
| `test_core_rx.py::test_alarm_message_during_program_raises_machine_alarm_issue` | `ALARM:` during a job: MachineAlarm | yes | `test_protocol.py::test_alarm_mid_job_is_reported`, `diff:protocol` | `protocol.rs::alarm_mid_job_is_reported` | — |
| `test_core_rx.py::test_alarm_outside_program_is_just_logged` | `ALARM:` while idle is not an issue | yes | `test_responses.py::test_alarm_while_idle_is_not_an_issue` | — | — |
| `test_core_rx.py::test_wco_is_remembered_for_job_resume_only_in_program` | The WCO is remembered for resume only during a job | yes | `test_jobs.py::test_resume_with_homing_restores_the_work_offset_of_the_interrupted_job` | `projection.rs::wco_and_issues` | — |
| `test_core_gaps.py::test_run_from_start_with_homing_pushes_dollar_h_first` | Run with homing: `$H` before the header | yes | `test_jobs.py::test_run_with_homing_sends_dollar_h_before_the_header` | `host_behaviour.rs::run_with_homing_pushes_dollar_h_first` | — |
| `test_core_gaps.py::test_restart_from_the_start_after_an_interruption_skips_the_header` | Restarting an interrupted job from the start skips the header (F-54) | no: only through the resume dialog (UI) | — | — | DIV-054 |
| `test_core_gaps.py::test_job_end_notifies_telegram_when_over_threshold` | Telegram notification at the end of a long job | no: notifications (UI concern) | — | — | DIV-104 |
| `test_grblfile.py::test_program_end_without_subscribers` | Passes run without event subscribers | yes | `test_jobs.py::test_passes_repeat_the_program_with_the_passes_code` | `host_behaviour.rs::loop_count_repeats_the_program_with_the_passes_code` | — |
| `test_core_types.py::test_time_projection_initial_state` | Time projection: initial state | no: time projection is not observed by the HostAdapter (note 4) | — | `projection.rs::counters_and_projection` | — |
| `test_core_types.py::test_time_projection_job_counters` | Job counters (target, sent, executed, errors) frozen after the end | no: time projection is not observed by the HostAdapter (note 4) | — | `projection.rs::counters_and_projection`, `host_behaviour.rs::time_projection_follows_the_job` | — |
| `test_core_types.py::test_time_projection_projects_from_progress` | Projected time from progress | no: time projection is not observed by the HostAdapter (note 4) | — | `projection.rs::counters_and_projection` | — |
| `test_core_types.py::test_time_projection_without_progress_returns_estimate` | Projection without progress is the estimate | no: time projection is not observed by the HostAdapter (note 4) | — | `projection.rs::counters_and_projection` | — |
| `test_core_types.py::test_time_projection_pauses_are_excluded_from_true_time` | Pauses excluded; negative global time between passes (F-14) | no: time projection is not observed by the HostAdapter (note 4) | — | `projection.rs::passes_keep_the_global_start` | DIV-014 |
| `test_core_types.py::test_time_projection_global_time_spans_passes` | Global time spans passes | no: time projection is not observed by the HostAdapter (note 4) | — | `projection.rs::passes_keep_the_global_start` | — |
| `test_core_types.py::test_time_projection_continue_from_position` | Counters of a resumed job | no: time projection is not observed by the HostAdapter (note 4) | — | `projection.rs::continue_from_position` | — |
| `test_core_types.py::test_time_projection_last_known_wco_only_while_in_program` | Last known WCO only while in a job | yes | `test_jobs.py::test_resume_with_homing_restores_the_work_offset_of_the_interrupted_job` | `projection.rs::wco_and_issues` | — |

## Custom code

| White-box test | Behaviour | Observable | Portable | Rust | DIV |
| --- | --- | --- | --- | --- | --- |
| `test_core_tx.py::test_custom_header_footer_expressions_and_immediate_codes` | Header/footer with `[expr]` and immediate codes (`0x85`, `!`) | yes | `test_jobs.py::test_custom_header_and_footer_with_expressions_and_immediates` | `host_behaviour.rs::custom_header_and_footer_with_expressions_and_immediates` | — |
| `test_core_tx.py::test_execute_custom_code_handles_immediates_and_expressions` | Custom code: immediates at once, `0xZZ` as text, `[jogstep]`/`[jogspeed]` | yes | `test_jobs.py::test_custom_code_sends_immediates_at_once_and_queues_the_rest`, `test_jobs.py::test_custom_code_expressions_see_the_jog_step_and_speed`, `diff:protocol` | `host_behaviour.rs::custom_header_and_footer_with_expressions_and_immediates`, `host_behaviour.rs::custom_code_sees_the_jog_step_and_speed` | — |
| `test_core_tx.py::test_evaluate_expression_variables` | Expression variables (drawing, `$N`, WCO, MPos; WPos is MPos) | yes | `test_jobs.py::test_custom_code_expressions_see_the_drawing_the_board_and_its_settings`, `test_jobs.py::test_custom_code_wpos_variables_are_the_machine_position` | `expr.rs::brackets_are_replaced_and_formatted`, `host_behaviour.rs::work_position_variables_are_the_work_position` | DIV-101 |
| `test_core_tx.py::test_evaluate_expression_default_spindle_max_and_empty_drawing` | `$30` defaults to 1000, the drawing to 0 | yes | `test_jobs.py::test_custom_code_expressions_without_settings_or_drawing` | `expr.rs::brackets_are_replaced_and_formatted` | — |
| `test_core_tx.py::test_auto_cooling_pauses_and_resumes` | Auto cooling holds after TOn of job time and resumes after TOff | yes | `test_jobs.py::test_auto_cooling_holds_the_job_and_resumes_it` | `host_behaviour.rs::auto_cooling_holds_and_resumes` | — |
| `test_core_tx.py::test_auto_cooling_without_laser_mode_does_nothing` | No auto cooling without laser mode | yes | `test_jobs.py::test_auto_cooling_needs_laser_mode` | — | — |
| `test_core_tx.py::test_tx_loop_sends_and_queries_status` | The TX loop sends and polls the status | yes | `test_protocol.py::test_status_is_polled_periodically` | `protocol.rs::status_is_polled_periodically`, `host_behaviour.rs::next_deadline_follows_the_timers` | — |
| `test_core_tx.py::test_tx_loop_exception_is_logged` | TX loop exception logged | no: C# exception path (injected fault) | — | — | — |
| `test_core_tx.py::test_connect_timeout_closes_port` | 10 s in Connecting closes the port | no: not reproducible over a PTY with Mono's SerialPort (see note 2) | — | `host_behaviour.rs::connection_timeout_closes_the_port` | — |
| `test_core_tx.py::test_open_com_failure_reports_and_disconnects` | A port that cannot open: failed connection counted | no: ends in a MessageBox (UI) | — | `host_behaviour.rs::connection_timeout_closes_the_port`, `driver.rs::open_failure_is_reported` | — |

## Immediate commands and permissions

| White-box test | Behaviour | Observable | Portable | Rust | DIV |
| --- | --- | --- | --- | --- | --- |
| `test_core_tx.py::test_feed_hold_and_resume` | `!` only while running, `~` only in a hold or door | yes | `test_protocol.py::test_feed_hold_pauses_and_cycle_start_resumes`, `test_responses.py::test_feed_hold_and_resume_are_not_sent_when_not_allowed`, `test_responses.py::test_door_open_is_resumed_with_cycle_start`, `diff:protocol` | `protocol.rs::feed_hold_pauses_and_cycle_start_resumes`, `host_behaviour.rs::state_rules_of_immediate_commands` | DIV-103 |
| `test_core_tx.py::test_safety_door_sends_legacy_at_sign` | Safety door sends `@` (Grbl 0.9), prefixing the next line (F-20) | yes | `test_responses.py::test_safety_door_sends_the_legacy_at_sign`, `diff:protocol` | `host_behaviour.rs::state_rules_of_immediate_commands` | DIV-020 |
| `test_core_tx.py::test_query_position_sends_question_mark` | Status query is `?` | yes | `test_protocol.py::test_status_is_polled_periodically` | `protocol.rs::status_is_polled_periodically` | — |
| `test_core_tx.py::test_send_immediate_only_when_port_open` | Immediate bytes only with the port open | no: nothing reaches a device without a connection | — | — | — |
| `test_core_tx.py::test_send_immediate_write_error_is_swallowed` | Immediate write error swallowed | no: C# exception path (injected fault) | — | — | — |
| `test_core_tx.py::test_can_flags_by_state` | What each state allows | yes | `test_responses.py::test_feed_hold_and_resume_are_not_sent_when_not_allowed`, `test_jog.py::test_jog_is_not_sent_during_a_job`, `test_jog.py::test_set_zero_only_away_from_the_work_zero`, `test_jog.py::test_home_is_not_sent_when_homing_is_disabled` | `host_behaviour.rs::state_rules_of_immediate_commands`, `host_behaviour.rs::manual_commands_are_refused_during_a_job` | DIV-103 |
| `test_core_tx.py::test_homing_unlock_zero_commands` | `$H`, `$X`, `G92 X0 Y0 Z0` (zero only away from the work zero) | yes | `test_protocol.py::test_unlock_and_home`, `test_jog.py::test_set_zero_only_away_from_the_work_zero`, `diff:protocol` | `host_behaviour.rs::state_rules_of_immediate_commands` | — |
| `test_core_tx.py::test_homing_not_allowed_when_disabled` | No `$H` with `$22=0` | yes | `test_jog.py::test_home_is_not_sent_when_homing_is_disabled` | `host_behaviour.rs::state_rules_of_immediate_commands` | — |
| `test_core_gaps.py::test_permission_matrix` | Permission matrix (state x job) | yes | `test_responses.py::test_feed_hold_and_resume_are_not_sent_when_not_allowed`, `test_jog.py::test_jog_is_not_sent_during_a_job`, `test_jobs.py::test_write_settings_is_silently_skipped_during_a_job`, `test_responses.py::test_door_open_is_resumed_with_cycle_start`, `diff:protocol` | `host_behaviour.rs::state_rules_of_immediate_commands`, `host_behaviour.rs::manual_commands_are_refused_during_a_job` | DIV-103 |
| `test_core_gaps.py::test_jog_enabled_legacy_firmware_in_program` | Grbl 0.9: no jog during a job | yes | — | `host_behaviour.rs::jog_is_refused_when_not_idle` | — |

## Responses, banners and status

| White-box test | Behaviour | Observable | Portable | Rust | DIV |
| --- | --- | --- | --- | --- | --- |
| `test_core_rx.py::test_error_marks_command_bad` | `error:N` marks the line bad | yes | `test_protocol.py::test_error_mid_job_is_counted_and_streaming_continues` | `host_behaviour.rs::errors_are_counted_and_decoded_in_the_console` | — |
| `test_core_rx.py::test_eeprom_write_ok_updates_stored_configuration` | An acknowledged `$N=V` updates the table | yes | `test_jog.py::test_jog_to_a_position_is_clamped_by_the_soft_limits`, `test_jog.py::test_rejected_settings_write_leaves_the_table_unchanged` | `host_behaviour.rs::eeprom_writes_go_one_at_a_time_and_update_the_table` | — |
| `test_core_rx.py::test_eeprom_write_is_lost_when_no_configuration_was_read_yet` | Without a `$$` read, a written value is lost (F-16) | yes | `test_jog.py::test_settings_written_before_any_read_are_forgotten` | `host_behaviour.rs::settings_written_before_any_read_are_used` | DIV-016 |
| `test_core_rx.py::test_eeprom_write_error_does_not_update_configuration` | A rejected `$N=V` does not change the table | yes | `test_jog.py::test_rejected_settings_write_leaves_the_table_unchanged` | — | — |
| `test_core_rx.py::test_response_exception_is_swallowed` | Response handler exception swallowed | no: C# exception path (injected fault) | — | — | — |
| `test_core_rx.py::test_standard_welcome_sets_version_and_resets_state` | Banner: version; queue and override targets reset | yes | `test_protocol.py::test_connect_sends_soft_reset_then_status_query_then_reads_settings`, `test_responses.py::test_banner_sets_version_and_vendor`, `test_responses.py::test_overrides_are_not_pushed_back_after_a_soft_reset` | `host_behaviour.rs::firmware_banners_and_vendors` | — |
| `test_core_rx.py::test_malformed_welcome_is_logged_not_fatal` | Malformed banner: no version | yes | `test_responses.py::test_malformed_banner_sets_no_version` | `host_behaviour.rs::firmware_banners_and_vendors` | — |
| `test_core_rx.py::test_grblhal_welcome` | grblHAL banner | yes | `test_responses.py::test_banner_sets_version_and_vendor` | `host_behaviour.rs::firmware_banners_and_vendors` | — |
| `test_core_rx.py::test_grblhal_malformed` | Malformed grblHAL banner | yes | `test_responses.py::test_malformed_banner_sets_no_version` | — | — |
| `test_core_rx.py::test_vigo_welcome_sets_vendor_and_build` | Grbl-Vigo banner: vendor and build | yes | `test_responses.py::test_banner_sets_version_and_vendor` | `host_behaviour.rs::firmware_banners_and_vendors` | — |
| `test_core_rx.py::test_vigo_malformed` | Malformed Grbl-Vigo banner | yes | `test_responses.py::test_malformed_banner_sets_no_version` | — | — |
| `test_core_rx.py::test_ortur_model_firmware_then_welcome` | Ortur model and OLF version before the banner | yes | `test_responses.py::test_banner_sets_version_and_vendor` | `host_behaviour.rs::firmware_banners_and_vendors` | — |
| `test_core_rx.py::test_aufero_model_is_handled_as_ortur` | Aufero is handled as Ortur | yes | `test_responses.py::test_banner_sets_version_and_vendor` | `host_behaviour.rs::firmware_banners_and_vendors` | — |
| `test_core_rx.py::test_longer_machine_and_software` | Longer `[Machine:]`/`[Software:]` | yes | `test_responses.py::test_banner_sets_version_and_vendor` | `host_behaviour.rs::firmware_banners_and_vendors` | — |
| `test_core_rx.py::test_simplelaser_welcome` | SimpleLaser banner | yes | `test_responses.py::test_banner_sets_version_and_vendor` | `host_behaviour.rs::firmware_banners_and_vendors` | — |
| `test_core_rx.py::test_simplelaser_malformed` | Malformed SimpleLaser banner | yes | `test_responses.py::test_malformed_banner_sets_no_version` | — | — |
| `test_core_rx.py::test_unknown_firmware_welcome_detected_by_regex_once` | Unknown firmware banner (`Name X.Yz`) before any banner | yes | `test_responses.py::test_banner_sets_version_and_vendor` | `host_behaviour.rs::firmware_banners_and_vendors` | — |
| `test_core_rx.py::test_unknown_welcome_parse_failure_is_swallowed` | Unknown banner with an unparseable version | yes | `test_responses.py::test_malformed_banner_sets_no_version` | — | — |
| `test_core_rx.py::test_version_change_reloads_csv_and_logs` | A 0.9 banner switches to the 0.9 behaviour | yes | `test_jog.py::test_jog_on_grbl_09_is_a_relative_move`, `test_responses.py::test_legacy_status_reports_of_grbl_09` | `host_behaviour.rs::jog_on_grbl_09_uses_plain_gcode` | — |
| `test_core_rx.py::test_version_support_flags_for_v11` | Grbl 1.1: `$J=` jog, overrides, laser mode | yes | `test_jog.py::test_jog_direction`, `test_protocol.py::test_overrides_converge_to_targets` | `host_behaviour.rs::jog_variants_v11` | — |
| `test_core_rx.py::test_alarm_message_is_decoded_when_version_supports_csv` | `ALARM:N` decoded in the console | no: console text only | — | `console.rs::decoding` | — |
| `test_core_rx.py::test_sta_ip_message_records_ip` | `[MSG:Get IP ...]` records the IP | yes | `test_responses.py::test_ip_messages_are_recorded` | `host_behaviour.rs::ip_messages_alarms_and_broken_oks` | — |
| `test_core_rx.py::test_longer_ip_message_records_ip` | `[MSG:Connected with ...]` records the IP | yes | `test_responses.py::test_ip_messages_are_recorded` | `host_behaviour.rs::ip_messages_alarms_and_broken_oks` | — |
| `test_core_rx.py::test_generic_message_is_logged` | Other messages are logged | no: console text only | — | — | — |
| `test_core_rx.py::test_generic_message_exception_is_swallowed` | Message handler exception swallowed | no: C# exception path (injected fault) | — | — | — |
| `test_core_rx.py::test_ip_message_too_short_is_swallowed` | Truncated IP message handler | no: handler called directly, such a line never matches | — | — | — |
| `test_core_rx.py::test_vendor_message_handlers_catch_parse_errors` | Vendor handlers with a null line | no: a null line never comes from the wire | — | — | — |
| `test_core_rx.py::test_status_report_parses_all_fields` | Status report: MPos, Bf, FS, WCO, Ov | yes | `test_responses.py::test_status_report_positions_and_work_offset`, `test_protocol.py::test_overrides_converge_to_targets`, `test_responses.py::test_rx_buffer_size_learnt_from_the_board` | `status.rs::parses_every_v11_field`, `host_behaviour.rs::status_report_fields` | — |
| `test_core_rx.py::test_status_report_wpos_is_converted_with_known_wco` | WPos reports converted with the last WCO | yes | `test_responses.py::test_status_report_with_wpos_is_converted_with_the_last_wco` | `host_behaviour.rs::status_report_fields` | — |
| `test_core_rx.py::test_status_report_with_short_coordinate_list` | Two-axis reports | yes | `test_responses.py::test_status_report_with_two_axes` | `status.rs::parses_every_v11_field` | — |
| `test_core_rx.py::test_status_version_guessed_from_report_when_unknown` | Unknown version: the report shape picks the parser | yes | `test_responses.py::test_status_report_without_a_known_version_is_read_by_its_shape` | `status.rs::version_is_guessed_from_the_report_shape` | — |
| `test_core_rx.py::test_legacy_status_report_v09` | Grbl 0.9 comma reports | yes | `test_responses.py::test_legacy_status_reports_of_grbl_09` | `host_behaviour.rs::legacy_status_reports_without_version` | — |
| `test_core_rx.py::test_legacy_status_report_status_only` | `<Alarm>` without fields | yes | — | `status.rs::legacy_reports` | — |
| `test_core_rx.py::test_pin_report_with_unknown_version_is_not_parsed` | `|` + `Pin:` with an unknown version is not parsed (F-15) | yes | `test_responses.py::test_pin_report_without_a_known_version_is_not_parsed` | `host_behaviour.rs::legacy_status_reports_without_version` | DIV-015 |
| `test_core_rx.py::test_unknown_machine_state_is_swallowed` | Unknown state: report ignored | yes | `test_responses.py::test_unknown_machine_state_is_ignored` | `host_behaviour.rs::status_report_fields` | — |
| `test_core_rx.py::test_idle_during_program_is_reported_as_run` | `Idle` during a job is shown as Run | yes | `test_responses.py::test_lost_oks_are_recovered_when_the_board_reports_an_empty_buffer` | — | — |
| `test_core_rx.py::test_hold_states_depend_on_who_requested_it` | Hold by the user: Hold; by the board: AutoHold; by cooling: Cooling | yes | `test_responses.py::test_hold_requested_by_the_board_is_an_auto_hold`, `test_protocol.py::test_feed_hold_pauses_and_cycle_start_resumes`, `test_jobs.py::test_auto_cooling_holds_the_job_and_resumes_it` | `host_behaviour.rs::hold_states_depend_on_who_requested_them` | — |
| `test_core_rx.py::test_status_change_raises_event_and_updates_last_activity` | Status change event | no: UI (dialogs, events, hotkeys) | — | — | — |

## Overrides

| White-box test | Behaviour | Observable | Portable | Rust | DIV |
| --- | --- | --- | --- | --- | --- |
| `test_core_rx.py::test_overrides_step_towards_target` | One override step per status report towards the targets | yes | `test_responses.py::test_overrides_step_towards_the_targets`, `test_protocol.py::test_overrides_converge_to_targets`, `diff:protocol` | `protocol.rs::overrides_converge_to_targets` | — |
| `test_core_rx.py::test_override_change_raises_event_only_on_change` | Override change event | no: UI (dialogs, events, hotkeys) | — | — | — |
| `test_core_rx.py::test_hotkey_override_targets` | Hotkeys change the targets | no: UI (dialogs, events, hotkeys) | — | — | DIV-104 |

## Jog

| White-box test | Behaviour | Observable | Portable | Rust | DIV |
| --- | --- | --- | --- | --- | --- |
| `test_core_jog.py::test_jog_direction_v11` | `$J=G91` per direction, `$J=G90X0Y0` home | yes | `test_jog.py::test_jog_direction`, `diff:protocol` | `jog.rs::axes_per_direction`, `host_behaviour.rs::jog_variants_v11` | — |
| `test_core_jog.py::test_jog_fast_uses_100000_speed` | 'Fast' jog uses F100000 | no: UI flag; the HostAdapter passes the feed | — | — | — |
| `test_core_jog.py::test_jog_step_is_rounded_to_one_decimal` | Steps formatted with `0.0` (F-22) | yes | `test_jog.py::test_jog_step_is_rounded_to_one_decimal`, `diff:protocol` | `jog.rs::steps_and_speeds`, `host_behaviour.rs::jog_variants_v11` | DIV-022 |
| `test_core_jog.py::test_jog_feed_uses_current_culture` | Jog feed formatted with the current culture (F-21) | no: depends on the C# process culture (the harness runs the invariant one) | `test_jog.py::test_jog_fractional_feed` | `jog.rs::steps_and_speeds` | DIV-021 |
| `test_core_jog.py::test_jog_to_position_v11` | Jog to a position: two decimals | yes | `test_jog.py::test_jog_to_a_position_uses_two_decimals`, `diff:protocol` | `host_behaviour.rs::jog_variants_v11` | — |
| `test_core_jog.py::test_jog_to_position_clamped_by_soft_limits` | Jog to a position clamped by soft limits | yes | `test_jog.py::test_jog_to_a_position_is_clamped_by_the_soft_limits` | `host_behaviour.rs::jog_to_is_clamped_by_soft_limits` | — |
| `test_core_jog.py::test_jog_invalid_directions_throw` | Invalid jog directions throw | no: C# object model, not behaviour | — | — | — |
| `test_core_jog.py::test_jog_ignored_when_not_enabled` | No jog outside Idle/Jog | yes | `test_jog.py::test_jog_is_not_sent_during_a_job` | `host_behaviour.rs::jog_is_refused_when_not_idle` | DIV-103 |
| `test_core_jog.py::test_jog_direction_v09_wraps_in_relative_mode` | Grbl 0.9 jog: `G91`, `G1`, `G90` | yes | `test_jog.py::test_jog_on_grbl_09_is_a_relative_move` | `host_behaviour.rs::jog_on_grbl_09_uses_plain_gcode` | — |
| `test_core_jog.py::test_jog_home_v09` | Grbl 0.9 jog home | yes | `test_jog.py::test_jog_home_and_jog_to_on_grbl_09` | `host_behaviour.rs::jog_on_grbl_09_uses_plain_gcode` | — |
| `test_core_jog.py::test_jog_to_position_v09` | Grbl 0.9 jog to a position | yes | `test_jog.py::test_jog_home_and_jog_to_on_grbl_09` | `host_behaviour.rs::jog_on_grbl_09_uses_plain_gcode` | — |
| `test_core_jog.py::test_jog_enabled_rules_v09` | Grbl 0.9: jog allowed in Run outside a job, not in Jog | yes | — | — | — |
| `test_core_jog.py::test_continuous_jog_not_supported_v09` | No continuous jog on Grbl 0.9 | yes | `test_jog.py::test_continuous_jog_is_not_used_on_grbl_09` | `host_behaviour.rs::jog_on_grbl_09_uses_plain_gcode` | — |
| `test_core_jog.py::test_continuous_jog_direction_is_sent_by_tx_loop` | Continuous jog: a target sent by the TX loop | yes | `test_jog.py::test_continuous_jog_goes_to_the_edge_of_the_table` | `host_behaviour.rs::continuous_jog_sends_targets_and_aborts` | — |
| `test_core_jog.py::test_continuous_jog_targets` | Continuous jog targets the table edges (`G53`) | yes | `test_jog.py::test_continuous_jog_goes_to_the_edge_of_the_table`, `test_jog.py::test_continuous_jog_edges_from_the_settings_table` | `host_behaviour.rs::continuous_jog_sends_targets_and_aborts` | — |
| `test_core_jog.py::test_continuous_jog_z_is_sent_as_step_jog` | Continuous jog: Z is a step jog | yes | `test_jog.py::test_continuous_jog_z_is_a_step_jog` | `host_behaviour.rs::continuous_jog_sends_targets_and_aborts` | — |
| `test_core_jog.py::test_continuous_jog_new_target_aborts_previous` | A new target cancels the previous one (0x85) | yes | `test_jog.py::test_continuous_jog_new_target_cancels_the_previous_one` | `host_behaviour.rs::continuous_jog_sends_targets_and_aborts` | — |
| `test_core_jog.py::test_continuous_jog_abort_sends_jog_cancel_once` | Jog stop sends 0x85 once | yes | `test_jog.py::test_continuous_jog_stop_cancels_once` | `host_behaviour.rs::continuous_jog_sends_targets_and_aborts` | — |
| `test_core_jog.py::test_jog_abort_without_continuous_jog_does_nothing` | Jog stop without continuous jog does nothing | yes | `test_jog.py::test_jog_stop_without_continuous_jog_sends_nothing` | — | — |
| `test_core_jog.py::test_continuous_jog_waits_for_pending_commands` | Continuous jog waits for the pending lines | yes | `test_jog.py::test_continuous_jog_waits_for_the_pending_lines` | — | — |
| `test_core_jog.py::test_continuous_jog_static_api` | ContinuousJog target holder | no: C# object model, not behaviour | — | — | — |

## Configuration ($$, $I, settings table)

| White-box test | Behaviour | Observable | Portable | Rust | DIV |
| --- | --- | --- | --- | --- | --- |
| `test_core_live.py::test_connect_handshake_reset_query_then_config_and_info` | Connect: ctrl-x, `?`, `$$`, `$I`; table and buffer size read | yes | `test_protocol.py::test_connect_sends_soft_reset_then_status_query_then_reads_settings`, `test_protocol.py::test_host_uses_the_rx_buffer_size_reported_by_the_board`, `diff:protocol` | `protocol.rs::connect_sends_soft_reset_then_status_query_then_reads_settings` | — |
| `test_core_live.py::test_connect_without_machine_info_query` | Without `$I` the buffer size comes from `Bf:` | yes | `test_responses.py::test_rx_buffer_size_from_bf_without_machine_info_query` | — | — |
| `test_core_live.py::test_reconnect_with_port_already_open` | Reconnect with the port open | no: transport internals (Mono SerialPort / wrapper) | — | — | — |
| `test_core_live.py::test_partial_config_is_accepted` | A partial `$$` table is accepted | yes | `test_jog.py::test_continuous_jog_edges_from_the_settings_table` | — | — |
| `test_core_live.py::test_config_refresh_rejected_by_device_keeps_old_config` | `$$` rejected: the old table stays | yes | `test_jog.py::test_continuous_jog_edges_from_the_settings_table`, `test_jobs.py::test_custom_code_expressions_without_settings_or_drawing` | `host_behaviour.rs::settings_query_rejected_keeps_the_old_table` | — |
| `test_core_live.py::test_machine_info_rejected_or_malformed` | `$I` rejected or malformed: 127 | yes | `test_responses.py::test_rx_buffer_size_learnt_from_the_board` | — | — |
| `test_core_live.py::test_machine_info_with_small_rx_buffer_keeps_default` | `[OPT:]` without a size: 127 | yes | `test_responses.py::test_rx_buffer_size_learnt_from_the_board` | — | — |
| `test_core_live.py::test_refresh_config_times_out_after_10s_without_answer` | `$$` unanswered for 10 s: timeout, stays pending (F-28) | yes | — | `host_behaviour.rs::settings_refresh_and_timeouts` | DIV-028 |
| `test_core_live.py::test_refresh_machine_info_times_out_after_10s_without_answer` | `$I` unanswered for 10 s | yes | — | `host_behaviour.rs::settings_refresh_and_timeouts` | DIV-028 |
| `test_core_live.py::test_refresh_config_on_demand_and_disabled_info_query` | `$$` on demand; `$I` disabled by the option | yes | `test_jog.py::test_continuous_jog_edges_follow_a_settings_refresh` | `host_behaviour.rs::settings_refresh_and_timeouts` | — |
| `test_core_live.py::test_write_config_success_and_failure` | Settings write: one line each; a rejected one is reported, the rest written | yes | `test_protocol.py::test_write_settings_sends_one_dollar_line_per_setting`, `test_jog.py::test_settings_write_failure_is_reported_and_the_rest_is_written` | `host_behaviour.rs::eeprom_writes_go_one_at_a_time_and_update_the_table` | — |
| `test_core_live.py::test_write_wifi_config_ortur_uses_settings_74_75` | Wi-Fi setup on Ortur: `$74`, `$75`, `$WRS` | yes | — | `host_behaviour.rs::wifi_configuration_by_vendor` | — |
| `test_core_live.py::test_write_wifi_config_longer_uses_radio_commands` | Wi-Fi setup on Longer: `$radio`/`$sta`/`$wifi` | yes | — | `host_behaviour.rs::wifi_configuration_by_vendor` | — |
| `test_core_live.py::test_write_wifi_config_other_vendor_does_nothing` | Wi-Fi setup on other boards does nothing | yes | — | `host_behaviour.rs::wifi_configuration_by_vendor` | — |
| `test_core_live.py::test_write_wifi_config_ortur_requires_idle` | Wi-Fi setup needs Idle | yes | — | `host_behaviour.rs::state_rules_of_immediate_commands` | — |
| `test_core_live.py::test_write_wifi_config_without_known_version_throws` | Wi-Fi setup without a version throws | no: C# exception path (injected fault) | — | — | — |
| `test_core_live.py::test_hotkey_connect_disconnect` | Connect/disconnect hotkeys | no: UI (dialogs, events, hotkeys) | — | — | DIV-104 |
| `test_core_live.py::test_hotkey_manager_glue` | Hotkey manager glue | no: UI (dialogs, events, hotkeys) | — | — | DIV-104 |
| `test_core_live.py::test_translate_enum_and_paths` | Enum translation, data paths | no: UI (dialogs, events, hotkeys) | — | — | — |
| `test_core_live.py::test_translate_enum_error_falls_back_to_name` | Enum translation fallback | no: UI (dialogs, events, hotkeys) | — | — | — |
| `test_core_gaps.py::test_late_settings_and_info_within_500ms_are_collected` | `$$`/`$I` data within 500 ms of the last reply are read | yes | `test_responses.py::test_settings_and_info_replies_after_their_ok` | — | — |
| `test_core_gaps.py::test_settings_arriving_after_500ms_are_missed` | Data later than 500 ms are missed | yes | `test_responses.py::test_settings_and_info_replies_after_their_ok` | — | — |
| `test_core_gaps.py::test_settings_and_info_read_when_ok_comes_first` | `ok` before the data | yes | `test_responses.py::test_settings_and_info_replies_after_their_ok`, `diff:protocol` | `host_behaviour.rs::settings_read_when_ok_comes_first` | — |
| `test_core_gaps.py::test_conf_string_with_version_but_missing_key` | Missing string setting | no: C# object model, not behaviour | — | `grbl_settings.rs::wifi_strings` | — |
| `test_core_types.py::test_version_to_string` | Version text (`1.1f`) | yes | `test_responses.py::test_banner_sets_version_and_vendor` | `version.rs::display_and_ordering` | — |
| `test_core_types.py::test_version_equality_operators_with_nulls` | Version operators with nulls | no: C# object model, not behaviour | — | — | — |
| `test_core_types.py::test_version_ordering` | Version ordering | no: C# object model, not behaviour | — | `version.rs::display_and_ordering` | — |
| `test_core_types.py::test_version_ordering_with_null_left_operand_throws` | Ordering with null throws | no: C# object model, not behaviour | — | — | — |
| `test_core_types.py::test_version_compare_to_other_type_throws` | CompareTo another type throws | no: C# object model, not behaviour | — | — | — |
| `test_core_types.py::test_version_equality_considers_ortur_and_hal_flags` | Version equality and vendor flags | no: C# object model, not behaviour | — | — | — |
| `test_core_types.py::test_version_vendor_flags` | Vendor flags and machine name | yes | `test_responses.py::test_banner_sets_version_and_vendor` | `version.rs::vendor_flags` | DIV-009 |
| `test_core_types.py::test_version_vendor_name_vigotec_is_never_detected` | VendorName 'Vigotec' never detected (F-05) | no: VendorName feeds statistics and UI only | — | `version.rs::vendor_flags` | DIV-005 |
| `test_core_types.py::test_version_clone` | Version clone | no: C# object model, not behaviour | — | — | — |
| `test_core_types.py::test_gpoint_arithmetic_and_equality` | GPoint arithmetic | no: C# object model, not behaviour | — | `status.rs::point_math` | — |
| `test_core_types.py::test_conf_defaults_without_version` | Table defaults (300 x 200, 4000 mm/min...) | yes | `test_jog.py::test_continuous_jog_edges_from_the_settings_table` | `grbl_settings.rs::defaults_without_version` | — |
| `test_core_types.py::test_conf_reads_v11_keys` | Grbl 1.1 keys ($20, $22, $32, $110, $130...) | yes | `test_jog.py::test_continuous_jog_goes_to_the_edge_of_the_table`, `test_jog.py::test_home_is_not_sent_when_homing_is_disabled`, `test_jobs.py::test_auto_cooling_needs_laser_mode` | `grbl_settings.rs::reads_v11_keys_and_clamps` | — |
| `test_core_types.py::test_conf_v09_and_older_key_maps` | 0.9 and 0.8 key maps | yes | — | `grbl_settings.rs::older_versions_use_other_keys` | — |
| `test_core_types.py::test_conf_values_are_clamped` | Values clamped to their range | yes | `test_jog.py::test_continuous_jog_edges_from_the_settings_table` | `grbl_settings.rs::reads_v11_keys_and_clamps` | — |
| `test_core_types.py::test_conf_unparseable_value_uses_regex_then_default` | Unparseable value: number found in the text, else the default | yes | `test_jog.py::test_continuous_jog_edges_from_the_settings_table` | `grbl_settings.rs::unparseable_values_fall_back` | — |
| `test_core_types.py::test_conf_regex_fallback_parses_with_current_culture` | Fallback parsed with the current culture (F-13) | no: depends on the C# process culture | — | `grbl_settings.rs::unparseable_values_fall_back` | DIV-013 |
| `test_core_types.py::test_conf_add_or_update_and_foxalien_cleanup` | `$N=V (description)` cleaned up | yes | `test_jog.py::test_continuous_jog_edges_from_the_settings_table` | `grbl_settings.rs::updates_and_validation` | — |
| `test_core_types.py::test_conf_set_value_if_key_exist` | SetValueIfKeyExist | no: C# object model, not behaviour | — | `grbl_settings.rs::updates_and_validation` | — |
| `test_core_types.py::test_conf_is_set_conf_regex` | IsSetConf regex | no: C# object model, not behaviour | — | — | — |
| `test_core_types.py::test_conf_param_list_and_changes` | Settings dialog list and changes | no: UI (dialogs, events, hotkeys) | — | `grbl_settings.rs::updates_and_validation` | — |
| `test_core_types.py::test_conf_validate_config_protects_ortur_safety_param` | Ortur `$33` protected in the dialog | no: UI (dialogs, events, hotkeys) | — | `grbl_settings.rs::updates_and_validation` | — |
| `test_core_types.py::test_conf_strings_without_version_return_defaults` | String settings without version | no: C# object model, not behaviour | — | `grbl_settings.rs::wifi_strings` | — |
| `test_core_types.py::test_obsolete_conf_reads_values` | Obsolete GrblConf reads values | no: persistence format (BinaryFormatter) | — | — | — |
| `test_core_types.py::test_obsolete_conf_defaults_and_old_versions` | Obsolete GrblConf defaults | no: persistence format (BinaryFormatter) | — | — | — |
| `test_core_types.py::test_obsolete_conf_parsing_and_params` | Obsolete GrblConf parsing | no: persistence format (BinaryFormatter) | — | — | — |
| `test_core_types.py::test_conf_st_converts_from_obsolete_format` | Conversion from the obsolete format | no: persistence format (BinaryFormatter) | — | — | — |
| `test_core_types.py::test_core_configuration_migrates_obsolete_setting` | Stored configuration migration | no: persistence format (BinaryFormatter) | — | — | — |
| `test_core_types.py::test_core_configuration_setter_ignores_empty_config` | An empty table is not stored | no: persistence format (BinaryFormatter) | — | — | — |

## Connection and transport

| White-box test | Behaviour | Observable | Portable | Rust | DIV |
| --- | --- | --- | --- | --- | --- |
| `test_core_live.py::test_rx_reads_trim_and_skip_empty_lines` | Received lines trimmed, empty ones skipped | yes | `test_protocol.py::test_connect_sends_soft_reset_then_status_query_then_reads_settings` | — | — |
| `test_core_live.py::test_rx_io_error_is_retried` | Read IOException retried | no: transport internals (Mono SerialPort / wrapper) | — | — | — |
| `test_core_live.py::test_rx_repeated_io_errors_enable_ch340_mode` | CH340 workaround | no: transport internals (Mono SerialPort / wrapper) | — | — | — |
| `test_core_live.py::test_rx_other_error_closes_the_port` | Other read errors close the port | no: transport internals (Mono SerialPort / wrapper) | — | — | — |
| `test_core_live.py::test_rx_has_data_error_closes_the_port` | HasData error closes the port | no: transport internals (Mono SerialPort / wrapper) | — | — | — |
| `test_core_live.py::test_rx_loop_iteration_parses_one_line` | RX loop iteration | no: transport internals (Mono SerialPort / wrapper) | — | — | — |
| `test_core_live.py::test_rx_loop_null_line_and_errors` | RX loop null line | no: transport internals (Mono SerialPort / wrapper) | — | — | — |
| `test_core_live.py::test_tx_loop_skips_work_when_thread_must_exit` | TX loop exit | no: transport internals (Mono SerialPort / wrapper) | — | — | — |
| `test_core_gaps.py::test_configure_selects_wrapper_type_once` | Transport selection | no: transport internals (Mono SerialPort / wrapper) | — | — | — |
| `test_usbserial.py::test_open_write_read_close` | UsbSerial open/write/read/close on a PTY | no: transport internals (Mono SerialPort / wrapper) | — | `serial_pty.rs::serial_transport_talks_to_the_emulator_on_a_pty` | — |
| `test_usbserial.py::test_writes_and_read_on_closed_port` | Writes on a closed port | no: transport internals (Mono SerialPort / wrapper) | — | — | — |
| `test_usbserial.py::test_read_is_logged_when_com_logger_is_enabled` | COM logger | no: transport internals (Mono SerialPort / wrapper) | — | — | — |
| `test_usbserial.py::test_two_digit_port_name_retries_without_last_digit` | `COM23` retried as `COM2` | no: transport internals (Mono SerialPort / wrapper) | — | — | — |
| `test_usbserial.py::test_two_digit_port_name_retry_failure_rethrows_original_error` | Port retry failure | no: transport internals (Mono SerialPort / wrapper) | — | `serial_pty.rs::opening_a_missing_port_fails` | — |
| `test_usbserial.py::test_missing_port_with_single_digit_fails_silently` | Missing port: silently closed | no: transport internals (Mono SerialPort / wrapper) | — | `serial_pty.rs::opening_a_missing_port_fails` | — |
| `test_usbserial.py::test_marlin_and_hard_reset_settings_raise_dtr_rts` | DTR/RTS for Marlin and hard reset | no: transport internals (Mono SerialPort / wrapper) | — | — | — |
| `test_usbserial.py::test_reset_diagnostics_empty_by_default` | Reset diagnostics string | no: transport internals (Mono SerialPort / wrapper) | — | — | — |
| `test_smoke.py::test_runtime_loads_core_assembly` | The harness loads LaserGRBL | no: harness | — | — | — |
| `test_smoke.py::test_rig_connects_live_to_fake_device` | Live connection to the fake device | yes | `test_protocol.py::test_connect_sends_soft_reset_then_status_query_then_reads_settings` | `protocol.rs::connect_sends_soft_reset_then_status_query_then_reads_settings` | — |

## Firmware variants

| White-box test | Behaviour | Observable | Portable | Rust | DIV |
| --- | --- | --- | --- | --- | --- |
| `test_variants.py::test_marlin_capabilities` | Marlin: synchronous, no settings, no unlock, no `$J=` | yes | `test_firmware_variants.py::test_marlin_polls_the_position_with_m114` | `firmware.rs::capabilities` | — |
| `test_variants.py::test_marlin_queries_position_with_m114_unless_running` | Marlin polls with `M114`, not while running | yes | `test_firmware_variants.py::test_marlin_polls_the_position_with_m114` | `host_behaviour.rs::marlin_polls_with_m114_and_reports_idle_at_the_end` | — |
| `test_variants.py::test_marlin_position_report_sets_idle_and_position` | Marlin position report: Idle and position | yes | `test_firmware_variants.py::test_marlin_polls_the_position_with_m114` | `host_behaviour.rs::marlin_polls_with_m114_and_reports_idle_at_the_end` | — |
| `test_variants.py::test_marlin_malformed_position_report_is_swallowed` | Malformed Marlin report | yes | — | `host_behaviour.rs::marlin_polls_with_m114_and_reports_idle_at_the_end` | — |
| `test_variants.py::test_marlin_status_parsing` | Marlin status from `ok` | yes | — | — | — |
| `test_variants.py::test_marlin_reports_run_while_in_program_and_idle_at_end` | Marlin: Run during a job, Idle at the end | yes | — | `host_behaviour.rs::marlin_polls_with_m114_and_reports_idle_at_the_end` | — |
| `test_variants.py::test_marlin_no_reset_no_unlock_no_config` | Marlin: no soft reset, unlock, `$$`, `$I` | yes | `test_firmware_variants.py::test_marlin_polls_the_position_with_m114` | `host_behaviour.rs::marlin_polls_with_m114_and_reports_idle_at_the_end` | — |
| `test_variants.py::test_marlin_hang_detection_uses_activity_timer` | Marlin hang detection | yes | — | — | — |
| `test_variants.py::test_marlin_streams_synchronously` | Marlin streams synchronously | yes | — | `firmware.rs::capabilities` | — |
| `test_variants.py::test_smoothie_capabilities` | Smoothie: synchronous, no settings, no unlock | yes | `test_firmware_variants.py::test_smoothie_connects_without_soft_reset_and_streams_one_line_at_a_time`, `test_firmware_variants.py::test_smoothie_soft_reset_is_the_reset_command` | `firmware.rs::capabilities` | — |
| `test_variants.py::test_smoothie_start_skips_soft_reset_and_sends_newline_then_query` | Smoothie connect: `\n?`, no ctrl-x | yes | `test_firmware_variants.py::test_smoothie_connects_without_soft_reset_and_streams_one_line_at_a_time` | `host_behaviour.rs::smoothie_skips_soft_reset_sends_newline_and_streams_synchronously` | — |
| `test_variants.py::test_grbl_start_sends_soft_reset_then_query` | Grbl connect: ctrl-x then `?` | yes | `test_protocol.py::test_connect_sends_soft_reset_then_status_query_then_reads_settings` | `protocol.rs::connect_sends_soft_reset_then_status_query_then_reads_settings` | — |
| `test_variants.py::test_grbl_start_without_reset_setting` | Grbl connect without soft reset | yes | `test_protocol.py::test_connect_without_soft_reset_waits_for_the_board_banner` | `protocol.rs::connect_without_soft_reset_waits_for_the_board_banner` | — |
| `test_variants.py::test_smoothie_reset_writes_reset_command` | Smoothie soft reset is `reset` | yes | `test_firmware_variants.py::test_smoothie_soft_reset_is_the_reset_command` | `host_behaviour.rs::smoothie_skips_soft_reset_sends_newline_and_streams_synchronously` | — |
| `test_variants.py::test_smoothie_parses_feed_and_spindle_from_f_field` | Smoothie `F:feed,spindle` | yes | — | `host_behaviour.rs::smoothie_skips_soft_reset_sends_newline_and_streams_synchronously` | — |
| `test_variants.py::test_smoothie_unlock_is_noop` | Smoothie has no unlock | yes | `test_firmware_variants.py::test_smoothie_soft_reset_is_the_reset_command` | `host_behaviour.rs::smoothie_skips_soft_reset_sends_newline_and_streams_synchronously` | DIV-103 |
| `test_variants.py::test_vigo_capabilities` | Vigo: 127 bytes always | yes | — | `host_behaviour.rs::vigo_wraps_jobs_and_uses_sbuf_counters` | — |
| `test_variants.py::test_vigo_queries_with_0x88` | Vigo status query 0x88 | yes | `test_firmware_variants.py::test_vigo_queries_the_status_with_0x88` | `host_behaviour.rs::vigo_wraps_jobs_and_uses_sbuf_counters` | — |
| `test_variants.py::test_vigo_outside_job_marks_commands_ok_immediately` | Vigo outside a job: ok at once, left pending (F-08) | yes | — | `host_behaviour.rs::vigo_wraps_jobs_and_uses_sbuf_counters` | DIV-008 |
| `test_variants.py::test_vigo_job_wraps_program_and_uses_sbuf_counters` | Vigo job wrapper and `SBuf` counters | yes | — | `host_behaviour.rs::vigo_wraps_jobs_and_uses_sbuf_counters` | — |
| `test_variants.py::test_vigo_sbuf_counter_reset_and_job_end_state` | Vigo counter reset | yes | — | `host_behaviour.rs::vigo_wraps_jobs_and_uses_sbuf_counters` | — |
| `test_variants.py::test_vigo_malformed_status_is_swallowed` | Malformed Vigo status | yes | — | `host_behaviour.rs::vigo_wraps_jobs_and_uses_sbuf_counters` | — |
| `test_variants.py::test_vigo_other_lines_use_grbl_parser` | Vigo: other lines as Grbl | yes | — | `host_behaviour.rs::vigo_wraps_jobs_and_uses_sbuf_counters` | — |

## G-code parsing and analysis

| White-box test | Behaviour | Observable | Portable | Rust | DIV |
| --- | --- | --- | --- | --- | --- |
| `test_grblcommand.py::test_command_text_is_trimmed_and_uppercased` | Lines trimmed and upper-cased (current culture, F-52) | yes | `golden:comments_spacing`, `golden:casing`, `diff:gcode` | `command.rs::normalizes_spaces_and_comments` | DIV-052 |
| `test_grblcommand.py::test_preservecase_keeps_original_case` | Custom code keeps the case | yes | `test_jobs.py::test_custom_code_sends_immediates_at_once_and_queues_the_rest` | `command.rs::case_is_kept_on_request` | — |
| `test_grblcommand.py::test_build_helper_collapses_spaces_and_strips_comments` | Spaces collapse, comments removed, spaces around them kept (F-04) | yes | `golden:comments_spacing`, `golden:tokenizer_corners`, `diff:gcode` | `command.rs::normalizes_spaces_and_comments` | DIV-004 |
| `test_grblcommand.py::test_parenthesis_comment_suppresses_letters_inside` | No words inside `(...)` | yes | `golden:comments_spacing`, `golden:tokenizer_corners`, `diff:gcode` | `command.rs::normalizes_spaces_and_comments` | — |
| `test_grblcommand.py::test_semicolon_starts_comment_until_end_of_line` | `;` comments to the end, even inside `(...)` | yes | `golden:comments_spacing`, `golden:tokenizer_corners`, `diff:gcode` | `command.rs::normalizes_spaces_and_comments` | — |
| `test_grblcommand.py::test_unparseable_number_stops_parsing_silently` | A malformed number stops parsing (F-01) | yes | `golden:malformed`, `golden:tokenizer_corners`, `diff:gcode` | `command.rs::malformed_number_stops_parsing_and_keeps_text` | DIV-001 |
| `test_grblcommand.py::test_repeated_letter_keeps_parsing_until_duplicate_key` | A repeated letter stops parsing (F-01) | yes | `golden:malformed`, `diff:gcode` | `command.rs::malformed_number_stops_parsing_and_keeps_text` | DIV-001 |
| `test_grblcommand.py::test_dollar_commands_are_not_parsed_into_elements` | `$` commands are not parsed | yes | `golden:system_commands`, `diff:gcode` | `command.rs::system_commands_are_not_parsed` | — |
| `test_grblcommand.py::test_serial_data_strips_spaces_for_gcode_but_not_for_dollar_commands` | Wire: no spaces, except in `$` commands | yes | `golden:system_commands`, `golden:comments_spacing`, `diff:gcode` | `command.rs::wire_strips_spaces_except_for_system_commands` | — |
| `test_grblcommand.py::test_empty_line_is_empty` | Blank lines | yes | `golden:comments_spacing`, `diff:gcode` | `program.rs::blank_lines_are_skipped_and_comment_lines_kept` | — |
| `test_grblcommand.py::test_build_and_delete_helper` | Parse helper lifecycle | no: C# object model, not behaviour | — | — | — |
| `test_grblcommand.py::test_constructor_from_elements_and_with_prefix_element` | Command from elements | no: C# object model, not behaviour | — | `command.rs::jog_and_composition` | — |
| `test_grblcommand.py::test_element_implicit_conversion_equality_and_hash` | Element conversions | no: C# object model, not behaviour | — | — | — |
| `test_grblcommand.py::test_repeat_count_and_decoded_message` | `(Retry n)` in the console | no: console text only | — | — | — |
| `test_grblcommand.py::test_clone_shares_result_wrapper` | Clone shares the result (F-02) | no: C# object model, not behaviour | — | — | DIV-002 |
| `test_grblcommand.py::test_time_offset_roundtrip` | Time offset storage | no: C# object model, not behaviour | — | — | — |
| `test_grblcommand.py::test_dispose_and_clear_result` | Dispose / clear result | no: C# object model, not behaviour | — | — | — |
| `test_grblcommand.py::test_movement_classification` | Linear, arc and non-moves | yes | `golden:square`, `golden:arcs`, `diff:gcode` | `state.rs::true_movement_and_words` | — |
| `test_grblcommand.py::test_set_wco_and_g_modes` | G92, G4, G90/G91 | yes | `golden:offsets`, `golden:relative`, `golden:dwell_pause`, `diff:gcode` | `state.rs::relative_moves_and_offsets` | — |
| `test_grblcommand.py::test_is_cw_uses_g2_g3_else_previous` | Arc direction (modal) | yes | `golden:arcs`, `golden:arcs_quadrants`, `diff:gcode` | `arc.rs::half_circle_ccw_and_cw` | — |
| `test_grblcommand.py::test_spindle_codes` | M3/M4/M5 | yes | `golden:laser_modes`, `golden:raster_like`, `diff:gcode` | `state.rs::laser_burning_rules` | — |
| `test_grblcommand.py::test_parameter_accessors` | Words T S P X Y Z I J F R | yes | `golden:tokenizer_corners`, `diff:gcode` | `command.rs::words_are_parsed_and_queried` | — |
| `test_grblcommand.py::test_eeprom_write_detection` | `$N=V` detection | yes | `test_jobs.py::test_settings_write_is_sent_alone` | `command.rs::system_commands_are_not_parsed` | — |
| `test_grblcommand.py::test_status_lifecycle` | Command status icons | no: console text only | — | `console.rs::command_status_from_result` | — |
| `test_grblcommand.py::test_result_decoding_uses_error_csv` | `error:N` decoded | no: console text only | — | `console.rs::decoding` | — |
| `test_grblcommand.py::test_result_unknown_error_code_falls_back_to_raw` | Unknown error code | no: console text only | — | `console.rs::decoding` | — |
| `test_grblcommand.py::test_result_when_csv_lookup_throws` | CSV lookup failure | no: C# exception path (injected fault) | — | — | — |
| `test_grblcommand.py::test_good_result_and_erroronly` | Good result text | no: console text only | — | — | — |
| `test_grblcommand.py::test_row_colors` | Console colours | no: UI (dialogs, events, hotkeys) | — | — | — |
| `test_grblcommand.py::test_message_type_detection_and_color` | Message types | no: console text only | — | `console.rs::classification` | — |
| `test_grblcommand.py::test_message_warning_and_diagnostic_types` | Warning/diagnostic rows | no: console text only | — | — | — |
| `test_grblcommand.py::test_message_decodes_config_line_with_csv` | `$N=V` decoded | no: console text only | — | `console.rs::decoding` | — |
| `test_grblcommand.py::test_message_unknown_config_key_keeps_text` | Unknown setting key | no: console text only | — | — | — |
| `test_grblcommand.py::test_message_decodes_alarm_with_csv` | `ALARM:N` decoded | no: console text only | — | `console.rs::decoding` | — |
| `test_grblcommand.py::test_message_unknown_alarm_decodes_to_none` | Unknown alarm decodes to null (F-03) | no: console text only | — | `console.rs::decoding` | DIV-003 |
| `test_grblcommand.py::test_message_decode_exception_is_swallowed` | Decode exception | no: C# exception path (injected fault) | — | — | — |
| `test_grblcommand.py::test_load_appropriate_csv_selects_resource` | CSV per vendor/version | no: console text only | — | — | — |
| `test_grblcommand.py::test_load_appropriate_csv_alarm_and_error_variants` | Alarm/error CSV variants | no: console text only | — | — | — |
| `test_grblcommand.py::test_load_appropriate_csv_unknown_version_falls_back_to_v11` | CSV fallback | no: console text only | — | — | — |
| `test_grblcommand.py::test_load_appropriate_csv_null_version_falls_back_everywhere` | CSV with null version | no: console text only | — | — | — |
| `test_grblcommand.py::test_constructor_from_empty_element_list` | Empty element list | no: C# object model, not behaviour | — | — | — |
| `test_grblcommand.py::test_tooltip_for_good_result_is_empty` | Tooltip | no: UI (dialogs, events, hotkeys) | — | — | — |
| `test_grblcommand.py::test_message_partial_markers_are_others` | Partial markers are 'others' | no: console text only | — | `console.rs::classification` | — |
| `test_statebuilder.py::test_absolute_moves_update_position` | Absolute moves | yes | `golden:square`, `diff:gcode` | `state.rs::relative_moves_and_offsets` | — |
| `test_statebuilder.py::test_relative_moves_accumulate` | Relative moves | yes | `golden:relative`, `diff:gcode` | `state.rs::relative_moves_and_offsets` | — |
| `test_statebuilder.py::test_default_state_before_any_move` | Default state (origin, G90, G0) | yes | `golden:square`, `diff:gcode` | — | — |
| `test_statebuilder.py::test_feed_and_power_are_last_value` | F and S are modal | yes | `golden:raster_like`, `diff:gcode` | — | — |
| `test_statebuilder.py::test_g92_sets_work_offset_and_offsets_later_absolute_moves` | G92 offsets | yes | `golden:offsets`, `diff:gcode` | `state.rs::relative_moves_and_offsets` | — |
| `test_statebuilder.py::test_g92_z_only` | G92 with Z only | yes | `golden:offsets`, `diff:gcode` | — | — |
| `test_statebuilder.py::test_non_movement_commands_do_not_move` | Non-moves keep the position | yes | `golden:dwell_pause`, `diff:gcode` | — | — |
| `test_statebuilder.py::test_jog_command_uses_its_own_distance_mode_and_ignores_modals` | JogCommand analysis | no: used by the C# emulator only | — | `state.rs::jog_commands_move_without_changing_modes` | — |
| `test_statebuilder.py::test_jog_command_strips_dollar_j_prefix` | JogCommand text | no: used by the C# emulator only | — | `command.rs::jog_and_composition` | — |
| `test_statebuilder.py::test_homing_resets_position` | Homing resets the builder | no: used by the C# emulator only | — | — | — |
| `test_statebuilder.py::test_true_movement` | TrueMovement | no: C# object model, not behaviour | — | `state.rs::true_movement_and_words` | — |
| `test_statebuilder.py::test_modal_groups_track_only_their_own_codes` | Modal groups (resume) | yes | `test_jobs.py::test_resume_from_a_position_rebuilds_position_power_and_modes` | `state.rs::settled_modals_skip_motion_and_defaults_not_set` | — |
| `test_statebuilder.py::test_settled_modals_empty_by_default_and_motion_mode_excluded` | Settled modals exclude motion and defaults | yes | `test_jobs.py::test_resume_without_settled_modal_groups_sends_an_empty_line` | `state.rs::settled_modals_skip_motion_and_defaults_not_set` | DIV-019 |
| `test_statebuilder.py::test_modal_element_ignores_unknown_values` | Unknown modal values ignored | yes | — | `state.rs::settled_modals_skip_motion_and_defaults_not_set` | — |
| `test_statebuilder.py::test_distance_mode_property` | G90/G91 | yes | `golden:relative`, `diff:gcode` | `state.rs::relative_moves_and_offsets` | — |
| `test_statebuilder.py::test_g0_time_uses_max_rate_x` | G0 at `$110` | yes | `golden:square`, `golden:feeds`, `diff:gcode` | `state.rs::rapid_uses_max_rate_and_feed_is_capped` | — |
| `test_statebuilder.py::test_g1_time_uses_feed_capped_by_max_rate` | G1 at min(F, `$110`) | yes | `golden:feeds`, `diff:gcode` | `state.rs::rapid_uses_max_rate_and_feed_is_capped` | — |
| `test_statebuilder.py::test_g1_without_feed_takes_no_time` | G1 without F takes no time | yes | `golden:feeds`, `diff:gcode` | `state.rs::rapid_uses_max_rate_and_feed_is_capped` | — |
| `test_statebuilder.py::test_dwell_time_from_p_or_s` | Dwell from P or S | yes | `golden:dwell_pause`, `golden:feeds`, `diff:gcode` | `state.rs::dwell_uses_p_then_s_in_seconds` | — |
| `test_statebuilder.py::test_diagonal_segment_length` | Diagonal length | yes | `golden:square`, `diff:gcode` | — | — |
| `test_statebuilder.py::test_arc_time_uses_arc_length` | Arc time from its length | yes | `golden:arcs`, `diff:gcode` | `arc.rs::half_circle_ccw_and_cw` | — |
| `test_statebuilder.py::test_time_estimates_are_rounded_to_milliseconds` | Times rounded to ms per command | yes | `golden:feeds`, `diff:gcode` | `number.rs::millis_round_like_timespan` | — |
| `test_statebuilder.py::test_compute_false_returns_zero_and_keeps_helper_state` | AnalyzeCommand without timing | no: C# object model, not behaviour | — | — | — |
| `test_statebuilder.py::test_jog_time_uses_g0_rate_because_jog_does_not_set_motion_mode` | Jog time (emulator) | no: used by the C# emulator only | — | — | — |
| `test_statebuilder.py::test_default_config_max_rate` | Default `$110` 4000 | no: the golden layer fixes the configuration | — | `grbl_settings.rs::defaults_without_version` | — |
| `test_statebuilder.py::test_laser_burning_rules` | When the laser burns (drawing range) | yes | `golden:laser_modes`, `golden:raster_like`, `diff:gcode` | `state.rs::laser_burning_rules` | — |
| `test_statebuilder.py::test_laser_burning_without_hardware_pwm_ignores_power` | Without hardware PWM, S0 burns | yes | — | `state.rs::laser_burning_rules` | — |
| `test_statebuilder.py::test_current_alpha` | Preview alpha | no: UI (dialogs, events, hotkeys) | — | — | — |
| `test_statebuilder.py::test_cw_half_circle_bbox_and_length` | CW half circle | yes | `golden:arcs`, `diff:gcode` | `arc.rs::half_circle_ccw_and_cw` | — |
| `test_statebuilder.py::test_ccw_half_circle_bbox` | CCW half circle | yes | `golden:arcs`, `diff:gcode` | `arc.rs::half_circle_ccw_and_cw` | — |
| `test_statebuilder.py::test_full_circle_bbox_is_the_whole_circle` | Full circle | yes | `golden:arcs`, `diff:gcode` | `arc.rs::full_circle_bbox` | — |
| `test_statebuilder.py::test_quarter_arcs_in_every_quadrant` | Quarter arcs in every quadrant | yes | `golden:arcs_quadrants`, `diff:gcode` | `arc.rs::angles_and_quadrants` | — |
| `test_statebuilder.py::test_oblique_arc_angles_cover_all_atan_quadrants` | Oblique arcs | yes | `golden:arcs_quadrants`, `diff:gcode` | `arc.rs::angles_and_quadrants` | — |
| `test_statebuilder.py::test_r_arc_assumes_center_at_chord_midpoint` | R arcs: center at the chord midpoint (F-12) | yes | `golden:arcs`, `golden:arcs_quadrants`, `diff:gcode` | `arc.rs::r_arcs_use_the_chord_midpoint` | DIV-012 |
| `test_statebuilder.py::test_arc_with_only_i_or_only_j` | Arcs with only I or only J | yes | `golden:arcs_quadrants`, `diff:gcode` | — | — |
| `test_statebuilder.py::test_get_quadrant` | Angle quadrant helper | no: C# object model, not behaviour | — | `arc.rs::angles_and_quadrants` | — |
| `test_statebuilder.py::test_arc_helper_builds_helper_when_needed` | Arc helper builds the parse helper | no: C# object model, not behaviour | — | — | — |
| `test_statebuilder.py::test_arc_with_zero_offset_has_zero_radius` | Zero-radius arc | yes | `golden:arcs_quadrants`, `diff:gcode` | — | — |
| `test_statebuilder.py::test_wco_y_only_and_y_only_true_movement` | G92 Y only | yes | `diff:gcode` | — | — |
| `test_statebuilder.py::test_jog_without_feed_uses_modal_feed` | Jog without F (emulator) | no: used by the C# emulator only | — | — | — |
| `test_statebuilder.py::test_g0g1_flag` | G0/G1 flags | yes | `golden:arcs`, `diff:gcode` | — | — |
| `test_grblfile.py::test_load_skips_blank_lines_and_keeps_comment_lines` | Blank lines skipped, comment-only lines kept (F-17) | yes | `golden:comments_spacing`, `diff:gcode` | `program.rs::blank_lines_are_skipped_and_comment_lines_kept` | DIV-017 |
| `test_grblfile.py::test_load_missing_file_gives_empty_program` | A missing file loads as empty | no: the UI only opens existing files | — | — | — |
| `test_grblfile.py::test_append_keeps_previous_commands` | Append import | no: UI (dialogs, events, hotkeys) | — | — | — |
| `test_grblfile.py::test_analysis_ranges_and_time` | Ranges and total time | yes | `golden:square`, `golden:raster_like`, `golden:relative`, `diff:gcode` | `golden.rs::every_golden_file_matches` | — |
| `test_grblfile.py::test_analysis_arc_extends_range_with_its_bbox` | Arcs extend the range with their box | yes | `golden:arcs`, `golden:arcs_quadrants`, `diff:gcode` | `arc.rs::full_circle_bbox` | — |
| `test_grblfile.py::test_analysis_bad_command_aborts_load` | An analysis error stops the analysis (F-53) | yes | `golden:analysis_overflow` | — | DIV-053 |
| `test_grblfile.py::test_quadrant` | Quadrant of the drawing | yes | `golden:negative_quadrant`, `golden:square`, `diff:gcode` | `range.rs::quadrants` | — |
| `test_grblfile.py::test_constructor_with_fake_range_and_clear` | Fake range | no: C# object model, not behaviour | — | — | — |
| `test_grblfile.py::test_check_in_use_without_message_box` | File in use | no: UI (dialogs, events, hotkeys) | — | — | — |
| `test_grblfile.py::test_enumeration_both_interfaces` | Enumeration | no: C# object model, not behaviour | — | — | — |
| `test_grblfile.py::test_formatnumber` | Number formatting for the UI | no: UI (dialogs, events, hotkeys) | — | — | — |
| `test_grblfile.py::test_xy_range_helpers` | XY range helpers | yes | `golden:square`, `diff:gcode` | `range.rs::xy_range_helpers` | — |
| `test_grblfile.py::test_spindle_range_validity_rules` | Power range validity | yes | `golden:laser_modes`, `golden:raster_like`, `diff:gcode` | `range.rs::spindle_range_validity` | — |
| `test_grblfile.py::test_program_range_update_spindle_ignores_null` | Null S ignored | no: C# object model, not behaviour | — | — | — |
| `test_grblfile.py::test_save_gcode_with_header_footer_and_passes` | Save G-code with header/footer/passes | no: no 'save G-code' in FreeKerf yet | — | — | — |
| `test_grblfile.py::test_save_gcode_without_lf_option_uses_platform_newline` | Save with platform newline | no: no 'save G-code' in FreeKerf yet | — | — | — |
| `test_grblfile.py::test_save_gcode_header_expressions_are_evaluated` | Save evaluates expressions | no: no 'save G-code' in FreeKerf yet | — | — | — |
| `test_grblfile.py::test_save_gcode_to_invalid_path_is_silent` | Save to an invalid path | no: no 'save G-code' in FreeKerf yet | — | — | — |
| `test_grblfile.py::test_save_gcode_skips_lines_that_evaluate_to_empty` | Save skips empty lines | no: no 'save G-code' in FreeKerf yet | — | — | — |
| `test_grblfile.py::test_core_reports_file_events_and_resets_projection` | File events | no: UI (dialogs, events, hotkeys) | — | — | DIV-010 |
| `test_grblfile.py::test_core_events_without_subscribers` | Events without subscribers | no: UI (dialogs, events, hotkeys) | — | — | — |
| `test_grblfile.py::test_core_open_file_requires_free_file` | Open needs a free file | no: UI (dialogs, events, hotkeys) | — | — | — |
| `test_grblfile.py::test_core_open_gcode_needs_wait_cursor_ui` | Open shows a wait cursor | no: UI (dialogs, events, hotkeys) | — | — | — |
| `test_grblfile.py::test_core_save_program_and_project_need_a_program` | Save needs a program | no: UI (dialogs, events, hotkeys) | — | — | — |
| `test_grblfile.py::test_core_drawing_events` | Drawing events | no: UI (dialogs, events, hotkeys) | — | — | — |
| `test_grblfile.py::test_core_ui_flags_and_misc` | UI flags | no: UI (dialogs, events, hotkeys) | — | — | — |
| `test_grblfile.py::test_reload_replaces_and_disposes_previous_commands` | Loading replaces the previous file | yes | `test_jobs.py::test_loading_a_file_replaces_the_previous_one` | — | — |
| `test_grblfile.py::test_check_in_use_with_message_box_needs_a_display` | In-use message box | no: UI (dialogs, events, hotkeys) | — | — | — |
| `test_grblfile.py::test_quadrant_mix_when_negative_x_spans_y` | Quadrant Mix | yes | `diff:gcode` | `range.rs::quadrants` | — |
| `test_grblfile.py::test_spindle_range_with_only_negative_values_is_invalid` | Negative-only power range is invalid | yes | `diff:gcode` | `range.rs::spindle_range_validity` | — |
| `test_grblfile.py::test_file_loading_event_is_only_raised_when_loaded_has_subscribers` | OnFileLoading event (F-10) | no: UI (dialogs, events, hotkeys) | — | — | DIV-010 |

## Application glue

| White-box test | Behaviour | Observable | Portable | Rust | DIV |
| --- | --- | --- | --- | --- | --- |
| `test_core_gaps.py::test_open_file_dispatch_never_throws_headless` | Open dispatches by extension to dialogs | no: UI (dialogs, events, hotkeys) | — | — | — |
| `test_core_gaps.py::test_reopen_last_file` | Reopen last file | no: UI (dialogs, events, hotkeys) | — | — | — |
| `test_core_gaps.py::test_project_file_restores_settings_and_opens_each_image` | `.lps` projects (F-11) | no: projects are M2 | — | — | DIV-011 |
| `test_core_gaps.py::test_new_project_is_ignored_without_program_or_history` | New project | no: UI (dialogs, events, hotkeys) | — | — | — |
| `test_core_gaps.py::test_temp_path_is_created_on_first_use` | Temp path | no: UI (dialogs, events, hotkeys) | — | — | — |
| `test_core_gaps.py::test_exe_path_without_entry_assembly` | Executable path | no: UI (dialogs, events, hotkeys) | — | — | — |
| `test_core_gaps.py::test_hotkeys_are_delegated_to_the_manager` | Hotkeys | no: UI (dialogs, events, hotkeys) | — | — | DIV-104 |
| `test_core_gaps.py::test_threading_mode_equals_other_types` | Threading mode type | no: C# object model, not behaviour | — | — | — |
| `test_core_gaps.py::test_set_object_array_against_non_array` | Settings array storage | no: persistence format (BinaryFormatter) | — | — | — |
| `test_core_gaps.py::test_upload_json_separates_multiple_counters` | Statistics upload JSON | no: telemetry | — | — | DIV-027 |

## Settings persistence

| White-box test | Behaviour | Observable | Portable | Rust | DIV |
| --- | --- | --- | --- | --- | --- |
| `test_settings.py::test_get_object_returns_default_for_missing_wrong_type_or_null` | LaserGRBL.Settings store (BinaryFormatter), migrations, RetainedSetting | no: persistence format (BinaryFormatter) | — | `freekerf-settings`, `lib.rs::defaults_round_trip` | — |
| `test_settings.py::test_get_object_swallows_errors` | LaserGRBL.Settings store (BinaryFormatter), migrations, RetainedSetting | no: persistence format (BinaryFormatter) | — | — | — |
| `test_settings.py::test_set_object_triggers_save_only_on_change` | LaserGRBL.Settings store (BinaryFormatter), migrations, RetainedSetting | no: persistence format (BinaryFormatter) | — | — | — |
| `test_settings.py::test_set_object_compares_object_arrays_by_content` | LaserGRBL.Settings store (BinaryFormatter), migrations, RetainedSetting | no: persistence format (BinaryFormatter) | — | — | — |
| `test_settings.py::test_arrays_equal_helper` | LaserGRBL.Settings store (BinaryFormatter), migrations, RetainedSetting | no: persistence format (BinaryFormatter) | — | — | — |
| `test_settings.py::test_get_and_delete_object` | LaserGRBL.Settings store (BinaryFormatter), migrations, RetainedSetting | no: persistence format (BinaryFormatter) | — | — | — |
| `test_settings.py::test_exiting_writes_settings_file_immediately` | LaserGRBL.Settings store (BinaryFormatter), migrations, RetainedSetting | no: persistence format (BinaryFormatter) | — | — | — |
| `test_settings.py::test_save_failure_is_swallowed` | LaserGRBL.Settings store (BinaryFormatter), migrations, RetainedSetting | no: persistence format (BinaryFormatter) | — | — | — |
| `test_settings.py::test_settings_file_is_copied_from_working_directory_when_missing` | LaserGRBL.Settings store (BinaryFormatter), migrations, RetainedSetting | no: persistence format (BinaryFormatter) | — | — | — |
| `test_settings.py::test_graphic_modes` | LaserGRBL.Settings store (BinaryFormatter), migrations, RetainedSetting | no: persistence format (BinaryFormatter) | — | — | — |
| `test_settings.py::test_static_ctor_with_existing_file_reads_previous_version` | LaserGRBL.Settings store (BinaryFormatter), migrations, RetainedSetting | no: persistence format (BinaryFormatter) | — | — | — |
| `test_settings.py::test_static_ctor_without_file_starts_empty` | LaserGRBL.Settings store (BinaryFormatter), migrations, RetainedSetting | no: persistence format (BinaryFormatter) | — | — | — |
| `test_settings.py::test_static_ctor_with_corrupt_file_starts_empty` | LaserGRBL.Settings store (BinaryFormatter), migrations, RetainedSetting | no: persistence format (BinaryFormatter) | — | — | — |
| `test_settings.py::test_new_settings_file_skips_threading_migration` | LaserGRBL.Settings store (BinaryFormatter), migrations, RetainedSetting | no: persistence format (BinaryFormatter) | — | — | — |
| `test_settings.py::test_settings_from_4_6_keep_insane_threading_mode` | LaserGRBL.Settings store (BinaryFormatter), migrations, RetainedSetting | no: persistence format (BinaryFormatter) | — | — | — |
| `test_settings.py::test_retained_setting_reads_default_and_persists_changes` | LaserGRBL.Settings store (BinaryFormatter), migrations, RetainedSetting | no: persistence format (BinaryFormatter) | — | — | — |
| `test_settings.py::test_old_insane_threading_mode_is_migrated_to_fast` | LaserGRBL.Settings store (BinaryFormatter), migrations, RetainedSetting | no: persistence format (BinaryFormatter) | — | — | — |
| `test_settings.py::test_slow_threading_mode_is_kept` | LaserGRBL.Settings store (BinaryFormatter), migrations, RetainedSetting | no: persistence format (BinaryFormatter) | — | — | — |
| `test_settings.py::test_threading_mode_values` | LaserGRBL.Settings store (BinaryFormatter), migrations, RetainedSetting | no: persistence format (BinaryFormatter) | — | — | — |

## Laser life counters

| White-box test | Behaviour | Observable | Portable | Rust | DIV |
| --- | --- | --- | --- | --- | --- |
| `test_lifehandler.py::test_counter_defaults_and_properties` | Laser life counters: time per power class, selection, persistence, statistics upload | no: laser life counters are not on the wire (note 5) | — | `life.rs::power_classes` | — |
| `test_lifehandler.py::test_counter_true_time_classes_and_thresholds` | Laser life counters: time per power class, selection, persistence, statistics upload | no: laser life counters are not on the wire (note 5) | — | `life.rs::power_classes` | — |
| `test_lifehandler.py::test_counter_run_time_update_clone_and_deserialization_fix` | Laser life counters: time per power class, selection, persistence, statistics upload | no: laser life counters are not on the wire (note 5) | — | — | — |
| `test_lifehandler.py::test_list_clone_copies_dates` | Laser life counters: time per power class, selection, persistence, statistics upload | no: laser life counters are not on the wire (note 5) | — | — | — |
| `test_lifehandler.py::test_send_result_class` | Laser life counters: time per power class, selection, persistence, statistics upload | no: laser life counters are not on the wire (note 5) | — | — | — |
| `test_lifehandler.py::test_on_connect_with_single_counter_selects_it` | Laser life counters: time per power class, selection, persistence, statistics upload | no: laser life counters are not on the wire (note 5) | — | `life.rs::selection_on_connect` | — |
| `test_lifehandler.py::test_on_connect_with_one_alive_counter_selects_the_alive_one` | Laser life counters: time per power class, selection, persistence, statistics upload | no: laser life counters are not on the wire (note 5) | — | `life.rs::selection_on_connect` | — |
| `test_lifehandler.py::test_on_connect_ambiguous_needs_the_selector_dialog` | Laser life counters: time per power class, selection, persistence, statistics upload | no: laser life counters are not on the wire (note 5) | — | `host_behaviour.rs::several_laser_modules_ask_the_user` | — |
| `test_lifehandler.py::test_on_connect_without_counters_falls_through_to_dialog` | Laser life counters: time per power class, selection, persistence, statistics upload | no: laser life counters are not on the wire (note 5) | — | `life.rs::selection_on_connect` | DIV-007 |
| `test_lifehandler.py::test_run_time_accumulates_only_in_run_state` | Laser life counters: time per power class, selection, persistence, statistics upload | no: laser life counters are not on the wire (note 5) | — | `life.rs::run_time_only_in_run_and_plausible_deltas`, `host_behaviour.rs::laser_life_counters_follow_the_run_state` | DIV-026 |
| `test_lifehandler.py::test_run_time_ignores_implausible_deltas` | Laser life counters: time per power class, selection, persistence, statistics upload | no: laser life counters are not on the wire (note 5) | — | `life.rs::run_time_only_in_run_and_plausible_deltas` | — |
| `test_lifehandler.py::test_true_time_uses_configured_max_pwm` | Laser life counters: time per power class, selection, persistence, statistics upload | no: laser life counters are not on the wire (note 5) | — | `life.rs::power_classes` | — |
| `test_lifehandler.py::test_true_time_skips_invalid_max_pwm` | Laser life counters: time per power class, selection, persistence, statistics upload | no: laser life counters are not on the wire (note 5) | — | — | — |
| `test_lifehandler.py::test_time_accounting_swallows_errors` | Laser life counters: time per power class, selection, persistence, statistics upload | no: laser life counters are not on the wire (note 5) | — | — | — |
| `test_lifehandler.py::test_add_edit_death_undeath_delete_persist` | Laser life counters: time per power class, selection, persistence, statistics upload | no: laser life counters are not on the wire (note 5) | — | `life.rs::delete_rules` | — |
| `test_lifehandler.py::test_cannot_delete_connected_counter` | Laser life counters: time per power class, selection, persistence, statistics upload | no: laser life counters are not on the wire (note 5) | — | `life.rs::delete_rules` | — |
| `test_lifehandler.py::test_periodic_save_is_throttled` | Laser life counters: time per power class, selection, persistence, statistics upload | no: laser life counters are not on the wire (note 5) | — | — | — |
| `test_lifehandler.py::test_upload_success_records_last_sent` | Laser life counters: time per power class, selection, persistence, statistics upload | no: laser life counters are not on the wire (note 5) | — | — | DIV-027 |
| `test_lifehandler.py::test_upload_rejected_keeps_last_sent` | Laser life counters: time per power class, selection, persistence, statistics upload | no: laser life counters are not on the wire (note 5) | — | — | DIV-027 |
| `test_lifehandler.py::test_upload_skipped_without_url_or_work` | Laser life counters: time per power class, selection, persistence, statistics upload | no: laser life counters are not on the wire (note 5) | — | — | DIV-027 |
| `test_lifehandler.py::test_upload_attempt_is_scheduled_at_most_daily` | Laser life counters: time per power class, selection, persistence, statistics upload | no: laser life counters are not on the wire (note 5) | — | — | DIV-027 |
| `test_lifehandler.py::test_static_ctor_loads_counter_file` | Laser life counters: time per power class, selection, persistence, statistics upload | no: laser life counters are not on the wire (note 5) | — | — | — |
| `test_lifehandler.py::test_static_ctor_falls_back_to_old_file` | Laser life counters: time per power class, selection, persistence, statistics upload | no: laser life counters are not on the wire (note 5) | — | — | — |
| `test_lifehandler.py::test_static_ctor_adds_default_counter_to_empty_list` | Laser life counters: time per power class, selection, persistence, statistics upload | no: laser life counters are not on the wire (note 5) | — | — | — |

## Emulator

| White-box test | Behaviour | Observable | Portable | Rust | DIV |
| --- | --- | --- | --- | --- | --- |
| `test_emulator.py::test_emulator_connects_reports_version_config_and_buffer` | Built-in Grbl 1.1 emulator and its IComWrapper | no: the C# emulator is a device, not the host (note 3) | — | `freekerf-emulator`, `lib.rs::banner_status_and_settings` | — |
| `test_emulator.py::test_emulator_moves_and_reports_position_and_offset` | Built-in Grbl 1.1 emulator and its IComWrapper | no: the C# emulator is a device, not the host (note 3) | — | — | — |
| `test_emulator.py::test_emulator_check_mode_does_not_move` | Built-in Grbl 1.1 emulator and its IComWrapper | no: the C# emulator is a device, not the host (note 3) | — | — | — |
| `test_emulator.py::test_emulator_jog` | Built-in Grbl 1.1 emulator and its IComWrapper | no: the C# emulator is a device, not the host (note 3) | — | — | — |
| `test_emulator.py::test_emulator_homing` | Built-in Grbl 1.1 emulator and its IComWrapper | no: the C# emulator is a device, not the host (note 3) | — | — | — |
| `test_emulator.py::test_emulator_write_config_ok_and_unknown_key_error` | Built-in Grbl 1.1 emulator and its IComWrapper | no: the C# emulator is a device, not the host (note 3) | — | — | — |
| `test_emulator.py::test_emulator_write_config_success` | Built-in Grbl 1.1 emulator and its IComWrapper | no: the C# emulator is a device, not the host (note 3) | — | — | — |
| `test_emulator.py::test_emulator_hold_and_resume` | Built-in Grbl 1.1 emulator and its IComWrapper | no: the C# emulator is a device, not the host (note 3) | — | — | — |
| `test_emulator.py::test_emulator_reset_resends_welcome` | Built-in Grbl 1.1 emulator and its IComWrapper | no: the C# emulator is a device, not the host (note 3) | — | — | — |
| `test_emulator.py::test_emulator_ignores_firmware_probes_and_newline` | Built-in Grbl 1.1 emulator and its IComWrapper | no: the C# emulator is a device, not the host (note 3) | — | — | — |
| `test_emulator.py::test_emulator_log_handler_exception_is_swallowed` | Built-in Grbl 1.1 emulator and its IComWrapper | no: the C# emulator is a device, not the host (note 3) | — | — | — |
| `test_emulator.py::test_emulator_command_exception_drops_the_reply` | Built-in Grbl 1.1 emulator and its IComWrapper | no: the C# emulator is a device, not the host (note 3) | — | — | — |
| `test_emulator.py::test_emulator_configuration_is_persisted_on_close` | Built-in Grbl 1.1 emulator and its IComWrapper | no: the C# emulator is a device, not the host (note 3) | — | — | — |
| `test_emulator.py::test_emulator_direct_api_with_sink` | Built-in Grbl 1.1 emulator and its IComWrapper | no: the C# emulator is a device, not the host (note 3) | — | — | DIV-025 |
| `test_emulator.py::test_emulator_wrapper_reads_and_close_states` | Built-in Grbl 1.1 emulator and its IComWrapper | no: the C# emulator is a device, not the host (note 3) | — | — | DIV-023 |
| `test_emulator.py::test_emulator_pause_blocks_queue_and_send_errors_are_swallowed` | Built-in Grbl 1.1 emulator and its IComWrapper | no: the C# emulator is a device, not the host (note 3) | — | — | — |
| `test_emulator.py::test_emulator_without_log_subscribers` | Built-in Grbl 1.1 emulator and its IComWrapper | no: the C# emulator is a device, not the host (note 3) | — | — | — |
| `test_emulator.py::test_emulator_wrapper_close_by_core` | Built-in Grbl 1.1 emulator and its IComWrapper | no: the C# emulator is a device, not the host (note 3) | — | — | — |

## Observable, not compared yet

| White-box test | Why not yet |
| --- | --- |
| `test_core_gaps.py::test_jog_enabled_legacy_firmware_in_program` | needs a running Grbl 0.9 job with a jog request in the middle (the fake reports Run only with buffered lines) |
| `test_core_rx.py::test_legacy_status_report_status_only` | the fake has no `<Alarm>` 0.9 report |
| `test_core_jog.py::test_jog_enabled_rules_v09` | needs a running Grbl 0.9 board outside a job (the fake reports Run only with buffered lines) |
| `test_core_live.py::test_refresh_config_times_out_after_10s_without_answer` | needs a fake that ignores a line (10 s test); F-28/DIV-028 |
| `test_core_live.py::test_refresh_machine_info_times_out_after_10s_without_answer` | same as above |
| `test_core_live.py::test_write_wifi_config_ortur_uses_settings_74_75` | FreeKerf has no Wi-Fi action yet (`Host::write_wifi` only) |
| `test_core_live.py::test_write_wifi_config_longer_uses_radio_commands` | same as above |
| `test_core_live.py::test_write_wifi_config_other_vendor_does_nothing` | same as above |
| `test_core_live.py::test_write_wifi_config_ortur_requires_idle` | same as above |
| `test_core_types.py::test_conf_v09_and_older_key_maps` | needs a Grbl 0.8 board model in the fake |
| `test_variants.py::test_marlin_malformed_position_report_is_swallowed` | needs a Marlin / Smoothie / Vigo board model in the fake (the fake speaks Grbl) |
| `test_variants.py::test_marlin_status_parsing` | needs a Marlin / Smoothie / Vigo board model in the fake (the fake speaks Grbl) |
| `test_variants.py::test_marlin_reports_run_while_in_program_and_idle_at_end` | needs a Marlin / Smoothie / Vigo board model in the fake (the fake speaks Grbl) |
| `test_variants.py::test_marlin_hang_detection_uses_activity_timer` | needs a Marlin / Smoothie / Vigo board model in the fake (the fake speaks Grbl) |
| `test_variants.py::test_marlin_streams_synchronously` | needs a Marlin / Smoothie / Vigo board model in the fake (the fake speaks Grbl) |
| `test_variants.py::test_smoothie_parses_feed_and_spindle_from_f_field` | needs a Marlin / Smoothie / Vigo board model in the fake (the fake speaks Grbl) |
| `test_variants.py::test_vigo_capabilities` | needs a Marlin / Smoothie / Vigo board model in the fake (the fake speaks Grbl) |
| `test_variants.py::test_vigo_outside_job_marks_commands_ok_immediately` | needs a Marlin / Smoothie / Vigo board model in the fake (the fake speaks Grbl) |
| `test_variants.py::test_vigo_job_wraps_program_and_uses_sbuf_counters` | needs a Marlin / Smoothie / Vigo board model in the fake (the fake speaks Grbl) |
| `test_variants.py::test_vigo_sbuf_counter_reset_and_job_end_state` | needs a Marlin / Smoothie / Vigo board model in the fake (the fake speaks Grbl) |
| `test_variants.py::test_vigo_malformed_status_is_swallowed` | needs a Marlin / Smoothie / Vigo board model in the fake (the fake speaks Grbl) |
| `test_variants.py::test_vigo_other_lines_use_grbl_parser` | needs a Marlin / Smoothie / Vigo board model in the fake (the fake speaks Grbl) |
| `test_statebuilder.py::test_modal_element_ignores_unknown_values` | only through resume; covered by the Rust unit test |
| `test_statebuilder.py::test_laser_burning_without_hardware_pwm_ignores_power` | the golden analyzer has no PWM option |
