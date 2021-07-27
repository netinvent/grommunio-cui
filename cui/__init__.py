#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2021 grommunio GmbH
import subprocess
import sys
from asyncio.events import AbstractEventLoop
from pathlib import Path
from typing import Any, List, Tuple, Dict, Union
import os

import yaml
from yaml import SafeLoader
from getpass import getuser
from scroll import ScrollBar, Scrollable
from button import GButton, GBoxButton
from menu import MenuItem, MultiMenuItem
from gwidgets import GText, GEdit
from interface import ApplicationHandler, WidgetDrawer
import util
from urwid.widget import SPACE
from urwid import AttrWrap, ExitMainLoop, Padding, Columns, ListBox, Frame, LineBox, SimpleListWalker, \
    MainLoop, LEFT, CENTER, Filler, Pile, Button, connect_signal, AttrMap, GridFlow, Overlay, Widget, \
    Terminal, SimpleFocusListWalker, set_encoding, MIDDLE, TOP, RadioButton, ListWalker, raw_display, \
    RELATIVE_100
from systemd import journal
import datetime
import time


# print(sys.path)
try:
    import asyncio
except ImportError:
    import trollius as asyncio

_PRODUCTIVE: bool = True
loop: AbstractEventLoop
_MAIN: str = 'MAIN'
_MAIN_MENU: str = 'MAIN-MENU'
_TERMINAL: str = 'TERMINAL'
_LOGIN: str = 'LOGIN'
_REBOOT: str = 'REBOOT'
_SHUTDOWN: str = 'SHUTDOWN'
_NETWORK_CONFIG_MENU: str = 'NETWORK-CONFIG-MENU'
_UNSUPPORTED: str = 'UNSUPPORTED'
_PASSWORD: str = 'PASSWORD'
_DEVICE_CONFIG: str = 'DEVICE-CONFIG'
_IP_CONFIG: str = 'IP-CONFIG'
_IP_ADDRESS_CONFIG: str = 'IP-ADDRESS-CONFIG'
_DNS_CONFIG: str = 'DNS-CONFIG'
_MESSAGE_BOX: str = 'MESSAGE-BOX'
_INPUT_BOX: str = 'INPUT-BOX'
_LOG_VIEWER: str = 'LOG-VIEWER'
_ADMIN_WEB_PW: str = 'ADMIN-WEB-PW'
_TIMESYNCD: str = 'TIMESYNCD'


