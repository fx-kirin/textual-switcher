import gi
import os
import sys
import signal
import subprocess
gi.require_version('Gtk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository.GdkPixbuf import Pixbuf, InterpType
from gi.repository import Gtk, GdkX11, GLib
import webbrowser
import pidfile
import tabcontrol
import glib_wrappers
import windowcontrol
import keycodes
import window_entry
import bookmark_store
import entriestree


class EntryWindow(Gtk.Window):
    WINDOW_TITLE = "Textual Switcher"

    FULL_HELP_TEXT = ("Ctrl+J: Down\n"
                      "Ctrl+K: Up\n"
                      "Ctrl+W/U: Empty search filter\n"
                      "Ctrl+L: First (+reload)\n"
                      "Ctrl+D: Last\n"
                      "Ctrl+Backspace: SIGTERM selected\n"
                      "Ctrl+\\: SIGKILL selected\n"
                      "Ctrl+C: Hide\n"
                      "Ctrl+Space: Toggle expanded mode\n"
                      "Ctrl+H: Toggle Help")
    SHORT_HELP_TEXT = "Ctrl+H: Toggle Help"

    def __init__(self):
        Gtk.Window.__init__(self, title=self.WINDOW_TITLE)
        self._xid = None
        self._windows = {}
        self._tabs = {}
        self._bookmarks = []
        self._entriestree = entriestree.EntriesTree(self._window_selected_callback,
                                                    self._treeview_keypress,
                                                    self._get_tab_icon_callback)
        self._search_textbox = self._create_search_textbox()
        self._select_first_window()
        self._windowcontrol = windowcontrol.WindowControl()
        self._tabcontrol = tabcontrol.TabControl(self._update_tabs_callback, self._tab_icon_ready)
        glib_wrappers.register_signal(self._focus_on_me, signal.SIGHUP)
        self._set_window_properties()
        self._bookmarks_store = bookmark_store.BookmarksStore(self._list_bookmarks_callback,
                                                              self._connected_to_cloud_callback,
                                                              lambda: None)
        self._help_label = self._create_help_label()
        self._status_label = self._create_status_label()
        self._add_gui_components_to_window()
        self._async_list_windows()
        self._expanded_mode = True

    def _set_window_properties(self):
        self.set_size_request(500, 500)
        self.set_position(Gtk.WindowPosition.CENTER)

    def _add_gui_components_to_window(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(vbox)
        vbox.pack_start(self._search_textbox, expand=False, fill=True, padding=0)
        treeview_scroll_wrapper = self._create_treeview_scroll_wrapper()
        vbox.pack_start(treeview_scroll_wrapper, True, True, 0)
        vbox.pack_start(self._status_label, False, True, 0)
        vbox.pack_start(self._help_label, False, True, 0)

    def _create_search_textbox(self):
        search_textbox = Gtk.Entry()
        search_textbox.set_text("")
        search_textbox.connect("changed", self._text_changed_callback)
        search_textbox.connect("key-press-event", self._entry_keypress_callback)
        search_textbox.connect("activate", self._window_selected_callback)
        return search_textbox

    def _create_treeview_scroll_wrapper(self):
        scrollable_treeview = Gtk.ScrolledWindow()
        scrollable_treeview.set_vexpand(True)
        scrollable_treeview.add(self._entriestree.treeview)
        return scrollable_treeview

    def _create_help_label(self):
        label = Gtk.Label()
        label.set_text(self.SHORT_HELP_TEXT)
        label.set_justify(Gtk.Justification.LEFT)
        return label

    def _create_status_label(self):
        label = Gtk.Label()
        label.set_text("Drive: not connected")
        label.set_justify(Gtk.Justification.LEFT)
        return label

    def _focus_on_me(self):
        self.set_visible(True)
        self._windowcontrol.async_focus_on_window(self._get_xid())
        self._async_list_windows()

        self._search_textbox.set_text("")

    def _get_xid(self):
        if self._xid is None:
            try:
                self._xid = self.get_window().get_xid()
            except:
                # No XID yet
                raise
        return self._xid

    def _update_windows_listbox_callback(self, windows):
        windows = [window for window in windows if window.xid != self._get_xid()]
        self._windows = {window.xid: window_entry.WindowEntry(window, entriestree.ICON_SIZE) for window in windows}
        self._entriestree.refresh(self._windows, self._tabs, self._bookmarks, self._expanded_mode)
        self._async_list_tabs_from_windows_list(windows)

    def _tab_icon_ready(self, url, icon):
        # TODO can we refresh this tab list entry only
        self._entriestree.refresh(self._windows, self._tabs, self._bookmarks, self._expanded_mode)

    def _enforce_expanded_mode(self):
        self._entriestree.enforce_expanded_mode(self._expanded_mode)

    def _async_list_tabs_from_windows_list(self, windows):
        active_browsers = [window for window in windows if window.is_browser()]
        active_browsers_pids = [browser.pid for browser in active_browsers]
        stale_browser_pids = [pid for pid in self._tabs if pid not in active_browsers_pids]
        for pid in stale_browser_pids:
            del self._tabs[pid]
        self._tabcontrol.async_list_browsers_tabs(active_browsers)

    def _update_tabs_callback(self, pid, tabs):
        self._tabs[pid] = tabs
        self._entriestree.refresh(self._windows, self._tabs, self._bookmarks, self._expanded_mode)

    def _async_list_windows(self):
        self._windowcontrol.async_list_windows(callback=self._update_windows_listbox_callback)
        self._bookmarks_store.async_list_bookmarks()

    def _select_last_item(self):
        cursor = self._entriestree.treeview.get_cursor()[0]
        if cursor is not None:
            nr_rows = len(self._treefilter)
            self._entriestree.treeview.set_cursor(nr_rows - 1)

    def _select_next_item(self):
        model, _iter = self._entriestree.get_selected_row()
        row = model[_iter]
        if self._expanded_mode:
            try:
                next_row = row.iterchildren().next()
            except:
                next_row = row.next
        else:
            next_row = row.next
        while next_row is None and row is not None:
            next_row = row.next
            if next_row is None:
                row = row.parent
        if next_row is not None:
            self._entriestree.treeview.set_cursor(next_row.path)

    @staticmethod
    def _get_child_of_row(row):
        try:
            child = row.iterchildren().next()
        except StopIteration:
            child = None
        return child

    def _select_previous_item(self):
        model, _iter = self._entriestree.get_selected_row()
        original = current = model[_iter]
        while current.previous is None and current.parent != None:
            current = current.parent
        if original == current and current.previous is not None:
            current = current.previous
            child = self._get_child_of_row(current)
            current_has_children = child is not None
            if current_has_children:
                current = child
                while True:
                    while current.next is not None:
                        current = current.next
                    child = self._get_child_of_row(current)
                    current_has_children = child is not None
                    if current_has_children:
                        current = current.child
                    else:
                        break
        self._entriestree.treeview.set_cursor(current.path)

    def _entry_keypress_callback(self, *args):
        keycode = args[1].get_keycode()[1]
        state = args[1].get_state()
        is_ctrl_pressed = (state & state.CONTROL_MASK).bit_length() > 0
        # Don't switch focus in case of up/down arrow
        if keycode == keycodes.KEYCODE_ARROW_DOWN:
            self._select_next_item()
        elif keycode == keycodes.KEYCODE_ARROW_UP:
            self._select_previous_item()
        elif keycode == keycodes.KEYCODE_ESCAPE:
            sys.exit(0)
        elif is_ctrl_pressed:
            if keycode == keycodes.KEYCODE_D:
                self._select_last_item()
            if keycode == keycodes.KEYCODE_J:
                self._select_next_item()
            elif keycode == keycodes.KEYCODE_K:
                self._select_previous_item()
            elif keycode == keycodes.KEYCODE_C:
                self.set_visible(False)
            elif keycode == keycodes.KEYCODE_L:
                self._async_list_windows()
                self._select_first_window()
            elif keycode == keycodes.KEYCODE_W:
                self._search_textbox.set_text("")
            elif keycode == keycodes.KEYCODE_BACKSPACE:
                self._send_signal_to_selected_process(signal.SIGTERM)
            elif keycode == keycodes.KEYCODE_BACKSLASH:
                self._send_signal_to_selected_process(signal.SIGKILL)
            elif keycode == keycodes.KEYCODE_SPACE:
                self._expanded_mode = not self._expanded_mode
                self._enforce_expanded_mode()
            if keycode == keycodes.KEYCODE_H:
                self._toggle_help_text()
            if keycode == keycodes.KEYCODE_CTRL_PLUS:
                self._add_selection_as_bookmark()
            if keycode == keycodes.KEYCODE_CTRL_HYPEN:
                self._remove_selected_bookmark()

    def _treeview_keypress(self, *args):
        keycode = args[1].get_keycode()[1]
        if keycode not in (keycodes.KEYCODE_ARROW_UP, keycodes.KEYCODE_ARROW_DOWN):
            self._search_textbox.grab_focus()

    def _is_some_window_selected(self):
        _, _iter = self._entriestree.get_selected_row()
        return _iter is not None

    def _window_selected_callback(self, *_):
        record_type = self._entriestree.get_value_of_selected_row(entriestree.COL_NR_RECORD_TYPE)
        if record_type in (entriestree.RECORD_TYPE_BROWSER_TAB, entriestree.RECORD_TYPE_WINDOW):
            window_id = self._entriestree.get_value_of_selected_row(entriestree.COL_NR_WINDOW_ID)
            if window_id is None:
                return
            try:
                self._windowcontrol.focus_on_window(window_id)
                # Setting the window to not visible causes Alt+Tab to avoid switcher (which is good)
                self.set_visible(False)
            except subprocess.CalledProcessError:
                # Actual window list has changed since last reload
                self._async_list_windows()
            tab_id = self._entriestree.get_value_of_selected_row(entriestree.COL_NR_TAB_ID)
            is_tab = tab_id >= 0
            if is_tab:
                window = self._windows[window_id]
                self._tabcontrol.async_move_to_tab(tab_id, window.get_pid())
        elif record_type == entriestree.RECORD_TYPE_BOOKMARK_ENTRY:
            url = selected_window_id = self._entriestree.get_value_of_selected_row(entriestree.COL_NR_URL)
            webbrowser.open(url)

    def _text_changed_callback(self, search_textbox):
        search_key = search_textbox.get_text()
        search_key = search_key.decode('utf-8')
        self._entriestree.update_search_key(search_key)
        self._entriestree.treefilter.refilter()
        if not self._is_some_window_selected():
            self._select_first_window()
        self._enforce_expanded_mode()
        if len(self._entriestree.tree):
            self._entriestree.select_first_tab_under_selected_window()

    def _select_first_window(self):
        self._entriestree.select_first_window()

    def _send_signal_to_selected_process(self, signal_type):
        window_id = self._entriestree.get_value_of_selected_row(entriestree.COL_NR_WINDOW_ID)
        window = self._windows[window_id]
        os.kill(window.get_pid(), signal_type)
        self._async_list_windows()

    def _toggle_help_text(self):
        if self._help_label.get_text() == self.SHORT_HELP_TEXT:
            self._help_label.set_text(self.FULL_HELP_TEXT)
        else:
            self._help_label.set_text(self.SHORT_HELP_TEXT)

    def _connected_to_cloud_callback(self):
        print("Connected to cloud")

    def _disconnected_from_cloud_callback(self):
        print("Disconnected from cloud")

    def _list_bookmarks_callback(self, bookmarks):
        def update_bookmarks():
            self._bookmarks = bookmarks
            self._entriestree.refresh(self._windows, self._tabs, self._bookmarks, self._expanded_mode)
            return False

        GLib.timeout_add(0, update_bookmarks)

    def _add_selection_as_bookmark(self):
        url = selected_window_id = self._entriestree.get_value_of_selected_row(entriestree.COL_NR_URL)
        title = selected_window_id = self._entriestree.get_value_of_selected_row(entriestree.COL_NR_TITLE)
        self._bookmarks_store.add_bookmark(url, title)

    def _get_tab_icon_callback(self, tab):
        return self._tabcontrol.get_tab_icon(tab)


def show_window(window):
    window.connect("delete-event", Gtk.main_quit)
    window.show_all()
    window.realize()


if __name__ == "__main__":
    # Not using an argument parser to not waste time in latency
    if len(sys.argv) != 2:
        print("Please specify the PID file as an argument")
        sys.exit(1)

    pid_filepath = sys.argv[1]
    pidfile.create(pid_filepath)

    window = EntryWindow()
    show_window(window)

    Gtk.main()
