# -*- coding: utf-8 -*-
import json
import logging

from pygtkhelpers.delegates import SlaveView
from pygtkhelpers.utils import gsignal
from zmq_plugin.plugin import Plugin
from zmq_plugin.schema import decode_content_data
import gtk
import zmq

from . import generate_plugin_name

logger = logging.getLogger(__name__)


class DevicePlugin(Plugin):
    def __init__(self, parent, *args, **kwargs):
        self.parent = parent
        super(DevicePlugin, self).__init__(*args, **kwargs)

    def check_sockets(self):
        '''
        Check for new messages on sockets and respond accordingly.
        '''
        try:
            msg_frames = (self.command_socket
                          .recv_multipart(zmq.NOBLOCK))
        except zmq.Again:
            pass
        else:
            self.on_command_recv(msg_frames)

        try:
            msg_frames = (self.subscribe_socket
                          .recv_multipart(zmq.NOBLOCK))
            source, target, msg_type, msg_json = msg_frames

            if ((source == 'wheelerlab.device_info_plugin') and
                (msg_type == 'execute_reply')):
                msg = json.loads(msg_json)
                if msg['content']['command'] == 'get_device':
                    data = decode_content_data(msg)
                    if data is not None:
                        self.parent.on_device_loaded(data)
            elif ((source == 'wheelerlab.electrode_controller_plugin') and
                (msg_type == 'execute_reply')):
                msg = json.loads(msg_json)
                if msg['content']['command'] in ('set_electrode_state',
                                                 'set_electrode_states'):
                    data = decode_content_data(msg)
                    if data is None:
                        print msg
                    else:
                        #self.emit('electrode-states-updated', data)
                        self.parent.on_electrode_states_updated(data)
                elif msg['content']['command'] == 'get_channel_states':
                    data = decode_content_data(msg)
                    if data is None:
                        print msg
                    else:
                        #self.emit('electrode-states-set', data)
                        self.parent.on_electrode_states_set(data)
            elif ((source == 'wheelerlab.droplet_planning_plugin') and
                  (msg_type == 'execute_reply')):
                msg = json.loads(msg_json)
                if msg['content']['command'] in ('add_route', ):
                    self.execute_async('wheelerlab.droplet_planning_plugin',
                                       'get_routes')
                elif msg['content']['command'] in ('get_routes', ):
                    data = decode_content_data(msg)
                    #self.emit('routes-set', data)
                    self.parent.on_routes_set(data)
            else:
                self.most_recent = msg_json
        except zmq.Again:
            pass
        except:
            logger.error('Error processing message from subscription '
                         'socket.', exc_info=True)

        return True

    def request_refresh(self):
        # Request electrode/channel states.
        self.execute_async('wheelerlab.electrode_controller_plugin',
                           'get_channel_states')
        # Request routes.
        self.execute_async('wheelerlab.droplet_planning_plugin', 'get_routes')

    def on_execute__get_allocation(self, request):
        return self.parent.get_allocation()

    def on_execute__set_allocation(self, request):
        data = decode_content_data(request)
        self.parent.set_allocation(data['allocation'])

    def on_execute__terminate(self, request):
        self.parent.terminate()

    def on_execute__get_corners(self, request):
        return {'allocation': self.parent.get_allocation(),
                'df_canvas_corners': self.parent.canvas_slave.df_canvas_corners,
                'df_frame_corners': self.parent.canvas_slave.df_frame_corners}

    def on_execute__get_default_corners(self, request):
        return self.parent.canvas_slave.default_corners

    def on_execute__set_default_corners(self, request):
        data = decode_content_data(request)
        if 'canvas' in data and 'frame' in data:
            for k in ('canvas', 'frame'):
                self.parent.canvas_slave.default_corners[k] = data[k]
        self.parent.canvas_slave.reset_canvas_corners()
        self.parent.canvas_slave.reset_frame_corners()
        self.parent.canvas_slave.update_transforms()

    def on_execute__set_corners(self, request):
        data = decode_content_data(request)
        if 'df_canvas_corners' in data and 'df_frame_corners' in data:
            for k in ('df_canvas_corners', 'df_frame_corners'):
                setattr(self.parent.canvas_slave, k, data[k])
        self.parent.canvas_slave.update_transforms()

    def on_execute__get_video_configs(self, request):
        return self.parent.video_mode_slave.configs

    def on_execute__get_video_config(self, request):
        return self.parent.video_config

    def on_execute__set_video_config(self, request):
        data = decode_content_data(request)
        compare_fields = ['device_name', 'width', 'height', 'name', 'fourcc',
                          'framerate']
        if data['video_config'] is None:
            i = None
        else:
            for i, row in self.parent.video_mode_slave.configs.iterrows():
                if (row[compare_fields] ==
                        data['video_config'][compare_fields]).all():
                    break
            else:
                i = None
        if i is None:
            logger.error('Unsupported video config:\n%s', data['video_config'])
            logger.error('Video configs:\n%s',
                         self.parent.video_mode_slave.configs)
            self.parent.video_mode_slave.config_combo.set_active(0)
        else:
            logger.error('Set video config (%d):\n%s', i + 1,
                         data['video_config'])
            self.parent.video_mode_slave.config_combo.set_active(i + 1)

    def on_execute__get_surface_alphas(self, request):
        logger.debug('[on_execute__get_surface_alphas] %s',
                     self.parent.canvas_slave.df_surfaces)
        return self.parent.canvas_slave.df_surfaces['alpha']

    def on_execute__set_surface_alphas(self, request):
        data = decode_content_data(request)
        logger.debug('[on_execute__set_surface_alphas] %s',
                     data['surface_alphas'])
        for name, alpha in data['surface_alphas'].iteritems():
            self.parent.canvas_slave.set_surface_alpha(name, alpha)


