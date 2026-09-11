import html
import sublime
import sublime_plugin
import webbrowser
import threading


class UrlHighlighter(sublime_plugin.EventListener):
    # Thanks Jeff Atwood http://www.codinghorror.com/blog/2008/10/the-problem-with-urls.html
    # ^ that up here is a URL that should be matched
    URL_REGEX = "\\bhttps?://[-A-Za-z0-9+&@#/%?=~_()|!:,.;']*[-A-Za-z0-9+&@#/%=~_(|]"
    SETTINGS_FILENAME = 'ClickableUrls.sublime-settings'

    urls_for_buffer = {}
    drawn_for_view = {}
    phantom_sets_for_view = {}
    ignored_buffers = set()
    edit_generation = {}
    highlight_semaphore = threading.Semaphore()
    settings = None
    pending_url = None

    def on_activated_async(self, view):
        if not _decorations_enabled():
            return
        self.update_url_highlights_async(view)

    def on_load_async(self, view):
        if not _decorations_enabled():
            return
        self.update_url_highlights_async(view)

    def on_modified_async(self, view):
        if not _decorations_enabled():
            return
        delay = UrlHighlighter.settings.get('debounce_ms')
        if not delay:
            self.update_url_highlights_async(view)
            return

        # Typing fires this per keystroke, so rescan once the edits stop rather
        # than once per character. Every keystroke bumps the generation, which
        # retires the callback the previous one scheduled.
        view_id = view.id()
        generation = UrlHighlighter.edit_generation.get(view_id, 0) + 1
        UrlHighlighter.edit_generation[view_id] = generation
        sublime.set_timeout_async(
            lambda: self._update_latest_edit(view, view_id, generation),
            delay)

    def _update_latest_edit(self, view, view_id, generation):
        # Stale if another keystroke landed since, or if the view has closed
        if UrlHighlighter.edit_generation.get(view_id) != generation:
            return
        self.update_url_highlights_async(view)

    def on_pre_close(self, view):
        UrlHighlighter.edit_generation.pop(view.id(), None)
        UrlHighlighter.drawn_for_view.pop(view.id(), None)
        UrlHighlighter.urls_for_buffer.pop(view.buffer_id(), None)
        UrlHighlighter.ignored_buffers.discard(view.buffer_id())
        self._clear_phantoms(view)

    def on_selection_modified(self, view):
        if UrlHighlighter.pending_url and not all(s.empty() for s in view.sel()):
            UrlHighlighter.pending_url = None

    def on_post_text_command(self, view, command_name, args):
        if command_name != 'drag_select':
            return
        if not UrlHighlighter.settings.get('open_on_click'):
            return
        UrlHighlighter.pending_url = None
        if args and (args.get('extend') or args.get('additive') or args.get('by')):
            return
        if not view.sel():
            return
        pt = view.sel()[0].begin()
        for region in UrlHighlighter.urls_for(view):
            if region.begin() < pt < region.end():
                url = view.substr(region)
                UrlHighlighter.pending_url = url
                sublime.set_timeout(lambda: _open_pending(url), 300)
                return

    @staticmethod
    def _ignore(view, reason):
        """Retire a buffer for good. Every entry point goes through urls_for,
        so this is all it takes to stop the plugin touching it again."""
        print(f'UrlHighlighter: ignoring view with {reason}')
        UrlHighlighter.ignored_buffers.add(view.buffer_id())
        UrlHighlighter.urls_for_buffer.pop(view.buffer_id(), None)

    @staticmethod
    def urls_for(view):
        """The buffer's URLs, memoized per revision. Keyed by buffer so clones
        and split panes share a single scan, and used by the on-demand path
        when highlighting and phantoms are both off. The single gateway to
        every URL this plugin knows about, so both limits are enforced here."""
        buffer_id = view.buffer_id()
        if buffer_id in UrlHighlighter.ignored_buffers:
            return []

        # Checked before the scan, so a huge file is never read at all
        if view.size() > UrlHighlighter.settings.get('max_file_size'):
            UrlHighlighter._ignore(view, f'{view.size()} characters')
            return []

        change_count = view.change_count()
        stamp, urls = UrlHighlighter.urls_for_buffer.get(buffer_id, (None, None))
        if stamp != change_count:
            urls = view.find_all(UrlHighlighter.URL_REGEX)
            # Avoid slowdowns for views with too much URLs
            if len(urls) > UrlHighlighter.settings.get('max_url_limit'):
                UrlHighlighter._ignore(view, f'{len(urls)} URLs')
                return []
            UrlHighlighter.urls_for_buffer[buffer_id] = (change_count, urls)
        return urls

    def update_url_highlights(self, view):
        """The logic entry point. Find all URLs in view, store and highlight them"""
        if view.buffer_id() in UrlHighlighter.ignored_buffers:
            return

        # Returns [] on the call that trips a limit, which erases whatever was
        # drawn before; every later call stops at the check above
        urls = UrlHighlighter.urls_for(view)

        # Drawing is per view, so each clone of a buffer needs its own check
        if urls == UrlHighlighter.drawn_for_view.get(view.id()):
            return

        UrlHighlighter.drawn_for_view[view.id()] = urls

        if UrlHighlighter.settings.get('highlight_urls'):
            self.highlight_urls(view, urls)

        if UrlHighlighter.settings.get('show_phantom'):
            self._show_phantoms(view, urls)

    def update_url_highlights_async(self, view):
        """Same as update_url_highlights, but avoids race conditions with a
        semaphore."""
        UrlHighlighter.highlight_semaphore.acquire()
        try:
            self.update_url_highlights(view)
        finally:
            UrlHighlighter.highlight_semaphore.release()

    def highlight_urls(self, view, urls):
        style_flag = {
            'solid':    sublime.DRAW_SOLID_UNDERLINE,
            'stippled': sublime.DRAW_STIPPLED_UNDERLINE,
            'squiggly': sublime.DRAW_SQUIGGLY_UNDERLINE,
        }.get(UrlHighlighter.settings.get('underline_style'), sublime.DRAW_SOLID_UNDERLINE)
        view.add_regions(
            'clickable-urls',
            urls,
            UrlHighlighter.settings.get('underline_color'),
            flags=sublime.DRAW_NO_FILL|sublime.DRAW_NO_OUTLINE|style_flag)

    def _show_phantoms(self, view, urls):
        icon = UrlHighlighter.settings.get('phantom_icon')
        style = 'text-decoration: none;'
        if color := UrlHighlighter.settings.get('phantom_color'):
            style += f' color: {html.escape(color, quote=True)};'
        if size := UrlHighlighter.settings.get('phantom_size'):
            style += f' font-size: {html.escape(size, quote=True)};'
        if view.id() not in UrlHighlighter.phantom_sets_for_view:
            UrlHighlighter.phantom_sets_for_view[view.id()] = sublime.PhantomSet(view, 'clickable-urls-phantoms')
        phantoms = []
        for region in urls:
            phantoms.append(sublime.Phantom(
                sublime.Region(region.end()),
                f'<a href="{html.escape(view.substr(region), quote=True)}" style="{style}">{html.escape(icon)}</a>',
                sublime.LAYOUT_INLINE,
                on_navigate=open_url,
            ))
        UrlHighlighter.phantom_sets_for_view[view.id()].update(phantoms)

    def _clear_phantoms(self, view):
        if view.id() in UrlHighlighter.phantom_sets_for_view:
            UrlHighlighter.phantom_sets_for_view[view.id()].update([])
            del UrlHighlighter.phantom_sets_for_view[view.id()]


