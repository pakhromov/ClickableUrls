import html
import sublime
import sublime_plugin
import webbrowser
import threading


class UrlHighlighter(sublime_plugin.EventListener):
    # Thanks Jeff Atwood http://www.codinghorror.com/blog/2008/10/the-problem-with-urls.html
    # ^ that up here is a URL that should be matched
    URL_REGEX = "\\bhttps?://[-A-Za-z0-9+&@#/%?=~_()|!:,.;']*[-A-Za-z0-9+&@#/%=~_(|]"
    DEFAULT_MAX_URLS = 200
    SETTINGS_FILENAME = 'ClickableUrls.sublime-settings'

    urls_for_view = {}
    scopes_for_view = {}
    phantom_sets_for_view = {}
    ignored_views = []
    browser = None
    highlight_semaphore = threading.Semaphore()
    pending_open = {}

    def on_activated(self, view):
        self.update_url_highlights(view)

    # Blocking handlers for ST2
    def on_load(self, view):
        if sublime.version() < '3000':
            self.update_url_highlights(view)

    def on_modified(self, view):
        if sublime.version() < '3000':
            self.update_url_highlights(view)

    # Async listeners for ST3
    def on_load_async(self, view):
        self.update_url_highlights_async(view)

    def on_modified_async(self, view):
        self.update_url_highlights_async(view)

    def on_close(self, view):
        for map in [self.urls_for_view, self.scopes_for_view, self.ignored_views]:
            if view.id() in map:
                del map[view.id()]
        UrlHighlighter.pending_open.pop(view.id(), None)
        self._clear_phantoms(view)

    def on_selection_modified(self, view):
        if view.id() in UrlHighlighter.pending_open and not all(s.empty() for s in view.sel()):
            UrlHighlighter.pending_open.pop(view.id(), None)

    def on_post_text_command(self, view, command_name, args):
        if command_name != 'drag_select':
            return
        if not sublime.load_settings(UrlHighlighter.SETTINGS_FILENAME).get('open_on_click', False):
            return
        vid = view.id()
        UrlHighlighter.pending_open.pop(vid, None)
        if args and (args.get('extend') or args.get('additive') or args.get('by')):
            return
        if not view.sel():
            return
        pt = view.sel()[0].begin()
        for region in UrlHighlighter.urls_for_view.get(vid, []):
            if region.begin() < pt < region.end():
                url = view.substr(region)
                UrlHighlighter.pending_open[vid] = url
                sublime.set_timeout(lambda: self._open_pending(vid, url), 300)
                return

    def _open_pending(self, vid, url):
        if UrlHighlighter.pending_open.get(vid) == url:
            UrlHighlighter.pending_open.pop(vid, None)
            open_url(url)

    """The logic entry point. Find all URLs in view, store and highlight them"""
    def update_url_highlights(self, view):
        settings = sublime.load_settings(UrlHighlighter.SETTINGS_FILENAME)
        should_highlight_urls = settings.get('highlight_urls', True)
        max_url_limit = settings.get('max_url_limit', UrlHighlighter.DEFAULT_MAX_URLS)

        if view.id() in UrlHighlighter.ignored_views:
            return

        urls = view.find_all(UrlHighlighter.URL_REGEX)

        # Avoid slowdowns for views with too much URLs
        if len(urls) > max_url_limit:
            print("UrlHighlighter: ignoring view with %u URLs" % len(urls))
            UrlHighlighter.ignored_views.append(view.id())
            return

        UrlHighlighter.urls_for_view[view.id()] = urls

        should_highlight_urls = sublime.load_settings(UrlHighlighter.SETTINGS_FILENAME).get('highlight_urls', True)
        if (should_highlight_urls):
            self.highlight_urls(view, urls)

        if sublime.load_settings(UrlHighlighter.SETTINGS_FILENAME).get('show_phantom', False):
            self._show_phantoms(view, urls)
        else:
            self._clear_phantoms(view)

    """Same as update_url_highlights, but avoids race conditions with a
    semaphore."""
    def update_url_highlights_async(self, view):
        UrlHighlighter.highlight_semaphore.acquire()
        try:
            self.update_url_highlights(view)
        finally:
            UrlHighlighter.highlight_semaphore.release()

    """Creates a set of regions from the intersection of urls and scopes,
    underlines all of them."""
    def highlight_urls(self, view, urls):
        color_scope = sublime.load_settings(UrlHighlighter.SETTINGS_FILENAME).get('underline_color', '')
        if color_scope:
            self.underline_regions(view, color_scope, urls)
            self.update_view_scopes(view, [color_scope])
        else:
            # We need separate regions for each lexical scope for ST to use a proper color for the underline
            scope_map = {}
            for url in urls:
                scope_name = view.scope_name(url.a)
                scope_map.setdefault(scope_name, []).append(url)

            for scope_name in scope_map:
                self.underline_regions(view, scope_name, scope_map[scope_name])

            self.update_view_scopes(view, scope_map.keys())

    """Apply underlining with provided scope name to provided regions.
    Uses the empty region underline hack for Sublime Text 2 and native
    underlining for Sublime Text 3."""
    def underline_regions(self, view, scope_name, regions):
        if sublime.version() >= '3019':
            style = sublime.load_settings(UrlHighlighter.SETTINGS_FILENAME).get('underline_style', 'solid')
            style_flag = {
                'solid':    sublime.DRAW_SOLID_UNDERLINE,
                'stippled': sublime.DRAW_STIPPLED_UNDERLINE,
                'squiggly': sublime.DRAW_SQUIGGLY_UNDERLINE,
            }.get(style, sublime.DRAW_SOLID_UNDERLINE)
            view.add_regions(
                u'clickable-urls ' + scope_name,
                regions,
                scope_name,
                flags=sublime.DRAW_NO_FILL|sublime.DRAW_NO_OUTLINE|style_flag)
        else:
            # in Sublime Text 2, the 'empty region underline' hack is used
            char_regions = [sublime.Region(pos, pos) for region in regions for pos in range(region.a, region.b)]
            view.add_regions(
                u'clickable-urls ' + scope_name,
                char_regions,
                scope_name,
                sublime.DRAW_EMPTY_AS_OVERWRITE)

    def _show_phantoms(self, view, urls):
        settings = sublime.load_settings(UrlHighlighter.SETTINGS_FILENAME)
        icon = settings.get('phantom_icon', '\U0001f517')
        color = settings.get('phantom_color', '')
        size = settings.get('phantom_size', '')
        style = 'text-decoration: none;'
        if color:
            style += ' color: {};'.format(color)
        if size:
            style += ' font-size: {};'.format(size)
        vid = view.id()
        if vid not in UrlHighlighter.phantom_sets_for_view:
            UrlHighlighter.phantom_sets_for_view[vid] = sublime.PhantomSet(view, 'clickable-urls-phantoms')
        phantoms = []
        for region in urls:
            url = view.substr(region)
            phantoms.append(sublime.Phantom(
                sublime.Region(region.end()),
                '<a href="{}" style="{}">{}</a>'.format(html.escape(url, quote=True), style, html.escape(icon)),
                sublime.LAYOUT_INLINE,
                on_navigate=open_url,
            ))
        UrlHighlighter.phantom_sets_for_view[vid].update(phantoms)

    def _clear_phantoms(self, view):
        vid = view.id()
        if vid in UrlHighlighter.phantom_sets_for_view:
            UrlHighlighter.phantom_sets_for_view[vid].update([])
            del UrlHighlighter.phantom_sets_for_view[vid]

    """Store new set of underlined scopes for view. Erase underlining from
    scopes that were used but are not anymore."""
    def update_view_scopes(self, view, new_scopes):
        old_scopes = UrlHighlighter.scopes_for_view.get(view.id(), None)
        if old_scopes:
            unused_scopes = set(old_scopes) - set(new_scopes)
            for unused_scope_name in unused_scopes:
                view.erase_regions(u'clickable-urls ' + unused_scope_name)

        UrlHighlighter.scopes_for_view[view.id()] = new_scopes



def open_url(url):
    browser = sublime.load_settings(UrlHighlighter.SETTINGS_FILENAME).get('clickable_urls_browser') or None
    try:
        webbrowser.get(browser).open(url, autoraise=True)
    except(webbrowser.Error):
        sublime.error_message('Failed to open browser. See "Customizing the browser" in the README.')

class OpenUrlUnderCursorCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        if self.view.id() in UrlHighlighter.urls_for_view:
            for selection in self.view.sel():
                if selection.empty():
                    selection = next((url for url in UrlHighlighter.urls_for_view[self.view.id()] if url.contains(selection)), None)
                    if not selection:
                        return
                url = self.view.substr(selection)
                open_url(url)


class OpenAllUrlsCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        if self.view.id() in UrlHighlighter.urls_for_view:
            for url in set([self.view.substr(url_region) for url_region in UrlHighlighter.urls_for_view[self.view.id()]]):
                open_url(url)
