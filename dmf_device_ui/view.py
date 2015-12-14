# -*- coding: utf-8 -*-
import gtk
from pygtkhelpers.delegates import SlaveView
from .options import DeviceViewOptions


class DmfDeviceView(SlaveView):
    def __init__(self, device_canvas):
        self.device_canvas = device_canvas
        super(DmfDeviceView, self).__init__()

    def create_ui(self):
        super(DmfDeviceView, self).create_ui()
        self.widget.set_orientation(gtk.ORIENTATION_VERTICAL)
        self.options_slave = self.add_slave(DeviceViewOptions(), 'widget')
        self.canvas_slave = self.add_slave(self.device_canvas, 'widget')
        self.options_slave.connections = self.canvas_slave.connections_enabled

        # Pack load and save sections to end of row.
        self.widget.set_child_packing(self.options_slave.widget, False, False,
                                      0, gtk.PACK_START)

    def on_options_slave__labels_toggled(self, slave, active):
        self.canvas_slave.draw()

    def on_options_slave__connections_toggled(self, slave, active):
        self.canvas_slave.connections_enabled = active
        self.canvas_slave.draw()

    def on_options_slave__connections_alpha_changed(self, slave, alpha):
        print '[connections_alpha_changed] %s' % alpha
        self.canvas_slave.connections_alpha = alpha
        self.canvas_slave.draw()