# With both off there is nothing to draw, so the buffer is never scanned on
# load, activation or edit - only on demand, when a command asks for a URL.
def _decorations_enabled():
    return (UrlHighlighter.settings.get('highlight_urls')
            or UrlHighlighter.settings.get('show_phantom'))


# Drop every cached result, clear whatever the new settings turned off, then
# redraw, so a settings change takes effect immediately instead of waiting for
# the next edit. This is the only moment a clear is needed, which keeps the
# per-edit path down to the features that are actually on.
def _refresh_all_views():
    # Runs on the main thread while on_*_async may be mid-update, so hold the
    # semaphore across the whole refresh - the caches are dropped here, and a
    # concurrent update would otherwise write a stale result back into them.
    # update_url_highlights is called unwrapped because the semaphore is not
    # reentrant.
    UrlHighlighter.highlight_semaphore.acquire()
    try:
        UrlHighlighter.urls_for_buffer.clear()
        UrlHighlighter.drawn_for_view.clear()
        UrlHighlighter.ignored_buffers.clear()
        UrlHighlighter.edit_generation.clear()
        highlighter = UrlHighlighter()
        enabled = _decorations_enabled()
        for window in sublime.windows():
            for view in window.views(include_transient=True):
                if not UrlHighlighter.settings.get('highlight_urls'):
                    view.erase_regions('clickable-urls')
                if not UrlHighlighter.settings.get('show_phantom'):
                    highlighter._clear_phantoms(view)
                if enabled:
                    highlighter.update_url_highlights(view)
    finally:
        UrlHighlighter.highlight_semaphore.release()


