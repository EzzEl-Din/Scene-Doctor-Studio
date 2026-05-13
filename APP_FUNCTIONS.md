# Scene Doctor Studio — App Functions Reference

Complete list of all functions, classes, and methods across all modules.

---

## main.py — Main Application Window

### Top-Level Functions

| Function | Description |
|----------|-------------|
| `resource_path(filename)` | Returns absolute path to bundled resources (works in dev + PyInstaller EXE) |
| `needs_code_writer(user_message)` | Smart intent detection — returns True if user wants code (imperative commands, confirmations) |
| `is_scan_request(user_message)` | Returns True if user wants a scan/diagnostic (not code) |
| `main()` | App entry point — creates QApplication and StudioWindow |

### Classes

#### `GetSceneInfoWorker(QThread)`
Background thread to get scene name/path from DCC.
- `__init__(self, dcc)` — Initialize with DCC key
- `run(self)` — Executes scene info query

#### `DCCWorker(QThread)`
Generic background thread for DCC operations (scan, screenshot, etc).
- `__init__(self, fn, *args)` — Initialize with callable + args
- `run(self)` — Executes the function

#### `ToggleSwitch(QWidget)`
Custom animated toggle switch widget (iOS-style).
- `get_anim_pos() / set_anim_pos(value)` — Animation property
- `isChecked() / setChecked(value)` — Get/set state
- `mousePressEvent(event)` — Toggle on click
- `paintEvent(event)` — Custom drawing (track + knob)

#### `PlusMenuPopup(QWidget)`
The "+" button popup menu with toggles and actions.
- `_setup_ui()` — Build popup layout
- `_make_row(key, label, has_warning, is_action)` — Create a menu row
- `_on_action(key)` — Handle action items (viewport image)
- `_on_toggle(key, checked)` — Handle toggle changes (search, steps, autorun, plan)
- `_apply_popup_theme()` — Update colors on theme change
- `set_toggle(key, value)` — Sync toggle state
- `show_at(pos)` — Position and show popup

#### `DCCTabStrip(QWidget)`
DCC filter tabs (All / Maya / Blender) in sidebar.
- `_make_tab_btn(key, label)` — Create a tab button
- `_make_dcc_icon_btn(dcc)` — Create DCC icon button
- `_apply_dcc_theme(t)` — Update theme
- `_on_tab_clicked(dcc)` — Handle tab selection
- `add_dcc(dcc)` — Add a new DCC tab

#### `PluginStoreWindow(QDialog)`
Plugin/addon store dialog.
- `_setup_ui()` — Build store layout
- `_make_plugin_card(dcc_key, info, is_installed)` — Create plugin card
- `_install_plugin(dcc_key, info)` — Install a plugin

#### `StudioWindow(QMainWindow)` — Main Application

**UI Construction:**
- `_build_ui()` — Build entire UI (sidebar, chat, input, artifacts panel)
- `_build_collapsed_sidebar()` — Build the 56px collapsed sidebar rail

**Theme & Styling:**
- `_apply_theme(theme_name)` — Apply dark/light theme to all widgets
- `_apply_sidebar_button_theme(button, t)` — Style sidebar buttons
- `_apply_collapsed_sidebar_theme(t)` — Style collapsed sidebar icons
- `_restyle_chat_messages()` — Re-style all chat bubbles on theme change
- `_apply_input_theme()` — Style input panel
- `_apply_plus_btn_theme()` — Style + button
- `_apply_scan_buttons_theme()` — Style scan buttons
- `_apply_global_palette()` — Set QPalette for placeholder text
- `_darken(hex_color, factor)` — Darken a hex color

**Sidebar:**
- `_toggle_sidebar()` — Animate sidebar expand/collapse (260px ↔ 56px)
- `_restore_sidebar_state()` — Restore sidebar state from settings
- `_create_sidebar_panel_icon()` — Draw custom sidebar toggle icon
- `_make_icon_button(icon_text, tooltip, callback)` — Create collapsed sidebar icon button
- `_make_sidebar_btn(icon, text, callback)` — Create expanded sidebar button
- `_sidebar_icon_style()` — Get sidebar icon button stylesheet
- `_filter_sessions(query)` — Filter session list by search query
- `_expand_to_search()` — Expand sidebar and focus search bar

**Sessions:**
- `_load_sessions_list()` — Load and display all sessions in sidebar
- `_on_dcc_filter_changed(dcc)` — Filter sessions by DCC
- `_select_session(session_id)` — Switch to a session
- `_render_chat_history()` — Render all messages in current session
- `_on_new_session()` — Create new session (auto-detects DCC)
- `_on_dccs_detected(dccs)` — Handle DCC detection results
- `_finish_new_session(dcc, info)` — Complete session creation
- `_session_context_menu(session_id, pos)` — Right-click menu (rename/delete)

