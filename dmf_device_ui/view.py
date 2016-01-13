# -*- coding: utf-8 -*-
from collections import OrderedDict
from datetime import datetime
import logging

from microdrop_utility.gui import register_shortcuts
from pygtkhelpers.delegates import SlaveView
from pygtkhelpers.ui.views import composite_surface
import gobject
import gtk
import pandas as pd
import zmq

from .options import DeviceViewOptions, DeviceViewInfo, DebugView
from .plugin import DevicePluginConnection, DevicePlugin
from . import gtk_wait, generate_plugin_name

logger = logging.getLogger(__name__)


class DmfDeviceViewBase(SlaveView):
    def __init__(self, device_canvas, hub_uri='tcp://localhost:31000',
                 plugin_name=None, allocation=None):
        self.device_canvas = device_canvas
        self._hub_uri = hub_uri
        self._plugin_name = plugin_name or generate_plugin_name()
        self._allocation = allocation
        self.plugin = None
        self.socket_timeout_id = None
        self.heartbeat_timeout_id = None
        self.heartbeat_alive_timestamp = None
        self.route = None
        super(DmfDeviceViewBase, self).__init__()

    def get_allocation(self):
        width, height = self.widget.parent.get_size()
        x, y = self.widget.parent.get_position()
        return {'x': x, 'y': y, 'width': width, 'height': height}

    def set_allocation(self, allocation):
        if allocation.get('width') is not None and (allocation.get('height') is
                                                    not None):
            self.widget.parent.resize(allocation['width'], allocation['height'])
        if allocation.get('x') is not None and allocation.get('y') is not None:
            self.widget.parent.move(allocation['x'], allocation['y'])

    def create_slaves(self):
        self.info_slave = self.add_slave(DeviceViewInfo(), 'widget')
        self.options_slave = self.add_slave(DeviceViewOptions(), 'widget')
        self.debug_slave = self.add_slave(DebugView(), 'widget')
        self.canvas_slave = self.add_slave(self.device_canvas, 'widget')

    def create_ui(self):
        super(DmfDeviceViewBase, self).create_ui()
        self.widget.set_orientation(gtk.ORIENTATION_VERTICAL)
        self.create_slaves()

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

        def configure_window(*args):
            if self._allocation is not None:
                self.set_allocation(self._allocation)
        self.canvas_slave.widget.connect('map-event', configure_window)

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

    ###########################################################################
    # Options UI element callbacks
    ###########################################################################
    def on_options_slave__labels_toggled(self, slave, active):
        self.canvas_slave.render()
        gtk.idle_add(self.canvas_slave.draw)

    def on_options_slave__connections_toggled(self, slave, active):
        surfaces = self.canvas_slave.surfaces
        if not active:
            surfaces = OrderedDict([(k, v) for k, v in surfaces.iteritems()
                                    if k != 'connections'])
        self.canvas_slave.cairo_surface = composite_surface(surfaces.values())
        gtk.idle_add(self.canvas_slave.draw)

    def on_options_slave__connections_alpha_changed(self, slave, alpha):
        self.canvas_slave.connections_alpha = alpha
        self.canvas_slave.surfaces['connections'] = \
            self.canvas_slave.render_default_connections()
        self.canvas_slave.cairo_surface = self.canvas_slave.flatten_surfaces()
        gtk.idle_add(self.canvas_slave.draw)

    ###########################################################################
    # Device canvas event callbacks
    ###########################################################################
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

    def on_canvas_slave__route_selected(self, slave, route):
        print 'Route selected:', route
        self.plugin.execute_async('wheelerlab.droplet_planning_plugin',
                                  'add_route', drop_route=route.electrode_ids)

    def on_canvas_slave__route_electrode_added(self, slave, electrode_id):
        print 'Route electrode added:', electrode_id

    def on_canvas_slave__clear_routes(self, slave, electrode_id):
        def refresh_routes(reply):
            # Request routes.
            self.plugin.execute_async('wheelerlab.droplet_planning_plugin',
                                      'get_routes')
        self.plugin.execute_async('wheelerlab.droplet_planning_plugin',
                                  'clear_routes', electrode_id=electrode_id,
                                  callback=refresh_routes)

    def on_canvas_slave__clear_electrode_states(self, slave):
        if self.plugin is not None:
            (self.plugin.execute('wheelerlab.electrode_controller_plugin',
                                 'set_electrode_states',
                                 electrode_states=
                                 pd.Series(0, dtype=int,
                                           index=self.canvas_slave.device
                                           .electrodes)))

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
                self.plugin.execute(self.plugin.hub_name, 'ping', timeout_s=1,
                                    wait_func=gtk_wait)
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

    def on_plugin_connected(self, plugin):
        self.plugin = plugin

        # Block until device is retrieved from device info plugin.
        self.plugin.execute_async('wheelerlab.device_info_plugin',
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
            self.canvas_slave.surfaces['shapes'] = (self.canvas_slave
                                                    .render_shapes())
            self.canvas_slave.cairo_surface = (self.canvas_slave
                                               .flatten_surfaces())
            gtk.idle_add(self.canvas_slave.draw)

    def on_electrode_states_set(self, states):
        if not (self.canvas_slave.electrode_states
                .equals(states['electrode_states'])):
            self.canvas_slave.electrode_states = states['electrode_states']
            self.canvas_slave.surfaces['shapes'] = (self.canvas_slave
                                                    .render_shapes())
            self.canvas_slave.cairo_surface = (self.canvas_slave
                                               .flatten_surfaces())
            gtk.idle_add(self.canvas_slave.draw)

    def on_routes_set(self, df_routes):
        if not self.canvas_slave.df_routes.equals(df_routes):
            self.canvas_slave.df_routes = df_routes
            self.canvas_slave.surfaces['routes'] = (self.canvas_slave
                                                    .render_routes())
            self.canvas_slave.cairo_surface = (self.canvas_slave
                                               .flatten_surfaces())
            gtk.idle_add(self.canvas_slave.draw)


class DmfDeviceFixedHubView(DmfDeviceViewBase):
    '''
    DMF device user interface (hub URI and plugin name fixed upon creation).
    '''
    def connect_plugin(self):
        logger.info('Connect plugin')
        plugin = DevicePlugin(self, self._plugin_name, self._hub_uri,
                              subscribe_options={zmq.SUBSCRIBE: ''})
        plugin.reset()
        self.on_plugin_connected(plugin)
        logger.info('Plugin connected.')


class DmfDeviceConfigurableHubView(DmfDeviceViewBase):
    '''
    DMF device user interface with configurable hub URI and plugin name.

    Plugin connection is only established upon clicking the `"Connect"` button.
    '''

    def cleanup(self):
        self.plugin_slave.reset()
        super(DmfDeviceConfigurableHubView, self).cleanup()

    def create_slaves(self):
        self.plugin_slave =\
            self.add_slave(DevicePluginConnection(self, self._hub_uri,
                                                  self._plugin_name), 'widget')
        super(DmfDeviceConfigurableHubView, self).create_slaves()

    def on_plugin_slave__plugin_connected(self, slave, plugin):
        self.on_plugin_connected(plugin)