class PluginConnection(SlaveView):
    gsignal('plugin-connected', object)

    def __init__(self, hub_uri='tcp://localhost:31000', plugin_name=None):
        self._hub_uri = hub_uri
        self._plugin_name = (generate_plugin_name()
                             if plugin_name is None else plugin_name)
        super(PluginConnection, self).__init__()

    def create_ui(self):
        super(PluginConnection, self).create_ui()
        self.widget.set_orientation(gtk.ORIENTATION_VERTICAL)
        self.top_row = gtk.HBox()

        self.plugin_uri_label = gtk.Label('Plugin hub URI:')
        self.plugin_uri = gtk.Entry()
        self.plugin_uri.set_text(self._hub_uri)
        self.plugin_uri.set_width_chars(len(self.plugin_uri.get_text()))
        self.ui_plugin_name_label = gtk.Label('UI plugin name:')
        self.ui_plugin_name = gtk.Entry()
        self.ui_plugin_name.set_text(self._plugin_name)
        self.ui_plugin_name.set_width_chars(len(self.ui_plugin_name
                                                .get_text()))
        self.connect_button = gtk.Button('Connect')

        top_widgets = [self.plugin_uri_label, self.plugin_uri,
                       self.ui_plugin_name_label, self.ui_plugin_name,
                       self.connect_button]
        for w in top_widgets:
            self.top_row.pack_start(w, False, False, 5)
        for w in (self.top_row, ):
            self.widget.pack_start(w, False, False, 5)

    def create_plugin(self, plugin_name, hub_uri):
        return Plugin(plugin_name, hub_uri,
                      subscribe_options={zmq.SUBSCRIBE: ''})

    def init_plugin(self, plugin):
        # Initialize sockets.
        plugin.reset()
        return plugin

    def on_connect_button__clicked(self, event):
        '''
        Connect to Zero MQ plugin hub (`zmq_plugin.hub.Hub`) using the settings
        from the text entry fields (e.g., hub URI, plugin name).

        Emit `plugin-connected` signal with the new plugin instance after hub
        connection has been established.
        '''
        hub_uri = self.plugin_uri.get_text()
        ui_plugin_name = self.ui_plugin_name.get_text()

        plugin = self.create_plugin(ui_plugin_name, hub_uri)
        self.init_plugin(plugin)

        self.connect_button.set_sensitive(False)
        self.emit('plugin-connected', plugin)


class DevicePluginConnection(PluginConnection):
    plugin_class = DevicePlugin

    def __init__(self, parent, *args, **kwargs):
        self.parent = parent
        self.plugin = None
        super(DevicePluginConnection, self).__init__(*args, **kwargs)

    def create_plugin(self, plugin_name, hub_uri):
        self.reset()
        self.plugin = DevicePlugin(self.parent, plugin_name, hub_uri,
                                   subscribe_options={zmq.SUBSCRIBE: ''})
        return self.plugin

    def reset(self):
        if self.plugin is not None:
            self.plugin.close()
            self.plugin = None
        self.connect_button.set_sensitive(True)
