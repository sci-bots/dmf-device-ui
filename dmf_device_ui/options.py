# -*- coding: utf-8 -*-
from collections import OrderedDict

import gtk
from pygtkhelpers.utils import gsignal
from pygtkhelpers.delegates import SlaveView


class DebugView(SlaveView):
    def create_ui(self):
        super(DebugView, self).create_ui()
        self.widget.set_orientation(gtk.ORIENTATION_HORIZONTAL)

        self.ipython_button = gtk.Button('IPython...')
        self.ipython_button.set_tooltip_text('Launch embedded IPython shell '
                                             '(`parent` is reference to parent'
                                             ' object.)')

        self.widget.pack_start(self.ipython_button, False, False, 0)

    def on_ipython_button__clicked(self, button):
        import IPython
        import inspect

        # Get parent from stack
        parent_stack = inspect.stack()[1]
        parent = parent_stack[0].f_locals['self']
        IPython.embed()


class DeviceViewInfo(SlaveView):
    def create_ui(self):
        super(DeviceViewInfo, self).create_ui()
        self.widget.set_orientation(gtk.ORIENTATION_HORIZONTAL)

        self.labels = OrderedDict([('electrode_count', gtk.Label()),
                                   ('connection_count', gtk.Label()),
                                   ('electrode_tag', gtk.Label()),
                                   ('electrode_id', gtk.Label())])

        self.labels['electrode_tag'].set_markup('<b>Electrode id: </b>')

        for i, (k, label) in enumerate(self.labels.iteritems()):
            self.widget.pack_start(label, False, False,
                                   10 if i >= 1 and i < len(self.labels) - 2
                                   else 0)

    def __setattr__(self, name, value):
        if name == 'electrode_id':
            self.labels[name].set_markup(value)
        elif name == 'electrode_count':
            self.labels[name].set_markup('<b>Electrode count:</b> %s' % value)
        elif name == 'connection_count':
            self.labels[name].set_markup('<b>Connection count:</b> %s' % value)
        else:
            super(DeviceViewInfo, self).__setattr__(name, value)


class DeviceViewOptions(SlaveView):
    gsignal('labels-toggled', bool)
    gsignal('connections-toggled', bool)
    gsignal('connections-alpha-changed', float)

    def create_ui(self):
        super(DeviceViewOptions, self).create_ui()
        self.widget.set_orientation(gtk.ORIENTATION_HORIZONTAL)

        self.labels_button = gtk.CheckButton('Labels')
        self.connections_button = gtk.CheckButton('Connections')
        self.connections_alpha_label = gtk.Label('Opacity:')

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

        widgets = [self.labels_button, self.connections_button,
                   self.connections_alpha_label, self.connections_alpha_scale]
        for w in widgets:
            self.widget.pack_start(w, False, False, 5)

    def on_labels_button__toggled(self, button):
        self.emit('labels-toggled', button.get_property('active'))

    def on_connections_button__toggled(self, button):
        self.emit('connections-toggled', button.get_property('active'))

    def on_connections_alpha_adjustment__value_changed(self, adjustment):
        self.emit('connections-alpha-changed', adjustment.value / 100.)

    @property
    def connections_alpha(self):
        return self.connections_button.get_property('active')

    @connections_alpha.setter
    def connections_alpha(self, value):
        self.connections_alpha_adjustment.value = value * 100

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


class DeviceLoader(SlaveView):
    gsignal('device-loaded', object)

    def create_ui(self):
        super(DeviceLoader, self).create_ui()
        self.widget.set_orientation(gtk.ORIENTATION_HORIZONTAL)

        self.plugin_uri_label = gtk.Label('Plugin hub URI:')
        self.plugin_uri = gtk.Entry()
        self.plugin_uri.set_text('tcp://localhost:31000')
        self.plugin_uri.set_width_chars(len(self.plugin_uri.get_text()))
        self.ui_plugin_name_label = gtk.Label('UI plugin name:')
        self.ui_plugin_name = gtk.Entry()
        self.ui_plugin_name.set_text('dmf-device-ui')
        self.ui_plugin_name.set_width_chars(len(self.ui_plugin_name
                                                .get_text()))
        self.device_plugin_name_label = gtk.Label('Device plugin name:')
        self.device_plugin_name = gtk.Entry()
        self.device_plugin_name.set_text('wheelerlab.device_info_plugin')
        self.device_plugin_name.set_width_chars(len(self.device_plugin_name
                                                    .get_text()))
        self.load_device_button = gtk.Button('Load device')

        widgets = [self.plugin_uri_label, self.plugin_uri,
                   self.ui_plugin_name_label, self.ui_plugin_name,
                   self.device_plugin_name_label, self.device_plugin_name,
                   self.load_device_button]
        for w in widgets:
            self.widget.pack_start(w, False, False, 5)

    def on_load_device_button__clicked(self, event):
        from zmq_plugin.plugin import Plugin

        hub_uri = self.plugin_uri.get_text()
        ui_plugin_name = self.ui_plugin_name.get_text()
        plugin = Plugin(ui_plugin_name, hub_uri); plugin.reset()
        device = plugin.execute('wheelerlab.device_info_plugin', 'get_device')
        self.emit('device-loaded', device)