**Chat & Messaging:**
- `_on_send()` — Handle send button / Enter key
- `_add_bubble(role, text)` — Add a chat bubble (user/assistant/analyzer/codewriter)
- `_add_system_msg(text)` — Add a system message
- `_scroll_to_bottom()` — Scroll chat to latest message
- `_build_session_context()` — Build [SESSION CONTEXT] block for AI
- `_build_user_message(text)` — Prepend session context + profile to user message
- `_clear_current_chat()` — Clear all messages in current session
- `_classify_intent(content, has_image)` — Classify message intent (vision/analyze/fix)

**AI Streaming:**
- `_start_ai(user_text, has_image, is_scan)` — Start AI response generation
- `_start_worker(messages, agent_settings, search_mode)` — Launch StreamWorker thread
- `_on_token(token)` — Handle streaming token (append to bubble)
- `_on_done()` — Handle AI response complete (artifact detection, auto-run, handoff)
- `_on_error(msg)` — Handle AI error
- `_reset_busy()` — Reset busy state
- `_on_busy_timeout()` — Safety timeout (90s) resets busy state

**DCC Operations:**
- `_on_scan()` — Full scene scan
- `_on_scan_done(success, result)` — Handle scan results
- `_on_quick_check()` — Scan selection (detailed mesh + animation check)
- `_on_quick_check_done(success, output)` — Handle selection scan results
- `_on_screenshot()` — Take viewport screenshot
- `_run_code(code)` — Execute code in connected DCC
- `_set_dcc_loading(label)` — Show loading state on send button
- `_clear_dcc_loading()` — Restore send button
- `_update_connection_indicator()` — Update green/red connection dot
- `_show_dcc_setup()` — Open DCC setup dialog

**Artifacts:**
- `_should_create_artifact(response, user_message)` — Smart detection (structural, not keyword)
- `_detect_artifact_type(response)` — Detect file type (python/svg/mermaid/markdown)
- `_extract_artifact_content(response)` — Extract code/content from response
- `_generate_artifact_name(ext)` — Generate meaningful filename from user message
- `_maybe_create_artifact(response)` — Create artifact if detection passes
- `_create_artifact_card_widget(fpath, art_id, file_type, ext, line_count)` — Create artifact card in chat
- `_on_view_artifacts()` — Toggle artifacts panel
- `_animate_artifacts_panel(close)` — Smooth open/close animation
- `_refresh_artifacts_panel()` — Refresh artifact list
- `_open_artifact_in_viewer(fpath)` — Open artifact in viewer pane
- `_show_code_in_viewer(code)` — Display code in viewer
- `_show_markdown_in_viewer(md_text)` — Display markdown in viewer
- `_copy_artifact_content()` — Copy current artifact to clipboard
- `_run_artifact_code()` — Execute .py artifact in DCC
- `_download_artifact(fpath)` — Save artifact to user-chosen location
- `_download_all_artifacts()` — Export all artifacts as zip

**Modes & Toggles:**
- `_show_plus_menu()` — Show + button popup
- `_toggle_search_mode(checked)` — Toggle web search mode
- `_web_search(query)` — Search DuckDuckGo HTML for solutions
- `_toggle_step_mode(checked)` — Toggle step-by-step mode (persistent)
- `_toggle_plan_mode(checked)` — Toggle plan mode (persistent)
- `_toggle_auto_run(checked)` — Toggle auto-run code mode
- `_show_mode_menu()` — Show Normal/Thinking mode popup
- `_set_mode(mode)` — Set AI mode (normal/thinking)
- `_auto_execute_blocks(code_blocks)` — Auto-run code blocks

**Input:**
- `eventFilter(obj, event)` — Handle Enter/Shift+Enter in input field
- `_auto_resize_input()` — Auto-expand input field (36px–120px)
- `_on_image_pasted(image)` — Handle pasted/dropped images
- `dragEnterEvent(event)` — Accept image drag
- `dropEvent(event)` — Handle image drop
- `keyPressEvent(event)` — Global keyboard shortcuts (Ctrl+K, Ctrl+B)

**Tokens:**
- `_estimate_tokens(text)` — Estimate token count (~4 chars/token)
- `_update_token_count()` — Recalculate session tokens
- `_update_token_display()` — Update token label color (gray/orange/red)

**Other:**
- `_on_settings()` — Open settings dialog
- `_on_doc_mode_toggled(checked)` — Toggle documentation mode
- `_show_plugin_store()` — Open plugin store
- `_sanitize_node_names(code)` — Strip pipe characters from Maya node names
- `_clean_response_for_display(response)` — Strip think tags, mode prefixes
- `_strip_display_markers(text)` — Remove internal markers
- `_get_previous_user_message()` — Get last user message for context
- `_agentic_check()` — Post-execution verification (deprecated)
- `_pulse_loading()` — Animate loading indicator

---

## ui_widgets.py — Reusable UI Components

| Function/Class | Description |
|----------------|-------------|
| `set_theme(theme_name)` | Set active theme (updates COLORS dict) |
| `get_app_stylesheet()` | Get global QSS stylesheet |

#### `ChatLineEdit(QLineEdit)`
Custom line edit with Enter-to-send behavior.

#### `MessageBubble(QFrame)`
Chat message bubble with role-based styling.
- `set_text(text)` — Set full message text
- `append_text(token)` — Append streaming token
- `finalize()` — Finalize message (render code blocks)
- `_render_code_blocks()` — Extract and render code block widgets

