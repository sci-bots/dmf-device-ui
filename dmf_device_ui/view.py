# -*- coding: utf-8 -*-
import gtk
from pygtkhelpers.delegates import SlaveView
from .options import DeviceViewOptions, DeviceViewInfo, DebugView


class DmfDeviceView(SlaveView):
    def __init__(self, device_canvas):
        self.device_canvas = device_canvas
        super(DmfDeviceView, self).__init__()

    def create_ui(self):
        super(DmfDeviceView, self).create_ui()
        self.widget.set_orientation(gtk.ORIENTATION_VERTICAL)
        self.info_slave = self.add_slave(DeviceViewInfo(), 'widget')
        self.options_slave = self.add_slave(DeviceViewOptions(), 'widget')
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
