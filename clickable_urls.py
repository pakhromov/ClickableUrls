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
    ignored_views = set()
    highlight_semaphore = threading.Semaphore()
    pending_url = None

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
        UrlHighlighter.urls_for_view.pop(view.id(), None)
        UrlHighlighter.scopes_for_view.pop(view.id(), None)
        UrlHighlighter.ignored_views.discard(view.id())
        self._clear_phantoms(view)

    def on_selection_modified(self, view):
        if UrlHighlighter.pending_url and not all(s.empty() for s in view.sel()):
            UrlHighlighter.pending_url = None

    def on_post_text_command(self, view, command_name, args):
        if command_name != 'drag_select':
            return
        if not sublime.load_settings(UrlHighlighter.SETTINGS_FILENAME).get('open_on_click', False):
            return
        UrlHighlighter.pending_url = None
        if args and (args.get('extend') or args.get('additive') or args.get('by')):
            return
        if not view.sel():
            return
        pt = view.sel()[0].begin()
        for region in UrlHighlighter.urls_for_view.get(view.id(), []):
            if region.begin() < pt < region.end():
                url = view.substr(region)
                UrlHighlighter.pending_url = url
                sublime.set_timeout(lambda: _open_pending(url), 300)
                return

    """The logic entry point. Find all URLs in view, store and highlight them"""
    def update_url_highlights(self, view):
        settings = sublime.load_settings(UrlHighlighter.SETTINGS_FILENAME)

        if view.id() in UrlHighlighter.ignored_views:
            return

        urls = view.find_all(UrlHighlighter.URL_REGEX)

        # Avoid slowdowns for views with too much URLs
        if len(urls) > settings.get('max_url_limit', UrlHighlighter.DEFAULT_MAX_URLS):
            print("UrlHighlighter: ignoring view with %u URLs" % len(urls))
            UrlHighlighter.ignored_views.add(view.id())
            return

        if urls == UrlHighlighter.urls_for_view.get(view.id()):
            return

        UrlHighlighter.urls_for_view[view.id()] = urls

        if settings.get('highlight_urls', True):
            self.highlight_urls(view, urls, settings)
        else:
            for scope_name in UrlHighlighter.scopes_for_view.get(view.id()) or []:
                view.erase_regions('clickable-urls ' + scope_name)

        if settings.get('show_phantom', False):
            self._show_phantoms(view, urls, settings)
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
    def highlight_urls(self, view, urls, settings):
        color_scope = settings.get('underline_color', '')
        if color_scope:
            self.underline_regions(view, color_scope, urls, settings)
            self.update_view_scopes(view, [color_scope])
        else:
            # We need separate regions for each lexical scope for ST to use a proper color for the underline
            scope_map = {}
            for url in urls:
                scope_name = view.scope_name(url.a)
                scope_map.setdefault(scope_name, []).append(url)

            for scope_name in scope_map:
                self.underline_regions(view, scope_name, scope_map[scope_name], settings)

            self.update_view_scopes(view, list(scope_map.keys()))

    """Apply underlining with provided scope name to provided regions.
    Uses the empty region underline hack for Sublime Text 2 and native
    underlining for Sublime Text 3."""
    def underline_regions(self, view, scope_name, regions, settings):
        if sublime.version() >= '3019':
            style_flag = {
                'solid':    sublime.DRAW_SOLID_UNDERLINE,
                'stippled': sublime.DRAW_STIPPLED_UNDERLINE,
                'squiggly': sublime.DRAW_SQUIGGLY_UNDERLINE,
            }.get(settings.get('underline_style', 'solid'), sublime.DRAW_SOLID_UNDERLINE)
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

    def _show_phantoms(self, view, urls, settings):
        icon = settings.get('phantom_icon', '\U0001f517')
        color = settings.get('phantom_color', '')
        size = settings.get('phantom_size', '')
        style = 'text-decoration: none;'
        if color:
            style += ' color: {};'.format(color)
        if size:
            style += ' font-size: {};'.format(size)
        if view.id() not in UrlHighlighter.phantom_sets_for_view:
            UrlHighlighter.phantom_sets_for_view[view.id()] = sublime.PhantomSet(view, 'clickable-urls-phantoms')
        phantoms = []
        for region in urls:
            phantoms.append(sublime.Phantom(
                sublime.Region(region.end()),
                '<a href="{}" style="{}">{}</a>'.format(html.escape(view.substr(region), quote=True), style, html.escape(icon)),
                sublime.LAYOUT_INLINE,
                on_navigate=open_url,
            ))
        UrlHighlighter.phantom_sets_for_view[view.id()].update(phantoms)

    def _clear_phantoms(self, view):
        if view.id() in UrlHighlighter.phantom_sets_for_view:
            UrlHighlighter.phantom_sets_for_view[view.id()].update([])
            del UrlHighlighter.phantom_sets_for_view[view.id()]

    """Store new set of underlined scopes for view. Erase underlining from
    scopes that were used but are not anymore."""
    def update_view_scopes(self, view, new_scopes):
        old_scopes = UrlHighlighter.scopes_for_view.get(view.id())
        if old_scopes:
            for unused_scope_name in set(old_scopes) - set(new_scopes):
                view.erase_regions(u'clickable-urls ' + unused_scope_name)

        UrlHighlighter.scopes_for_view[view.id()] = new_scopes



def _open_pending(url):
    if UrlHighlighter.pending_url == url:
        UrlHighlighter.pending_url = None
        open_url(url)


def open_url(url):
    browser = sublime.load_settings(UrlHighlighter.SETTINGS_FILENAME).get('clickable_urls_browser') or None
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
        for region in UrlHighlighter.urls_for_view.get(self.view.id(), []):
            if region.begin() < pt < region.end():
                url = self.view.substr(region)
                UrlHighlighter.pending_url = url
                sublime.set_timeout(lambda: _open_pending(url), 300)
                return


class OpenUrlUnderCursorCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        if self.view.id() in UrlHighlighter.urls_for_view:
            for selection in self.view.sel():
                if selection.empty():
                    selection = next((url for url in UrlHighlighter.urls_for_view[self.view.id()] if url.contains(selection)), None)
                    if not selection:
                        return
                open_url(self.view.substr(selection))


class OpenAllUrlsCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        if self.view.id() in UrlHighlighter.urls_for_view:
            for url in {self.view.substr(url_region) for url_region in UrlHighlighter.urls_for_view[self.view.id()]}:
                open_url(url)
