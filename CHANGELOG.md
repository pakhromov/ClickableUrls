## 2.1.0

* Added phantom icons: a clickable inline icon after each URL, controlled by `show_phantom` (on by default), `phantom_icon`, `phantom_color` and `phantom_size`
* Added an `open_url_on_click` command, so a mouse binding can open URLs on button *release* rather than press (see "Opening URLs with a single click" in the README)
* Added `max_file_size`, which ignores documents above a given size without scanning them at all, regardless of how many URLs they contain
* Added `debounce_ms`, which rescans once typing stops instead of on every keystroke
* Added a confirmation prompt to "Open all URLs", which previously opened every URL at once with no warning
* Dropped ST2 and ST3 support, the plugin now uses Python 3.8
* `underline_color` now takes an explicit scope name. Per-syntax-scope tracking has been removed, so an empty value no longer makes each URL inherit the color of its surrounding scope
* Performance: settings are loaded once rather than re-read on every event, scanning is debounced and kept off the UI thread


## 2.0.1

* Added `.gitattributes` to exclude `screenshot.png` from the installed package
* Menu and Command Palette now open Settings and Key Bindings in split view via `edit_settings`
* Renamed "Clickable URLs: Settings" to "Preferences: Clickable URLs Settings" and added "Preferences: Clickable URLs Key Bindings" to match Package Control naming conventions

## 2.0.0

* Added `underline_color` setting to override the underline color with a fixed scope (e.g. `region.bluish`)
* Added `underline_style` setting to choose between `solid`, `stippled`, and `squiggly` underlines
* Added `open_on_click` setting to open URLs with a single left click
* Added "Clickable URLs: Settings" to the Command Palette, opening a split view with default and user settings
* Fixed: empty `clickable_urls_browser` setting caused a silent failure

## 1.3.0 "Need For Speed"

* **The name for the command is now `open_url_under_cursor` to avoid clash with the built-in `open_url` command**
* Performance improvements in Sublime Text 3 - use native highlighting, background processing.
* Well tested on Windows and in Sublime Text 2, bugs fixed.
* Handled issue with URLs not being highlighted when the editor is opened with "Remember Files" #16
* Added license #19
