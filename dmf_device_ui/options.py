# -*- coding: utf-8 -*-
import gtk
from pygtkhelpers.utils import gsignal
from pygtkhelpers.delegates import SlaveView


class DeviceViewOptions(SlaveView):
    gsignal('labels-toggled', bool)
    gsignal('connections-toggled', bool)
    gsignal('connections-alpha-changed', float)

    def __init__(self):
        super(DeviceViewOptions, self).__init__()

    def create_ui(self):
        super(DeviceViewOptions, self).create_ui()
        self.widget.set_orientation(gtk.ORIENTATION_HORIZONTAL)

        self.labels_button = gtk.CheckButton('Labels')
        self.connections_button = gtk.CheckButton('Connections')
        self.connections_alpha_label = gtk.Label('Connections alpha')

        # Note that the page_size value only makes a difference for scrollbar
        # widgets, and the highest value you'll get is actually
        # (upper - page_size).
        # value, lower, upper, step_increment, page_increment, page_size
        self.connections_alpha_adjustment = gtk.Adjustment(100, 0, 110, 1, 10,
                                                           10)

        self.connections_alpha_scale = \
            gtk.HScale(self.connections_alpha_adjustment)
        self.connections_alpha_scale.set_size_request(200, 40)
        self.connections_alpha_scale.set_update_policy(gtk.UPDATE_DELAYED)
        self.connections_alpha_scale.set_digits(0)
        self.connections_alpha_scale.set_value_pos(gtk.POS_TOP)
        self.connections_alpha_scale.set_draw_value(True)

        self.widget.pack_start(self.labels_button, False, False, 0)
        self.widget.pack_start(self.connections_button, False, False, 0)
        self.widget.pack_start(self.connections_alpha_label, False, False, 0)
        self.widget.pack_start(self.connections_alpha_scale, False, False, 0)

    def on_labels_button__toggled(self, button):
        self.emit('labels-toggled', button.get_property('active'))

    def on_connections_button__toggled(self, button):
        self.emit('connections-toggled', button.get_property('active'))

    def on_connections_alpha_adjustment__value_changed(self, adjustment):
        self.emit('connections-alpha-changed', adjustment.value / 100.)

    @property
    def connections(self):
        return self.connections_button.get_property('active')

    @connections.setter
    def connections(self, active):
        self.connections_button.set_property('active', active)

    @property
    def labels(self):
        return self.labels_button.get_property('active')

    @labels.setter
    def labels(self, active):
        self.labels_button.set_property('active', active)
