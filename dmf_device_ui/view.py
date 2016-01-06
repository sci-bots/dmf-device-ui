# -*- coding: utf-8 -*-
from datetime import datetime
import logging

from microdrop_utility.gui import register_shortcuts
from pygtkhelpers.delegates import SlaveView
import gobject
import gtk
import pandas as pd

from .options import DeviceViewOptions, DeviceViewInfo, DebugView
from .plugin import DevicePluginConnection
from . import gtk_wait

logger = logging.getLogger(__name__)


class DmfDeviceView(SlaveView):
    def __init__(self, device_canvas):
        self.device_canvas = device_canvas
        self.plugin = None
        self.socket_timeout_id = None
        self.heartbeat_timeout_id = None
        self.heartbeat_alive_timestamp = None
        super(DmfDeviceView, self).__init__()

    def create_ui(self):
        super(DmfDeviceView, self).create_ui()
        self.widget.set_orientation(gtk.ORIENTATION_VERTICAL)
        self.info_slave = self.add_slave(DeviceViewInfo(), 'widget')
        self.options_slave = self.add_slave(DeviceViewOptions(), 'widget')
        self.plugin_slave = self.add_slave(DevicePluginConnection(self),
                                           'widget')
        self.debug_slave = self.add_slave(DebugView(), 'widget')
        self.canvas_slave = self.add_slave(self.device_canvas, 'widget')

        self.info_slave.connection_count = self.canvas_slave.connection_count
        self.info_slave.electrode_count = self.canvas_slave.shape_count

        self.options_slave.connections = self.canvas_slave.connections_enabled
        self.options_slave.connections_alpha = (self.canvas_slave
                                                .connections_alpha)

        # Pack load and save sections to end of row.
        for slave in self.slaves:
            if slave is self.canvas_slave:
                continue
            self.widget.set_child_packing(slave.widget, False, False, 0,
                                          gtk.PACK_START)

    def on_options_slave__labels_toggled(self, slave, active):
        self.canvas_slave.render()
        gtk.idle_add(self.canvas_slave.draw)

    def on_options_slave__connections_toggled(self, slave, active):
        self.canvas_slave.connections_enabled = active
        self.canvas_slave.render()
        gtk.idle_add(self.canvas_slave.draw)

    def on_options_slave__connections_alpha_changed(self, slave, alpha):
        self.canvas_slave.connections_alpha = alpha
        self.canvas_slave.render()
        gtk.idle_add(self.canvas_slave.draw)

    def on_canvas_slave__electrode_mouseover(self, slave, data):
        self.info_slave.electrode_id = data['electrode_id']

    def on_canvas_slave__electrode_mouseout(self, slave, data):
        self.info_slave.electrode_id = ''

    def on_canvas_slave__electrode_selected(self, slave, data):
        if self.plugin is not None:
            state = (self.canvas_slave.electrode_states
                     .get(data['electrode_id'], 0))
            (self.plugin.execute('wheelerlab.electrode_controller_plugin',
                                 'set_electrode_states',
                                 electrode_states=
                                 pd.Series([not state],
                                           index=[data['electrode_id']])))

    def on_canvas_slave__electrode_pair_selected(self, slave, data):
        '''
        Process pair of selected electrodes.

        For now, this consists of finding the shortest path between the two
        electrodes and appending it to the list of droplet routes for the
        current step.

        Note that the droplet routes for a step are stored in a frame/table in
        the `DmfDeviceController` step options.
        '''
        import networkx as nx

        source_id = data['source_id']
        target_id = data['target_id']

        if self.canvas_slave.device is None or self.plugin is None:
            return
        try:
            shortest_path = self.canvas_slave.device.find_path(source_id,
                                                               target_id)
            self.plugin.execute_async('wheelerlab.droplet_planning_plugin',
                                      'add_route', drop_route=shortest_path)
        except nx.NetworkXNoPath:
            logger.error('No path found between %s and %s.', source_id,
                         target_id)

    def on_widget__realize(self, *args):
        self.register_shortcuts()

    def register_shortcuts(self):
        def control_protocol(command):
            if self.plugin is not None:
                self.plugin.execute_async('microdrop.gui.protocol_controller',
                                          command)

        # Tie shortcuts to protocol controller commands (next, previous, etc.)
        shortcuts = {'<Control>r': lambda *args:
                     control_protocol('run_protocol'),
                     'A': lambda *args: control_protocol('first_step'),
                     'S': lambda *args: control_protocol('prev_step'),
                     'D': lambda *args: control_protocol('next_step'),
                     'F': lambda *args: control_protocol('last_step')}
        register_shortcuts(self.widget.parent, shortcuts)

    def cleanup(self):
        if self.socket_timeout_id is not None:
            gobject.source_remove(self.socket_timeout_id)
        if self.plugin is not None:
            self.plugin = None
        self.plugin_slave.reset()

    ###########################################################################
    # ZeroMQ plugin callbacks
    ###########################################################################
    def ping_hub(self):
        '''
        Attempt to ping the ZeroMQ plugin hub to verify connection is alive.

        If ping is successful, record timestamp.
        If ping is unsuccessful, call `on_heartbeat_error` method.
        '''
        if self.plugin is not None:
            try:
                result = self.plugin.execute(self.plugin.hub_name, 'ping',
                                             timeout_s=1, wait_func=gtk_wait)
            except IOError:
                self.on_heartbeat_error()
            else:
                self.heartbeat_alive_timestamp = datetime.now()
                logger.debug('Hub connection alive as of %s',
                             self.heartbeat_alive_timestamp)
                return True

    def on_heartbeat_error(self):
        logger.error('Timed out waiting for heartbeat ping.')
        self.cleanup()

    def on_plugin_slave__plugin_connected(self, slave, plugin):
        self.plugin = plugin

        # Block until device is retrieved from device info plugin.
        device = self.plugin.execute_async('wheelerlab.device_info_plugin',
                                           'get_device')
        # Periodically process outstanding plugin socket messages.
        self.socket_timeout_id = gobject.timeout_add(10,
                                                     self.plugin.check_sockets)
        # Periodically ping hub to verify connection is alive.
        self.heartbeat_timeout_id = gobject.timeout_add(2000, self.ping_hub)

    def on_device_loaded(self, device):
        self.canvas_slave.set_device(device)
        self.info_slave.connection_count = self.canvas_slave.connection_count
        self.info_slave.electrode_count = self.canvas_slave.shape_count
        self.plugin.request_refresh()

    def on_electrode_states_updated(self, states):
        updated_electrode_states = \
            states['electrode_states'].combine_first(self.canvas_slave
                                                     .electrode_states)
        if not (self.canvas_slave.electrode_states
                .equals(updated_electrode_states)):
            self.canvas_slave.electrode_states = updated_electrode_states
            self.canvas_slave.render()
            gtk.idle_add(self.canvas_slave.draw)

    def on_electrode_states_set(self, states):
        if not (self.canvas_slave.electrode_states
                .equals(states['electrode_states'])):
            self.canvas_slave.electrode_states = states['electrode_states']
            self.canvas_slave.render()
            gtk.idle_add(self.canvas_slave.draw)

    def on_routes_set(self, df_routes):
        if not self.canvas_slave.df_routes.equals(df_routes):
            self.canvas_slave.df_routes = df_routes
            self.canvas_slave.render()
            gtk.idle_add(self.canvas_slave.draw)
