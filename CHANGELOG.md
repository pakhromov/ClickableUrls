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