def plugin_loaded():
    UrlHighlighter.settings = sublime.load_settings(UrlHighlighter.SETTINGS_FILENAME)
    UrlHighlighter.settings.add_on_change('clickable-urls', _refresh_all_views)
    # Off the UI thread, onto the same thread the on_*_async scans run on
    sublime.set_timeout_async(_refresh_all_views, 0)


def plugin_unloaded():
    if UrlHighlighter.settings is not None:
        UrlHighlighter.settings.clear_on_change('clickable-urls')
    highlighter = UrlHighlighter()
    for window in sublime.windows():
        for view in window.views(include_transient=True):
            view.erase_regions('clickable-urls')
            highlighter._clear_phantoms(view)
    UrlHighlighter.urls_for_buffer.clear()
    UrlHighlighter.drawn_for_view.clear()
    UrlHighlighter.ignored_buffers.clear()
    UrlHighlighter.edit_generation.clear()
    UrlHighlighter.pending_url = None


def _open_pending(url):
    if UrlHighlighter.pending_url == url:
        UrlHighlighter.pending_url = None
        open_url(url)


def open_url(url):
    browser = UrlHighlighter.settings.get('clickable_urls_browser') or None
    try:
        webbrowser.get(browser).open(url)
    except webbrowser.Error:
        sublime.error_message('Failed to open browser. See "Customizing the browser" in the README.')


class OpenUrlOnClickCommand(sublime_plugin.TextCommand):
    def want_event(self):
        return True

    def run(self, edit, event=None):
        UrlHighlighter.pending_url = None
        if event:
            pt = self.view.window_to_text((event['x'], event['y']))
        elif self.view.sel():
            pt = self.view.sel()[0].begin()
        else:
            return
        for region in UrlHighlighter.urls_for(self.view):
            if region.begin() < pt < region.end():
                url = self.view.substr(region)
                UrlHighlighter.pending_url = url
                sublime.set_timeout(lambda: _open_pending(url), 300)
                return


class OpenUrlUnderCursorCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        urls = UrlHighlighter.urls_for(self.view)
        for selection in self.view.sel():
            if selection.empty():
                selection = next((url for url in urls if url.contains(selection)), None)
                if not selection:
                    continue
            open_url(self.view.substr(selection))


class OpenAllUrlsCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        urls = {self.view.substr(region) for region in UrlHighlighter.urls_for(self.view)}
        if not urls:
            return
        if not sublime.ok_cancel_dialog(f'Open {len(urls)} URLs?', 'Open'):
            return
        for url in urls:
            open_url(url)