class Application(ApplicationHandler):
    """
    The console UI. Main application class.
    """
    current_window: str = _MAIN
    current_window_input_box: str = ""
    message_box_caller: str = ''
    _message_box_caller_body: Widget = None
    input_box_caller: str = ''
    _input_box_caller_body: Widget = None
    last_input_box_value: str = ""
    log_file_caller: str = ''
    _log_file_caller_body: Widget = None
    current_event = None
    current_bottom_info = 'Idle'
    menu_items: List[str] = []
    layout: Frame
    debug: bool = False
    quiet: bool = False
    current_menu_state: int = -1
    maybe_menu_state: int = -1
    active_device: str = 'lo'
    active_ips: Dict[str, List[Tuple[str, str, str, str]]] = {}
    config: Dict[str, Any] = {}
    timesyncd_vars: Dict[str, str] = {}
    log_units: Dict[str, Dict[str, str]] = {}
    current_log_unit: int = 0
    log_line_count: int = 200
    log_finished: bool = False

    _current_kbdlayout = util.get_current_kbdlayout()

    # The default color palette
    _current_colormode: str = 'light'

    # The hidden input string
    _hidden_input: str = ""
    _hidden_pos: int = 0

    def __init__(self):
        # MAIN Page
        set_encoding('utf-8')
        self.screen = raw_display.Screen()
        self.old_termios = self.screen.tty_signal_keys()
        self.blank_termios = ['undefined' for bla in range(0, 5)]
        self.screen.tty_signal_keys(*self.blank_termios)
        self.prepare_mainscreen()

        # Loop
        self._loop = MainLoop(
            self._body,
            util.get_palette(self._current_colormode),
            unhandled_input=self.handle_event,
            screen=self.screen,
            handle_mouse=False
        )
        self._loop.set_alarm_in(1, self.update_clock)
        # self._loop.screen.set_terminal_properties(colors=256)

        # Login Dialog
        self.login_header = AttrMap(GText(('header', 'Login'), align='center'), 'header')
        self.user_edit = GEdit(("Username: ",), edit_text=getuser(), edit_pos=0)
        self.pass_edit = GEdit("Password: ", edit_text="", edit_pos=0, mask='*')
        self.login_body = Pile([
            self.user_edit,
            # AttrMap(self.user_edit, 'MMI.selectable', 'MMI.focus'),
            self.pass_edit,
        ])
        login_button = GBoxButton("Login", self.check_login)
        connect_signal(login_button, 'click', lambda button: self.handle_event('login enter'))
        # self.login_footer = GridFlow([login_button], 10, 1, 1, 'center')
        self.login_footer = AttrMap(Columns([GText(""), login_button, GText("")]), 'buttonbar')

        # Common OK Button
        # self.ok_button = GButton("OK", self.press_button, left_end='[', right_end=']')
        self.ok_button = GBoxButton("OK", self.press_button)
        connect_signal(self.ok_button, 'click', lambda button: self.handle_event('ok enter'))
        self.ok_button = (8, self.ok_button)
        self.ok_button_footer = AttrMap(Columns([
            ('weight', 1, GText('')),
            ('weight', 1, Columns([('weight', 1, GText('')), self.ok_button, ('weight', 1, GText(''))])),
            ('weight', 1, GText(''))
        ]), 'buttonbar')

        # Common Cancel Button
        self.cancel_button = GBoxButton("Cancel", self.press_button)
        connect_signal(self.cancel_button, 'click', lambda button: self.handle_event('cancel enter'))
        self.cancel_button = (12, self.cancel_button)
        self.cancel_button_footer = GridFlow([self.cancel_button[1]], 10, 1, 1, 'center')

        # Common Close Button
        self.close_button = GBoxButton("Close", self.press_button)
        connect_signal(self.close_button, 'click', lambda button: self.handle_event('close enter'))
        self.close_button = (11, self.close_button)
        # self.close_button_footer = GridFlow([self.close_button], 10, 1, 1, 'center')
        self.close_button_footer = AttrMap(Columns([
            ('weight', 1, GText('')),
            ('weight', 1, Columns([('weight', 1, GText('')), self.close_button, ('weight', 1, GText(''))])),
            ('weight', 1, GText(''))
        ]), 'buttonbar')

        # Common Add Button
        self.add_button = GBoxButton("Add", self.press_button)
        connect_signal(self.add_button, 'click', lambda button: self.handle_event('add enter'))
        self.add_button = (9, self.add_button)
        self.add_button_footer = GridFlow([self.add_button[1]], 10, 1, 1, 'center')

        # Common Edit Button
        self.edit_button = GBoxButton("Edit", self.press_button)
        connect_signal(self.edit_button, 'click', lambda button: self.handle_event('edit enter'))
        self.edit_button = (10, self.edit_button)
        self.edit_button_footer = GridFlow([self.edit_button[1]], 10, 1, 1, 'center')

        # Common Details Button
        self.details_button = GBoxButton("Details", self.press_button)
        connect_signal(self.details_button, 'click', lambda button: self.handle_event('details enter'))
        self.details_button = (13, self.details_button)
        self.details_button_footer = GridFlow([self.details_button[1]], 10, 1, 1, 'center')

        # Common Toggle Button
        self.toggle_button = GBoxButton("Space to toggle", self.press_button)
        self.toggle_button._selectable = False
        self.toggle_button = (21, self.toggle_button)
        self.toggle_button_footer = GridFlow([self.toggle_button[1]], 10, 1, 1, 'center')

        # Common Apply Button
        self.apply_button = GBoxButton("Apply", self.press_button)
        connect_signal(self.apply_button, 'click', lambda button: self.handle_event('apply enter'))
        self.apply_button = (12, self.apply_button)
        self.apply_button_footer = GridFlow([self.apply_button[1]], 10, 1, 1, 'center')

        # Common Save Button
        self.save_button = GBoxButton("Save", self.press_button)
        connect_signal(self.save_button, 'click', lambda button: self.handle_event('save enter'))
        self.save_button = (10, self.save_button)
        self.save_button_footer = GridFlow([self.save_button[1]], 10, 1, 1, 'center')

        self.refresh_main_menu()

        # Password Dialog
        self.prepare_password_dialog()

        # Read in logging units
        self._load_journal_units()

        # Log file viewer
        self.log_file_content: List[str] = [
            "If this is not that what you expected to see,",
            "You probably have insufficient permissions!?"
        ]
        # self.prepare_log_viewer('gromox-http', self.log_line_count)
        self.prepare_log_viewer('NetworkManager', self.log_line_count)

        self.prepare_timesyncd_config()

        # some settings
        MultiMenuItem.application = self
        GButton.application = self

    def refresh_main_menu(self):
        # The common menu description column
        self.menu_description = Pile([GText('Main Menu', CENTER), GText('Here you can do the main actions', LEFT)])
        # Main Menu
        items = {
            'Change system password': Pile([
                GText('Password change', CENTER), GText(""),
                GText(f'Change the password of the Linux system user "{getuser()}".')
            ]),
            'Network configuration': Pile([
                GText('Configuration of network', CENTER), GText(""),
                GText('Set up the active device, interfaces, IP addresses, DNS and more network bonds.')
            ]),
            'Timezone configuration': Pile([
                GText('Timezone', CENTER), GText(""),
                GText('Configuration of your country and timezone settings.')
            ]),
            'Timesyncd configuration': Pile([
                GText('Timesyncd', CENTER), GText(""),
                GText('Configuration of systemd-timesyncd as a lightweight NTP client for time synchronisation.')
            ]),
            'grommunio setup wizard': Pile([
                GText('Setup wizard', CENTER), GText(""),
                GText('Initial configuration of grommunio databases, TLS certificates, services and web UI.')
            ]),
            'Admin web password reset': Pile([
                GText('Password Change', CENTER), GText(""),
                GText('Reset the administration web interface password initially set by the grommunio '
                      'setup wizard.')
            ]),
            'Terminal': Pile([
                GText('Terminal', CENTER), GText(""),
                # GText('Starts Terminal and closes everything else.'),
                GText('Starts terminal for advanced system configuration.')
            ]),
            'Reboot': Pile([
                GText('Reboot system.', CENTER), GText(""),
                GText("")
            ]),
            'Shutdown': Pile([
                GText('Shutdown system.', CENTER), GText(""),
                GText("")
            ]),
        }
        self.main_menu_list = self.prepare_menu_list(items)
        self.main_menu = self.menu_to_frame(self.main_menu_list)

    def recreate_text_header(self):
        self.tb_header = GText(
            ''.join(self.text_header).format(colormode=self._current_colormode,
                                             kbd=self._current_kbdlayout,
                                             authorized_options=self.authorized_options),
            align=CENTER, wrap=SPACE
        )

    def prepare_mainscreen(self):
        # colormode: str = "light" if self._current_colormode == 'dark' else 'dark'
        colormode: str = self._current_colormode
        self.text_header = [u"grommunio console user interface"]
        self.text_header += ['\n']
        self.text_header += [u"You are in {colormode} colormode and use the {kbd} keyboard layout"]
        self.authorized_options = ''
        text_intro = [
            u"Here you can configure your system.", u"\n",
            u"If you need help, please try pressing 'H' to view the logs!", u"\n"
        ]
        self.tb_intro = GText(text_intro, align=CENTER, wrap=SPACE)
        text_sysinfo_top = util.get_system_info("top")
        self.tb_sysinfo_top = GText(text_sysinfo_top, align=LEFT, wrap=SPACE)
        text_sysinfo_bottom = util.get_system_info("bottom")
        self.tb_sysinfo_bottom = GText(text_sysinfo_bottom, align=LEFT, wrap=SPACE)
        self.main_top = ScrollBar(Scrollable(
            Pile([
                Padding(self.tb_intro, left=2, right=2, min_width=20),
                Padding(self.tb_sysinfo_top, align=LEFT, left=6, width=('relative', 80))
            ])
        ))
        self.main_bottom = ScrollBar(Scrollable(
            Pile([AttrWrap(Padding(self.tb_sysinfo_bottom, align=LEFT, left=6, width=('relative', 80)), 'reverse')])
        ))
        self.tb_header = GText(
            ''.join(self.text_header).format(colormode=colormode, kbd=self._current_kbdlayout,
                                             authorized_options=''),
            align=CENTER, wrap=SPACE
        )
        self.refresh_header(colormode, self._current_kbdlayout, '')
        # self.tb_header = GText(self.text_header.format(colormode=colormode, kbd=self._current_kbdlayout,
        #                                                authorized_options=''), align=CENTER, wrap=SPACE)
        self.vsplitbox = Pile([("weight", 50, AttrMap(self.main_top, "body")), ("weight", 50, self.main_bottom)])
        self.footer_text = GText('heute')
        self.print("Idle")
        self.footer = AttrMap(self.footer_text, 'footer')
        # frame = Frame(AttrMap(self.vsplitbox, 'body'), header=self.header, footer=self.footer)
        frame = Frame(AttrMap(self.vsplitbox, 'reverse'), header=self.header, footer=self.footer)
        self.mainframe = frame
        self._body = self.mainframe

    def refresh_header(self, colormode, kbd, auth_options):
        self.refresh_head_text(colormode, kbd, auth_options)
        self.header = AttrMap(Padding(self.tb_header, align=CENTER), 'header')
        if getattr(self, 'footer', None):
            self.refresh_main_menu()

    def refresh_head_text(self, colormode, kbd, authorized_options):
        self.tb_header.set_text(''.join(self.text_header).format(colormode=colormode, kbd=kbd,
                                                                 authorized_options=authorized_options))

    def listen_unsupported(self, what: str, key: Any):
        self.print(f"What is {what}.")
        if key in ['ctrl a', 'A']:
            return key

    def handle_event(self, event: Any):
        """
        Handles user input to the console UI.

            :param event: A mouse or keyboard input sequence. While the mouse event has the form ('mouse press or
                release', button, column, line), the key stroke is represented as is a single key or even the
                represented value like 'enter', 'up', 'down', etc.
            :type: Any
        """
        self.current_event = event
        if type(event) == str:
            self.handle_key_event(event)
        elif type(event) == tuple:
            self.handle_mouse_event(event)
        self.print(self.current_bottom_info)

    def handle_key_event(self, event: Any):
        # event was a key stroke
        key: str = str(event)
        if self.current_window == _MAIN:
            self.key_ev_main(key)
        elif self.current_window == _MESSAGE_BOX:
            self.key_ev_mbox(key)
        elif self.current_window == _INPUT_BOX:
            self.key_ev_ibox(key)
        elif self.current_window == _TERMINAL:
            self.key_ev_term(key)
        elif self.current_window == _PASSWORD:
            self.key_ev_pass(key)
        elif self.current_window == _LOGIN:
            self.key_ev_login(key)
        elif self.current_window == _REBOOT:
            self.key_ev_reboot(key)
        elif self.current_window == _SHUTDOWN:
            self.key_ev_shutdown(key)
        elif self.current_window == _MAIN_MENU:
            self.key_ev_mainmenu(key)
        elif self.current_window == _LOG_VIEWER:
            self.key_ev_logview(key)
        elif self.current_window == _UNSUPPORTED:
            self.key_ev_unsupp(key)
        elif self.current_window == _ADMIN_WEB_PW:
            self.key_ev_aapi(key)
        elif self.current_window == _TIMESYNCD:
            self.key_ev_timesyncd(key)
        self.key_ev_anytime(key)

    def key_ev_main(self, key):
        if key == 'f2':
            self.login_body.focus_position = 0 if getuser() == '' else 1  # focus on passwd if user detected
            self.dialog(body=LineBox(Padding(Filler(self.login_body))), header=self.login_header,
                        footer=self.login_footer, focus_part='body', align='center', valign='middle',
                        width=40, height=10)
            self.current_window = _LOGIN
        elif key == 'l' and not _PRODUCTIVE:
            self.open_main_menu()
        elif key == 'tab':
            self.vsplitbox.focus_position = 0 if self.vsplitbox.focus_position == 1 else 1

    def key_ev_mbox(self, key):
        if key.endswith('enter') or key == 'esc':
            self.current_window = self.message_box_caller
            self._body = self._message_box_caller_body
            self.reset_layout()

    def key_ev_ibox(self, key):
        self.handle_standard_tab_behaviour(key)
        if key.endswith('enter') or key == 'esc':
            if key.endswith('enter'):
                self.last_input_box_value = self._loop.widget.top_w.base_widget.body.base_widget[1].edit_text
            else:
                self.last_input_box_value = ""
            self.current_window = self.current_window_input_box
            self._body = self._input_box_caller_body
            self.reset_layout()
            self.handle_event(key)

    def key_ev_term(self, key):
        self.handle_standard_tab_behaviour(key)
        if key == 'f10':
            raise ExitMainLoop()
        elif key.endswith('enter') or key == 'esc':
            self.open_main_menu()

    def key_ev_pass(self, key):
        self.handle_standard_tab_behaviour(key)
        if key.lower().endswith('close enter') or key == 'esc':
            self.open_main_menu()

    def key_ev_login(self, key):
        self.handle_standard_tab_behaviour(key)
        if key.endswith('enter'):
            self.check_login()
        elif key == 'esc':
            self.open_mainframe()

    def key_ev_reboot(self, key):
        # Restore cursor etc. before going off.
        if key.lower() in ['enter']:
            self._loop.stop()
            self.screen.tty_signal_keys(*self.old_termios)
            os.system("reboot")
            raise ExitMainLoop()
        else:
            self.current_window = _MAIN_MENU

    def key_ev_shutdown(self, key):
        # Restore cursor etc. before going off.
        if key.lower() in ['enter']:
            self._loop.stop()
            self.screen.tty_signal_keys(*self.old_termios)
            os.system("poweroff")
            raise ExitMainLoop()
        else:
            self.current_window = _MAIN_MENU

    def key_ev_mainmenu(self, key):
        menu_selected: int = self.handle_standard_menu_behaviour(self.main_menu_list, key,
                                                                 self.main_menu.base_widget.body[1])
        if key.endswith('enter') or key in range(ord('1'), ord('9') + 1):
            if menu_selected == 1:
                self.open_change_password()
            elif menu_selected == 2:
                self.run_yast_module('lan')
            elif menu_selected == 3:
                self.run_yast_module('timezone')
            elif menu_selected == 4:
                self.open_timesyncd_conf()
            elif menu_selected == 5:
                self.open_setup_wizard()
            elif menu_selected == 6:
                self.open_reset_aapi_pw()
            elif menu_selected == 7:
                self.open_terminal()
            elif menu_selected == 8:
                self.reboot_confirm()
            elif menu_selected == 9:
                self.shutdown_confirm()
        elif key == 'esc':
            self.open_mainframe()

    def key_ev_logview(self, key):
        if key in ['ctrl f1', 'H']:
            self.current_window = self.log_file_caller
            self._body = self._log_file_caller_body
            self.reset_layout()
            self.log_finished = True
        elif key in ['left', 'right', '+', '-']:
            if key == '-':
                self.log_line_count -= 100
            elif key == '+':
                self.log_line_count += 100
            elif key == 'left':
                self.current_log_unit -= 1
            elif key == 'right':
                self.current_log_unit += 1
            if self.log_line_count < 200:
                self.log_line_count = 200
            elif self.log_line_count > 10000:
                self.log_line_count = 10000
            if self.current_log_unit < 0:
                self.current_log_unit = 0
            elif self.current_log_unit >= len(self.log_units):
                self.current_log_unit = len(self.log_units) - 1
            self.open_log_viewer(self.get_log_unit_by_id(self.current_log_unit), self.log_line_count)
        elif self._hidden_pos < len(_UNSUPPORTED) and key == _UNSUPPORTED.lower()[self._hidden_pos]:
            self._hidden_input += key
            self._hidden_pos += 1
            if self._hidden_input == _UNSUPPORTED.lower():
                self.open_unsupported()
                # raise ExitMainLoop()
        else:
            self._hidden_input = ""
            self._hidden_pos = 0

    def key_ev_unsupp(self, key):
        if key in ['ctrl d', 'esc', 'ctrl f1', 'H']:
            self.current_window = self.log_file_caller
            self._body = self._log_file_caller_body
            self.log_finished = True
            self.reset_layout()

    def key_ev_anytime(self, key):
        if key in ['f10', 'Q']:
            raise ExitMainLoop()
        elif key == 'f4' and len(self.authorized_options) > 0:
            self.open_main_menu()
        elif key == 'f1' or key == 'c':
            # self.change_colormode('dark' if self._current_colormode == 'light' else 'light')
            self.switch_next_colormode()
        elif key == 'f5':
            self.switch_kbdlayout()
        elif key in ['ctrl f1', 'H'] and self.current_window != _LOG_VIEWER \
                and self.current_window != _UNSUPPORTED \
                and not self.log_finished:
            # self.open_log_viewer('test', 10)
            self.open_log_viewer('gromox-http', self.log_line_count)
            # self.open_log_viewer('NetworkManager', self.log_line_count)

    def key_ev_aapi(self, key):
        if key.lower().endswith('enter') or key == 'esc':
            res = None
            if key.lower().endswith('enter'):
                res = self.reset_aapi_passwd(self.last_input_box_value)
            self.current_window = self.input_box_caller
            if res is not None:
                success_msg = 'successfully'
                if not res:
                    success_msg = 'not successful'
                self.message_box(f'Admin password reset was changed {success_msg}!', 'Admin password reset', height=10)

    def key_ev_timesyncd(self, key):
        self.handle_standard_tab_behaviour(key)
        success_msg = 'NOTHING'
        if key.lower().endswith('enter'):
            if key.lower().startswith('hidden'):
                button_type = key.lower().split(' ')[1]
                if button_type == 'ok':
                    # Save config and return to mainmenu
                    self.timesyncd_vars['NTP'] = self.timesyncd_body.base_widget[1].edit_text
                    self.timesyncd_vars['FallbackNTP'] = self.timesyncd_body.base_widget[2].edit_text
                    util.minishell_write('/etc/systemd/timesyncd.conf', self.timesyncd_vars)
                    rc = subprocess.Popen(["timedatectl", "set-ntp", "true"],
                                          stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
                    res = rc.wait() == 0
                    success_msg = 'successful'
                    if not res:
                        success_msg = 'not successful'
                    self.open_main_menu()
                else:
                    success_msg = 'aborted'
                    self.open_main_menu()
        elif key == 'esc':
            success_msg = 'aborted'
            self.open_main_menu()
        if key.lower().endswith('enter') or key in ['esc', 'enter']:
            self.message_box(f'Timesyncd configuration change has been {success_msg}!',
                             'Timesyncd Configuration', height=10)

    def handle_mouse_event(self, event: Any):
        # event is a mouse event in the form ('mouse press or release', button, column, line)
        event: Tuple[str, float, int, int] = tuple(event)
        if event[0] == 'mouse press' and event[1] == 1:
            # self.handle_event('mouseclick left enter')
            self.handle_event('my mouseclick left button')

    def _load_journal_units(self):
        try:
            exe = '/usr/sbin/grammm-admin'
            if Path('/usr/sbin/grommunio-admin').exists():
                exe = '/usr/sbin/grommunio-admin'
            p = subprocess.Popen([exe, "config", "dump"],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, err = p.communicate()
            if type(out) is bytes:
                out = out.decode()
            if out == "":
                # self.message_box(err, "An Error occured!!", width=60, height=11)
                self.config = {'logs': {'Gromox http': {'source': 'gromox-http.service'}}}
            else:
                self.config = yaml.load(out, Loader=SafeLoader)
        except BaseException as e:
            # use dummy config if no groadmin is there
            self.config = {'logs': {'Gromox http': {'source': 'gromox-http.service'}}}
        self.log_units = self.config.get('logs', {'Gromox http': {'source': 'gromox-http.service'}})
        for i, k in enumerate(self.log_units.keys()):
            if k == 'Gromox http':
                self.current_log_unit = i
                break

    def get_logging_formatter(self) -> str:
        # conf = {
        #     'logging': {
        #         'formatters': {
        #             'mi-default': {
        #                 'format': '[%(asctime)s] [%(levelname)s] (%(module)s): "%(message)s"'
        #             }}}}
        default = self.config.get('logging', {}).get('formatters', {}).get('mi-default', {})
        return default.get('format', '[%(asctime)s] [%(levelname)s] (%(module)s): "%(message)s"')

    def get_log_unit_by_id(self, id) -> str:
        for i, k in enumerate(self.log_units.keys()):
            if id == i:
                return self.log_units[k].get('source')[:-8]
        return ''

    @staticmethod
    def get_pure_menu_name(label: str) -> str:
        """
        Reduces label with id to original label-only form.

        :param label: The label in form "ID) LABEL" or "LABEL".
        :return: Only LABEL without "ID) ".
        """
        if label.find(') ') > 0:
            parts = label.split(') ')
            if len(parts) < 2:
                return label
            else:
                return parts[1]
        else:
            return label

    def handle_click(self, creator: Widget, option: bool = False):
        """
        Handles RadioButton clicks.

        :param creator: The widget creating calling the function.
        :param option: On if True, of otherwise.
        """
        self.print(f"Creator ({creator}) clicked {option}.")

    def handle_menu_changed(self, *args, **kwargs):
        """
        Is called additionally if item is chnaged (???).
        TODO Check what this does exactly.  or when it is called

        :param args: Optional user_args.
        :param kwargs: Optional keyword args
        """
        self.print(f"Called handle_menu_changed() with args({args}) und kwargs({kwargs})")

    def handle_menu_activated(self, *args, **kwargs):
        """
        Is called additionally if menu is activated.
        (Maybe obsolete!)

        :param args: Optional user_args.
        :param kwargs: Optional keyword args
        """
        self.print(f"Called handle_menu_activated() with args({args}) und kwargs({kwargs})")

    def open_terminal(self):
        """
        Jump to a shell prompt
        """
        self._loop.stop()
        self.screen.tty_signal_keys(*self.old_termios)
        print("\x1b[K")
        print("\x1b[K \x1b[36m▼\x1b[0m To return to the CUI, issue the `exit` command.")
        print("\x1b[J")
        # We have no environment, and so need su instead of just bash to launch
        # a proper PAM session and set $HOME, etc.
        os.system("/usr/bin/su -l")
        self.screen.tty_signal_keys(*self.blank_termios)
        self._loop.start()

    def reboot_confirm(self):
        msg = "Are you sure?\nAfter pressing OK, the system will reboot!"
        title = 'Reboot'
        self.current_window = _REBOOT
        self.message_box(msg, title, width=80, height=10)

    def shutdown_confirm(self):
        msg = "Are you sure?\nAfter pressing OK, the system will shut down!"
        title = "Shutdown"
        self.current_window = _SHUTDOWN
        self.message_box(msg, title, width=80, height=10)

    def open_change_password(self):
        """
        Opens password changing dialog.
        """
        self.reset_layout()
        self.current_window = _PASSWORD
        self.print('Opening change password dialog.')
        self.prepare_password_dialog()
        # footer = self.close_button_footer
        footer = AttrMap(Columns([
            ('weight', 1, GText('Note: Use "TAB" to jump to close.')),
            ('weight', 1, Columns([('weight', 1, GText('')), self.close_button, ('weight', 1, GText(''))])),
            ('weight', 1, GText(''))
        ]), 'buttonbar')
        self.dialog(
            header=GText(f"Change password for user {getuser()}", align='center'),
            body=self.password_frame, footer=footer, focus_part='body',
            align=CENTER, valign='middle', width=80, height=25
        )

    def prepare_password_dialog(self):
        self.password = Terminal(["passwd"])
        self.password_frame = LineBox(
            Pile([
                ('weight', 70, self.password),
            ]),
        )

    def prepare_log_viewer_old(self, logfile: str = 'syslog', lines: int = 0):
        """
        Prepares log file viewer widget and fills last lines of file content.

        :param logfile: The logfile to be viewed.
        """
        filename: str = '/var/log/messages'
        if logfile == 'syslog':
            filename = '/var/log/messages'
        elif logfile == 'test':
            filename = '../README.md'

        log: Path = Path(filename)

        if log.exists():
            # self.log_file_content = log.read_text('utf-8')[:lines * -1]
            if os.access(str(log), os.R_OK):
                self.log_file_content = util.fast_tail(str(log.absolute()), lines)
        self.log_viewer = LineBox(Pile([ScrollBar(Scrollable(Pile([GText(line) for line in self.log_file_content])))]))

    def prepare_log_viewer(self, unit: str = 'syslog', lines: int = 0):
        """
        Prepares log file viewer widget and fills last lines of file content.

        :param unit: The journal unit to be viewed.
        """
        unitname: str = unit if unit.strip().endswith('.service') else f"{unit}.service"

        h = 60 * 60
        d = 24 * h
        sincetime = time.time() - 4 * d
        r = journal.Reader()
        r.this_boot()
        #r.log_level(sj.LOG_INFO)
        r.add_match(_SYSTEMD_UNIT=unitname)
        #r.seek_realtime(sincetime)
        l = []
        for entry in r:
            if entry.get('__REALTIME_TIMESTAMP', '') == "":
                continue
            d = {
                'asctime': entry.get('__REALTIME_TIMESTAMP', datetime.datetime(1970, 1, 1, 0, 0, 0)).isoformat(),
                'levelname': entry.get('PRIORITY', ''),
                'module': entry.get('_SYSTEMD_UNIT', 'gromox-http.service').split('.service')[0],
                'message': entry.get('MESSAGE', '')
            }
            l.append(self.get_logging_formatter() % d)
            # ll = entry.get('NM_LOG_LEVEL', 'None')
#             l.append(f"""\
# {entry['__REALTIME_TIMESTAMP'].isoformat():19.19} {entry['_HOSTNAME']:8.8} \
# {entry['_SYSTEMD_UNIT'].split('.service')[0]:>10.10} {entry['_COMM']:>10.10}: {entry['MESSAGE']}\
#             """)
        self.log_file_content = l[-lines:]
        found: bool = False
        pre: List[str] = []
        post: List[str] = []
        cur: str = f" {unitname[:-8]} "
        for i, uname in enumerate(self.log_units.keys()):
            src = self.log_units[uname].get('source')
            if src == unitname:
                found = True
            else:
                if not found:
                    pre.append(src[:-8])
                else:
                    post.append(src[:-8])
        header = 'Use arrow keys to switch between the logfiles. <LEFT> and <RIGHT> changes the logfile, ' \
                 'while <+> and <-> changes the line count to view. ({})'.format(self.log_line_count)
        self.log_viewer = LineBox(AttrMap(Pile([
            (2, Filler(Padding(GText(('body', header), CENTER), CENTER, RELATIVE_100))),
            (1, Columns([Filler(GText([
                ('body', '*** '),
                ('body', ' '.join([u for u in pre[-3:]])), ('reverse', cur), ('body', ' '.join([u for u in post[:3]])),
                ('body', ' ***'),
            ], CENTER))])),
            AttrMap(ScrollBar(Scrollable(Pile([GText(line) for line in self.log_file_content]))), 'default')
        ]), 'body'))

    def open_log_viewer(self, unit: str, lines: int = 0):
        """
        Opens log file viewer.
        """
        if self.current_window != _LOG_VIEWER:
            self.log_file_caller = self.current_window
            self._log_file_caller_body = self._body
            self.current_window = _LOG_VIEWER
        self.print(f"Log file viewer has to open file {unit} ...")
        self.prepare_log_viewer(unit, lines)
        self._body = self.log_viewer
        self._loop.widget = self._body

    def run_yast_module(self, modulename: str):
        self._loop.stop()
        self.screen.tty_signal_keys(*self.old_termios)
        print("\x1b[K")
        print("\x1b[K \x1b[36m▼\x1b[0m Please wait while `yast2 {}` is being run.".format(modulename))
        print("\x1b[J")
        os.system("yast2 {}".format(modulename))
        self.screen.tty_signal_keys(*self.blank_termios)
        self._loop.start()

    def open_reset_aapi_pw(self):
        self.reset_layout()
        self.print("Resetting admin-web password")
        self.current_window_input_box = _ADMIN_WEB_PW
        self.input_box(
            title='Admin-Web-Password Reset',
            msg='Enter your new admin-web password:',
            width=60,
            input_text="",
            height=10,
            mask='*')

    def reset_aapi_passwd(self, new_pw: str) -> bool:
        if new_pw:
            if new_pw != "":
                exe = 'grammm-admin'
                if Path('/usr/sbin/grommunio-admin').exists():
                    exe = 'grommunio-admin'
                proc = subprocess.Popen([exe, 'passwd', '--password', new_pw],
                                        stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)

                return proc.wait() == 0
        return False

    def open_timesyncd_conf(self):
        self.reset_layout()
        self.print("Opening timesyncd configuration")
        self.current_window = _TIMESYNCD
        header = AttrMap(GText('Timesyncd Configuration', CENTER), 'header')
        self.prepare_timesyncd_config()
        footer = AttrMap(Columns([self.ok_button, self.cancel_button]), 'buttonbar')
        self.dialog(
            body=AttrMap(self.timesyncd_body, 'body'), header=header,
            footer=footer, focus_part='body',
            align=CENTER, width=60, valign=MIDDLE, height=15
        )

    def prepare_timesyncd_config(self):
        ntp_server: List[str] = [
            '0.arch.pool.ntp.org', '1.arch.pool.ntp.org',
            '2.arch.pool.ntp.org', '3.arch.pool.ntp.org'
        ]
        fallback_server: List[str] = [
            '0.opensuse.pool.ntp.org', '1.opensuse.pool.ntp.org',
            '2.opensuse.pool.ntp.org', '3.opensuse.pool.ntp.org'
        ]
        self.timesyncd_vars = util.minishell_read('/etc/systemd/timesyncd.conf')
        ntp_from_file = self.timesyncd_vars.get('NTP', ' '.join(ntp_server))
        fallback_from_file = self.timesyncd_vars.get('FallbackNTP', ' '.join(fallback_server))
        ntp_server = ntp_from_file.split(' ')
        fallback_server = fallback_from_file.split(' ')
        self.timesyncd_body = LineBox(Padding(Filler(Pile([
            GText('Insert your NTP servers separated by <SPACE> char.', LEFT, wrap=SPACE),
            GEdit((15, 'NTP: '), ' '.join(ntp_server), wrap=SPACE),
            GEdit((15, 'FallbackNTP: '), ' '.join(fallback_server), wrap=SPACE),
            # GEdit(('pack', 'packTest: '), ' '.join(fallback_server), wrap=SPACE),
            # GEdit(('weight', 5, '5weightTest: '), ' '.join(fallback_server), wrap=SPACE),
            # GEdit(('weight', 15, '15weightTest: '), ' '.join(fallback_server), wrap=SPACE),
            # GEdit(('weight', 35, '35weightTest: '), ' '.join(fallback_server), wrap=SPACE),
            # GEdit('', ' '.join(fallback_server), wrap=SPACE),
            # GEdit('Test: ', ' '.join(fallback_server), wrap=SPACE),
        ]), TOP)))

    def open_setup_wizard(self):
        self._loop.stop()
        self.screen.tty_signal_keys(*self.old_termios)
        if Path("/usr/sbin/grommunio-setup").exists():
            os.system("/usr/sbin/grommunio-setup")
        else:
            os.system("/usr/sbin/grammm-setup")
        self.screen.tty_signal_keys(*self.blank_termios)
        self._loop.start()

    def open_main_menu(self):
        """
        Opens amin menu,
        """
        self.reset_layout()
        self.print("Login successful")
        self.current_window = _MAIN_MENU
        self.authorized_options = ', <F4> for Main-Menu'
        colormode: str = "light" if self._current_colormode == 'dark' else 'dark'
        self.prepare_mainscreen()
        # self.refresh_head_text(colormode, self._current_kbdlayout, self.authorized_options)
        self._body = self.main_menu
        self._loop.widget = self._body
        menu_selected: int = self.handle_standard_menu_behaviour(self.main_menu_list, 'up',
                                                                 self.main_menu.base_widget.body[1])

    def open_mainframe(self):
        """
        Opens main window. (Welcome screen)
        """
        self.reset_layout()
        self.print("Returning to main screen!")
        self.current_window = _MAIN
        self.prepare_mainscreen()
        self._loop.widget = self._body

    def check_login(self, w: Widget = None):
        """
        Checks login data and switch to authenticate on if successful.
        """
        if self.user_edit.get_edit_text() != getuser() and os.getegid() != 0:
            self.message_box("You must have root privileges if you want to use another user!", height=10)
            return
        msg = f"checking user {self.user_edit.get_edit_text()} with pass ***** ..."
        if self.current_window == _LOGIN:
            if util.authenticate_user(self.user_edit.get_edit_text(), self.pass_edit.get_edit_text()):
                self.open_main_menu()
            else:
                # self.message_box(f'You have taken a wrong password, {self.user_edit.get_edit_text()}!')
                self.message_box('Incorrect credentials. Access denied!', 'Password verification')
                self.print(f"Login wrong! ({msg})")

    def press_button(self, button: Widget, *args, **kwargs):
        """
        Handles general events if a button is pressed.

        :param button: The button been clicked.
        """
        label: str = "UNKNOWN LABEL"
        if isinstance(button, Button) or isinstance(button, WidgetDrawer):
            label = button.label
        if not self.current_window == _MAIN:
            self.print(f"{self.__class__}.press_button(button={button}, *args={args}, kwargs={kwargs})")
            self.handle_event(f"{label} enter")

    def prepare_menu_list(self, items: Dict[str, Widget]) -> ListBox:
        """
        Prepare general menu list.

        :param items: A dictionary of widgets representing the menu items.
        :return: ListBox containig menu items.
        """
        menu_items: List[MenuItem] = self.create_menu_items(items)
        return ListBox(SimpleFocusListWalker(menu_items))

    def menu_to_frame(self, listbox: ListBox):
        menu = Columns([
            AttrMap(listbox, 'body'),
            AttrMap(ListBox(SimpleListWalker([self.menu_description])), 'reverse'),
        ])
        menu[1]._selectable = False
        return Frame(menu, header=self.header, footer=self.footer)

    def prepare_radio_list(self, items: Dict[str, Widget]) -> Tuple[ListBox, ListBox]:
        """
        Prepares general radio list containing RadioButtons and content.

        :param items: A dictionary of widgets representing the menu items.
        :return: Tuple of one ListBox containing menu items and one containing the content.
        """
        radio_items: List[RadioButton]
        radio_content: List[Widget]
        radio_items, radio_content = self.create_radiobutton_items(items)
        radio_walker: ListWalker = SimpleListWalker(radio_items)
        content_walker: ListWalker = SimpleListWalker(radio_content)
        if len(radio_items) > 0:
            connect_signal(radio_walker, 'modified', self.handle_event, user_args=[radio_walker, radio_items])
        return ListBox(radio_walker), ListBox(content_walker)

    def wrap_radio(self, master: ListBox, slave: ListBox, header: Widget, title: str = None) -> LineBox:
        """
        Wraps the two ListBoxes returned by ::self::.prepare_radio_list() as master (RadioButton) and slave (content)
        with menues header and an optional title.

        :param master: The leading RadioButtons.
        :param slave: The following content widgets.
        :param header: The menu header.
        :param title: The optional title.
        :return: The wrapped LineBox.
        """
        title = 'Menu' if title is None else title
        return LineBox(Pile([
            (3, AttrMap(Filler(GText(title, CENTER), TOP), 'body')),
            (1, header),
            AttrMap(Columns([
                ('weight', 1, AttrMap(master, 'MMI.selectable', 'MMI.focus')),
                ('weight', 4, AttrMap(slave, 'MMI.selectable', 'MMI.focus')),
            ]), 'reverse'),
        ]))

    def change_colormode(self, mode: str):
        p = util.get_palette(mode)
        self._current_colormode = mode
        colormode: str = "light" if self._current_colormode == 'dark' else 'dark'
        self.refresh_header(colormode, self._current_kbdlayout, self.authorized_options)
        self._loop.screen.register_palette(p)
        self._loop.screen.clear()

    def switch_next_colormode(self):
        o = self._current_colormode
        n = util.get_next_palette_name(o)
        p = util.get_palette(n)
        # show_next = util.get_next_palette_name(n)
        show_next = n
        self.refresh_header(show_next, self._current_kbdlayout, self.authorized_options)
        self._loop.screen.register_palette(p)
        self._loop.screen.clear()
        self._current_colormode = show_next

    def switch_kbdlayout(self):
        # Base proposal on CUI's last known state
        proposal = "de-latin1-nodeadkeys" if self._current_kbdlayout == "us" else "us"
        # But do read the file again so newly added keys do not get lost
        file = "/etc/vconsole.conf"
        vars = util.minishell_read(file)
        vars["KEYMAP"] = proposal
        util.minishell_write(file, vars)
        os.system("systemctl restart systemd-vconsole-setup")
        self._current_kbdlayout = proposal
        self.refresh_head_text(self._current_colormode, self._current_kbdlayout, self.authorized_options)

    def redraw(self):
        """
        Redraws screen.
        """
        self._loop.draw_screen()

    def reset_layout(self):
        """
        Resets the console UI to the default layout
        """

        if getattr(self, '_loop', None):
            self._loop.widget = self._body
            self._loop.draw_screen()

    def create_menu_items(self, items: Dict[str, Widget]) -> List[MenuItem]:
        """
        Takes a dictionary with menu labels as keys and widget(lists) as content and creates a list of menu items.

        :param items: Dictionary in the form {'label': Widget}.
        :return: List of MenuItems.
        """
        menu_items: List[MenuItem] = []
        for id, caption in enumerate(items.keys(), 1):
            item = MenuItem(id, caption, items.get(caption), self)
            connect_signal(item, 'activate', self.handle_event)
            menu_items.append(AttrMap(item, 'selectable', 'focus'))
        return menu_items

    def create_radiobutton_items(self, items: Dict[str, Widget]) -> Tuple[List[RadioButton], List[Widget]]:
        """
        Takes a dictionary with menu labels as keys and widget(lists) as content and creates a tuple of two lists.
        One list of leading RadioButtons and the second list contains the following widget..

        :param items: Dictionary in the form {'label': Widget}.
        :return: Tuple with two lists. One List of MenuItems representing the leading radio buttons and one the content
                 widget.
        """
        menu_items: List[RadioButton] = []
        my_items: List[RadioButton] = []
        my_items_content: List[Widget] = []
        for id, caption in enumerate(items.keys(), 1):
            item = RadioButton(menu_items, caption, on_state_change=self.handle_click)
            my_items.append(AttrMap(item, 'MMI-selectable', 'MMI.focus'))
            my_items_content.append(AttrMap(items.get(caption), 'MMI-selectable', 'MMI.focus'))
        return my_items, my_items_content

    def create_multi_menu_items(self, items: Dict[str, Widget], selected: str = None) -> List[MultiMenuItem]:
        """
        Takes a dictionary with menu labels as keys and widget(lists) as content and creates a list of multi menu items
        with being one selected..

        :param items: Dictionary in the form {'label': Widget}.
        :param selected: The label of the selected multi menu item.
        :return: List of MultiMenuItems.
        """
        menu_items: List[MultiMenuItem] = []
        my_items: List[MultiMenuItem] = []
        for id, caption in enumerate(items.keys(), 1):
            caption_wo_no: str = self.get_pure_menu_name(caption)
            state: Any
            if selected is not None:
                if selected == caption_wo_no:
                    state = True
                else:
                    state = False
            else:
                state = 'first True'
            item = MultiMenuItem(menu_items, id, caption_wo_no, items.get(caption), state=state,
                                 on_state_change=MultiMenuItem.handle_menu_changed, app=self)
            my_items.append(item)
            # connect_signal(item, 'activate', self.handle_event)
            # menu_items.append(AttrMap(item, 'selectable', 'focus'))
        return my_items

    def create_multi_menu_listbox(self, menu_list: List[MultiMenuItem]) -> ListBox:
        """
        Creates general listbox of multi menu items from list of multi menu items.

        :param menu_list: list of MultiMenuItems
        :return: The ListBox.
        """
        listbox: ListBox[ListWalker] = ListBox(SimpleListWalker(menu_list))
        item: MultiMenuItem
        for item in menu_list:
            item.set_parent_listbox(listbox)
        return listbox

    def wrap_multi_menu_listbox(self, listbox: ListBox, header: Widget = None, title: str = None) -> LineBox:
        """
        Wraps general listbox of multi menu items with a linebox.

        :param listbox: ListBox to be wrapped.
        :param header: Optional ListBox header.
        :param title: Optional title. "Menu" is used if title is None.
        :return: The wrapping LineBox around the ListBox.
        """
        title = 'Menu' if title is None else title
        return LineBox(Pile([
            (3, AttrMap(Filler(GText(title, CENTER), TOP), 'body')),
            (1, header) if header is not None else (),
            AttrMap(Columns([listbox]), 'MMI.selectable'),
        ]))

    def print(self, string='', align='left'):
        """
        Prints a string to the console UI

        Args:
            string (str): The string to print
            align (str): The alignment of the printed text
        """
        text = [('footer', f"{util.get_clockstring()}: ")]
        text += util.get_footerbar(2, 10)
        text += util.get_load_avg_format_list()
        if not self.quiet:
            text += '\n'
            text += ('footer', string)
        if self.debug:
            text += ['\n', ('', f"({self.current_event})"), ('', f" on {self.current_window}")]
        self.footer_text.set_text([text])
        self.current_bottom_info = string

    def message_box(self, msg: Any, title: str = None, align: str = CENTER, width: int = 45,
                    valign: str = MIDDLE, height: int = 9):
        """
        Creates a message box dialog with an optional title. The message also can be a list of urwid formatted tuples.

        To use the box as standard message box always returning to it's parent, then you have to implement something like
        this in your event handler: (f.e. **self**.handle_event)

            elif self.current_window == _MESSAGE_BOX:
                if key.endswith('enter') or key == 'esc':
                    self.current_window = self.message_box_caller
                    self._body = self._message_box_caller_body
                    self.reset_layout()

        :param msg: List or one element of urwid formatted tuple containing the message content.
        :type: Any
        :param title: Optional title as simple string.
        :param align: Horizontal align.
        :param width: The width of the box.
        :param valign: Vertical align.
        :param height: The height of the box.
        """
        self.message_box_caller = self.current_window
        self._message_box_caller_body = self._loop.widget
        self.current_window = _MESSAGE_BOX
        body = LineBox(Padding(Filler(Pile([GText(msg, CENTER)]), TOP)))
        if title is None:
            title = 'Message'
        self.dialog(
            body=body, header=GText(title, CENTER),
            footer=self.ok_button_footer, focus_part='footer',
            align=align, width=width, valign=valign, height=height
        )

    def input_box(self, msg: Any, title: str = None, input_text: str = "", multiline: bool = False,
                  align: str = CENTER, width: int = 45,
                  valign: str = MIDDLE, height: int = 9,
                  mask: Union[bytes, str] = None):
        """Creates an input box dialog with an optional title and a default value. 
        The message also can be a list of urwid formatted tuples.

        To use the box as standard input box always returning to it's parent, then you have to implement something like
        this in your event handler: (f.e. **self**.handle_event) and you MUST set the self.current_window_input_box

            self.current_window_input_box = _ANY_OF_YOUR_CURRENT_WINDOWS
            self.input_box('Y/n', 'Question', 'yes')

            # and later on event handling
            elif self.current_window == _ANY_OF_YOUR_CURRENT_WINDOWS:
                if key.endswith('enter') or key == 'esc':
                    self.current_window = self.input_box_caller  # here you have to set your current window

        :param msg: List or one element of urwid formatted tuple containing the message content.
        :type: Any
        :param title: Optional title as simple string.
        :param input_text: Default text as input text.
        :param multiline: If True then inputs can have more than one line.
        :param align: Horizontal align.
        :param width: The width of the box.
        :param valign: Vertical align.
        :param height: The height of the box.
        :param mask: hide text entered by this character. If None, mask will be disabled.
        """
        self.input_box_caller = self.current_window
        self._input_box_caller_body = self._loop.widget
        self.current_window = _INPUT_BOX
        body = LineBox(Padding(Filler(Pile([
            GText(msg, CENTER),
            GEdit("", input_text, multiline, CENTER, mask=mask)
        ]), TOP)))
        if title is None:
            title = 'Input expected'
        self.dialog(
            body=body, header=GText(title, CENTER),
            footer=self.ok_button_footer, focus_part='body',
            align=align, width=width, valign=valign, height=height
        )

    def printf(self, *strings):
        """
        Prints multiple strings with different alignment
        TODO implemnt a similar method

        Args:
            strings (tuple): A string, alignment pair
        """

        self._body_walker.append(
            Columns(
                [
                    GText(string, align=align)
                    for string, align in strings
                ]
            )
        )

    def get_focused_menu(self, menu: ListBox, event: Any) -> int:
        """
        Returns id of focused menu item. Returns current id on enter or 1-9 or click, and returns the next id if
        key is up or down.

        :param menu: The menu from which you want to know the id.
        :type: ListBox
        :param event: The event passed to the menu.
        :type: Any
        :returns: The id of the selected menu item. (>=1)
        :rtype: int
        """
        self.current_menu_focus = super(Application, self).get_focused_menu(menu, event)
        if not self.last_menu_focus == self.current_menu_focus:
            cid: int = self.last_menu_focus - 1
            nid: int = self.current_menu_focus - 1
            cw: Widget = menu.body[cid].base_widget
            nw: Widget = menu.body[nid].base_widget
            if isinstance(cw, MultiMenuItem) and isinstance(nw, MultiMenuItem):
                cmmi: MultiMenuItem = cw
                nmmi: MultiMenuItem = nw
                cmmi.mark_as_dirty()
                nmmi.mark_as_dirty()
                nmmi.set_focus()
                cmmi.refresh_content()
        return self.current_menu_focus

    def handle_standard_menu_behaviour(self, menu: ListBox, event: Any, description_box: ListBox = None) -> int:
        """
        Handles standard menu behaviour and returns the focused id, if any.

        :param menu: The menu to be handled.
        :param event: The event to be handled.
        :param description_box: The ListBox containing the menu content that may be refreshed with the next description.
        :return: The id of the menu having the focus (1+)
        """
        id: int = self.get_focused_menu(menu, event)
        if str(event) not in ['up', 'down']:
            return id
        if description_box is not None:
            focused_item: MenuItem = menu.body[id - 1].base_widget
            description_box.body[0] = focused_item.get_description()
        return id

    def handle_standard_tab_behaviour(self, key: str = 'tab'):
        """
        Handles standard tabulator bahaviour in dialogs. Switching from body to footer and vice versa.

        :param key: The key to be handled.
        """
        if key == 'tab':
            if self.layout.focus_position == 'body':
                self.layout.focus_position = 'footer'
            elif self.layout.focus_position == 'footer':
                self.layout.focus_position = 'body'

    def set_debug(self, on: bool):
        """
        Sets debug mode on or off.

        :param on: True for on and False for off.
        """
        self.debug = on

    def update_clock(self, loop: MainLoop, data: Any = None):
        """
        Updates taskbar every second.

        :param loop: The event loop calling next update_clock()
        """
        self.print(self.current_bottom_info)
        loop.set_alarm_in(1, self.update_clock)

    def start(self):
        """
        Starts the console UI
        """
        self._loop.run()
        if self.old_termios is not None:
            self.screen.tty_signal_keys(*self.old_termios)

    def dialog(self, body: Widget = None, header: Widget = None, footer: Widget = None, focus_part: str = None,
               align: str = CENTER, width: int = 40, valign: str = MIDDLE, height: int = 10):
        """
        Overlays a dialog box on top of the console UI

        Args:
            body (Widget): The center widget.
            header (Widget): The header widget.
            footer (Widget): The footer widget.
            focus_part (str): The part getting the focus. ('header', 'body' or 'footer')
            align (str): Horizontal align.
            width (int): The width of the box.
            valign (str): Vertical align.
            height (int): The height of the box.
        """
        # Body
        if body is None:
            body_text = GText('No body', align='center')
            body_filler = Filler(body_text, valign='top')
            body_padding = Padding(
                body_filler,
                left=1,
                right=1
            )
            body = LineBox(body_padding)

        # Footer
        if footer is None:
            footer = GBoxButton('Okay', self.reset_layout())
            footer = AttrWrap(footer, 'selectable', 'focus')
            footer = GridFlow([footer], 8, 1, 1, 'center')

        # Focus
        if focus_part is None:
            focus_part = 'footer'

        # Layout
        self.layout = Frame(
            body,
            header=header,
            footer=footer,
            focus_part=focus_part
        )

        w = Overlay(
            LineBox(self.layout),
            self._body,
            align=align,
            width=width,
            valign=valign,
            height=height
        )

        self._loop.widget = w

    def check_config_write(self, di) -> bool:
        title: str = "Success on writing!"
        height: int = 9
        msg: List[str] = ["Config written"]
        rv: bool = True
        if di.write_config():
            msg += [' ', "successfully."]
        else:
            title = "Writing failed!"
            height += 1
            msg += [('important', ' not '), "successfully.", "\n", "Maybe you have insufficient rights?"]
            rv = False
        self.message_box(msg, title=title, height=height)
        return rv


def create_application():
    global _PRODUCTIVE
    set_encoding('utf-8')
    _PRODUCTIVE = True
    app = None
    if "--help" in sys.argv:
        print(f"Usage: {sys.argv[0]} [OPTIONS]")
        print(f"\tOPTIONS:")
        print(f"\t\t--help: Show this message.")
        print(f"\t\t-v/--debug: Verbose/Debugging mode.")
    else:
        app = Application()
        if "-v" in sys.argv:
            app.set_debug(True)
        else:
            app.set_debug(False)

        app.quiet = True

        if "--hidden-login" in sys.argv:
            _PRODUCTIVE = False

        return app


if __name__ == '__main__':
    app = create_application()
    app.start()
