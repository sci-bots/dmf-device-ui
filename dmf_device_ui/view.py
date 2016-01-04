# -*- coding: utf-8 -*-
import gtk
import pandas as pd
from pygtkhelpers.delegates import SlaveView
from .options import (DeviceViewOptions, DeviceViewInfo, DebugView,
                      DeviceLoader)


class DmfDeviceView(SlaveView):
    def __init__(self, device_canvas):
        self.device_canvas = device_canvas
        super(DmfDeviceView, self).__init__()

    def create_ui(self):
        super(DmfDeviceView, self).create_ui()
        self.widget.set_orientation(gtk.ORIENTATION_VERTICAL)
        self.info_slave = self.add_slave(DeviceViewInfo(), 'widget')
        self.options_slave = self.add_slave(DeviceViewOptions(), 'widget')
        self.loader_slave = self.add_slave(DeviceLoader(), 'widget')
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
        print '[connections_alpha_changed] %s' % alpha
        self.canvas_slave.connections_alpha = alpha
        self.canvas_slave.render()
        gtk.idle_add(self.canvas_slave.draw)

    def on_canvas_slave__electrode_mouseover(self, slave, data):
        self.info_slave.electrode_id = data['electrode_id']

    def on_canvas_slave__electrode_mouseout(self, slave, data):
        self.info_slave.electrode_id = ''

    def on_canvas_slave__electrode_selected(self, slave, data):
        if self.loader_slave.plugin is not None:
            state = (self.canvas_slave.electrode_states
                     .get(data['electrode_id'], 0))
            (self.loader_slave.plugin
             .execute('wheelerlab.electrode_controller_plugin',
                      'set_electrode_states',
                      electrode_states=
                      pd.Series([not state], index=[data['electrode_id']])))

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

        if self.canvas_slave.device is None or (self.loader_slave.plugin is
                                                None):
            return
        try:
            shortest_path = self.canvas_slave.device.find_path(source_id,
                                                               target_id)
            plugin = self.loader_slave.plugin
            plugin.execute_async('wheelerlab.droplet_planning_plugin',
                                 'add_route', drop_route=shortest_path)
        except nx.NetworkXNoPath:
            print 'no path found'

    def on_loader_slave__device_loaded(self, slave, device):
        self.canvas_slave.set_device(device)
        self.loader_slave.request_refresh()

    def on_loader_slave__electrode_states_updated(self, slave, states):
        updated_electrode_states = \
            states['electrode_states'].combine_first(self.canvas_slave
                                                     .electrode_states)
        if not (self.canvas_slave.electrode_states
                .equals(updated_electrode_states)):
            self.canvas_slave.electrode_states = updated_electrode_states
            self.canvas_slave.render()
            gtk.idle_add(self.canvas_slave.draw)

    def on_loader_slave__electrode_states_set(self, slave, states):
        if not (self.canvas_slave.electrode_states
                .equals(states['electrode_states'])):
            self.canvas_slave.electrode_states = states['electrode_states']
            self.canvas_slave.render()
            gtk.idle_add(self.canvas_slave.draw)

    def on_loader_slave__routes_set(self, slave, df_routes):
        if not self.canvas_slave.df_routes.equals(df_routes):
            self.canvas_slave.df_routes = df_routes
            self.canvas_slave.render()
            gtk.idle_add(self.canvas_slave.draw)