#### `CodeBlockWidget(QFrame)`
Code block with Run/Dismiss buttons.
- `_on_run()` — Execute code in DCC (with double-run guard)
- `_dismiss()` — Hide the code block
- `show_result(success, message)` — Show execution result

#### `SessionItemWidget(QFrame)`
Session list item in sidebar.
- `set_selected(sel)` — Highlight as selected
- `set_expanded(expanded)` — Show/hide details
- `update_theme(theme)` — Update colors

#### `TypingIndicator(QWidget)`
Animated typing indicator ("Thinking...", "Writing code...").

---

## ai_backend.py — AI Communication

| Function/Class | Description |
|----------------|-------------|
| `_build_agent_defaults(agent_key)` | Build default settings for an agent |
| `migrate_settings(data)` | Migrate old settings format to V3 |
| `detect_language(text)` | Detect message language (en/ar/etc) |

#### `StreamWorker(QThread)`
Streams AI responses token-by-token.
- `stop()` — Stop streaming
- `run()` — Main execution (routes to Ollama or OpenAI)
- `_stream_ollama()` — Stream from local Ollama
- `_stream_openai()` — Stream from OpenAI-compatible API
- `_with_system()` — Prepend system prompt to messages

#### `SummaryWorker(QThread)`
Generates conversation summaries.
- `run()` — Generate summary
- `_build_messages()` — Build summary prompt
- `_call_ollama() / _call_openai()` — Call respective backends

---

## dcc_connector.py — DCC Communication

| Function | Description |
|----------|-------------|
| `_check_port(dcc, port, timeout)` | Check if DCC port is open |
| `is_dcc_connected(dcc)` | Check if specific DCC is connected |
| `detect_connected_dccs()` | Detect all connected DCCs |
| `detect_connected_dcc()` | Detect first connected DCC |
| `_send_maya(code)` | Send Python code to Maya via commandPort |
| `_send_blender(code)` | Send Python code to Blender via socket |
| `send_code(dcc, code)` | Send code to any DCC (routes to Maya/Blender) |
| `get_scene_info(dcc)` | Get scene name and file path |
| `take_screenshot(dcc)` | Capture viewport screenshot (base64) |
| `run_scan(dcc)` | Run full scene health scan |

#### `DetectDCCWorker(QThread)`
Background thread to detect connected DCCs.

---

## session_manager.py — Session Storage

| Function | Description |
|----------|-------------|
| `_ensure_dir(dcc)` | Ensure session directories exist |
| `_session_folder(dcc, session_id)` | Get session folder path |
| `_artifacts_folder(dcc, session_id)` | Get artifacts folder path |
| `_generate_artifact_id()` | Generate unique artifact ID |
| `_detect_artifact_extension(content)` | Detect file extension from content |
| `_should_extract_artifact(content)` | Check if content should be an artifact |
| `_extract_artifacts(content, dcc, session_id)` | Extract and save artifacts |
| `_load_artifact(dcc, session_id, artifact_id)` | Load artifact content |
| `_reconstruct_content(message, dcc, session_id)` | Reconstruct message with artifacts |
| `_migrate_flat_sessions()` | Migrate old flat JSON sessions to new format |
| `_migrate_single_session(old_path, data, dcc, session_id)` | Migrate one session |
| `get_session_id(dcc, scene_path)` | Generate session ID from scene path |
| `get_session_path(dcc, scene_name, session_id)` | Get session file path |
| `create_session(dcc, scene_name, scene_path)` | Create new session |
| `save_session(session_data)` | Save session to disk |
| `load_all_sessions()` | Load all sessions for sidebar |
| `load_session(session_id)` | Load specific session |
| `delete_session(session_id)` | Delete session and artifacts |
| `rename_session(session_id, new_name)` | Rename a session |
| `add_message(session_data, role, content, image_b64)` | Add message to session |

---

## studio_settings_dialog.py — Settings UI

#### `SettingsDialog(QDialog)`
Settings dialog with tabs for each agent + profile.
- `_build()` — Build dialog layout
- `_on_mode()` — Handle mode change (single/multi)
- `_set_accent(color)` — Set accent color
- `_pick_custom_accent()` — Open color picker
- `_build_tab(ak)` — Build agent config tab
- `_build_profile_tab()` — Build "About You" profile tab
- `_append_to_profile(text)` — Quick-add chip to profile
- `_copy_all()` — Copy config to all agents
- `_save()` — Save settings
- `get_settings()` — Return current settings dict

---

## blender_addon.py — Blender Socket Server Addon

Runs a TCP socket server inside Blender that receives and executes Python code from Scene Doctor Studio.

---

## File Structure

```
Documents/SceneDoctor/
├── settings.json          # App settings
└── sessions/
    ├── maya/
    │   └── <session_id>/
    │       ├── chat.json      # Chat history
    │       └── artifacts/     # Saved artifacts (.py, .md, .svg)
    └── blender/
        └── <session_id>/
            ├── chat.json
            └── artifacts/
```
