# -*- coding: utf-8 -*-
from datetime import datetime
import logging
import subprocess as sp
import sys

from cairo_helpers.surface import flatten_surfaces
from logging_helpers import _L
from microdrop_utility.gui import register_shortcuts
from opencv_helpers.safe_cv import cv2
from pygst_utils.video_view.mode import VideoModeSelector
from pygst_utils.video_view.video_sink import Transform, VideoInfo
from pygtkhelpers.delegates import SlaveView
from pygtkhelpers.ui.views import find_closest
from pygtkhelpers.ui.views.surface import LayerAlphaController
from zmq_plugin.schema import decode_content_data
import gobject
import gtk
import numpy as np
import pandas as pd
import zmq

from .options import DeviceViewInfo, DebugView
from .plugin import DevicePluginConnection, DevicePlugin
from . import generate_plugin_name

logger = logging.getLogger(__name__)


class DmfDeviceViewBase(SlaveView):
    def __init__(self, device_canvas, hub_uri='tcp://localhost:31000',
                 plugin_name=None, allocation=None, video_transport='tcp',
                 video_host='*', video_port=None, debug_view=False):
        # Video sink socket info.
        self.socket_info = {'transport': video_transport,
                            'host': video_host,
                            'port': video_port}
        # Video source process (i.e., `Popen` instance).
        self.video_source_process = None

        self.device_canvas = device_canvas
        self._hub_uri = hub_uri
        self._plugin_name = plugin_name or generate_plugin_name()
        self._allocation = allocation
        self._debug_view = debug_view
        self.plugin = None
        self.socket_timeout_id = None
        self.heartbeat_timeout_id = None
        self.heartbeat_alive_timestamp = None
        self.route = None
        self.video_config = None
        self.modify_corners_undo = []
        self.modify_corners_redo = []
        super(DmfDeviceViewBase, self).__init__()

    def __del__(self):
        self.cleanup_video()

    def on_widget__destroy(self, widget):
        self.cleanup_video()

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
        self.box_settings = gtk.HBox()
        self.box_video = gtk.VBox()

        self.video_mode_slave = self.add_slave(VideoModeSelector(),
                                               'box_video')
        self.video_info_slave = self.add_slave(VideoInfo(), 'box_video')
        self.transform_slave = self.add_slave(Transform(), 'box_video')
        self.transform_slave.widget.set_sensitive(False)
        self.info_slave = self.add_slave(DeviceViewInfo(), 'box_video')
        if self._debug_view:
            self.debug_slave = self.add_slave(DebugView(), 'box_video')

        self.box_device = gtk.VBox()
        self.layer_alpha_slave = \
            self.add_slave(LayerAlphaController(self.device_canvas),
                           'box_device')
        # Get reference to button box containing "Show" and "Hide" buttons.
        button_box = (self.layer_alpha_slave.widget.get_children()[-1]
                      .get_children()[-1])
        # Add "Refresh device" button to button box.
        self.refresh_device_button = gtk.Button('Refresh device')
        self.refresh_device_button.connect('clicked', lambda *args:
                                           self.plugin
                                           .execute_async('microdrop'
                                                          '.device_info_plugin',
                                                          'get_device'))
        button_box.pack_start(self.refresh_device_button, False, False, 0)
        button_box.show_all()

        self.box_settings.pack_start(self.box_video, False, False, 0)
        self.box_settings.pack_start(self.box_device, True, True, 0)

        self.widget.pack_start(self.box_settings, False, False, 0)

        self.canvas_slave = self.add_slave(self.device_canvas, 'widget')
        self.canvas_slave.video_sink.connect('frame-rate-update',
                                             self.on_frame_rate_update)

    def create_ui(self):
        super(DmfDeviceViewBase, self).create_ui()
        self.widget.set_orientation(gtk.ORIENTATION_VERTICAL)
        self.create_slaves()

        self.info_slave.connection_count = self.canvas_slave.connection_count
        self.info_slave.electrode_count = self.canvas_slave.shape_count

        # Pack load and save sections to end of row.
        for slave in self.slaves:
            if slave is self.canvas_slave:
                continue
            slave.widget.parent.set_child_packing(slave.widget, False, False,
                                                  5, gtk.PACK_START)

        def configure_window(*args):
            if self._allocation is not None:
                self.set_allocation(self._allocation)
                logger.info('[map-event] set allocation %s', self._allocation)
                self.canvas_slave.widget.disconnect(self.map_event_id)
        self.map_event_id = self.canvas_slave.widget.connect('map-event',
                                                             configure_window)

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
                     '<Control>z': lambda *args: self.undo(),
                     '<Control>y': lambda *args: self.redo(),
                     'A': lambda *args: control_protocol('first_step'),
                     'S': lambda *args: control_protocol('prev_step'),
                     'D': lambda *args: control_protocol('next_step'),
                     'F': lambda *args: control_protocol('last_step')}
        register_shortcuts(self.widget.parent, shortcuts)

    def cleanup(self):
        for timeout_id in (self.socket_timeout_id, self.heartbeat_timeout_id):
            if timeout_id is not None:
                gobject.source_remove(timeout_id)
        if self.plugin is not None:
            self.plugin = None
        self.cleanup_video()

    def cleanup_video(self):
        '''
        .. versionchanged:: 0.6.1
            Log terminated video source process ID.
        '''
        if self.video_source_process is not None:
            self.video_source_process.terminate()
            logger.info('Terminated video process: %s',
                        self.video_source_process.pid)
            self.video_source_process = None

    def terminate(self):
        self.cleanup()
        gtk.main_quit()

    ###########################################################################
    # Device canvas event callbacks
    ###########################################################################
    def on_canvas_slave__electrode_mouseover(self, slave, data):
        self.info_slave.electrode_id = data['electrode_id']
        try:
            channels = (self.canvas_slave.electrode_channels
                        .ix[data['electrode_id']])
        except KeyError:
            # Electrode is not mapped to any channels.
            logger.debug('Electrode (%s) is not mapped to any channels.',
                         data['electrode_id'])
            self.info_slave.channels = ''
        else:
            self.info_slave.channels = ', '.join(map(str, channels))

    def on_canvas_slave__electrode_mouseout(self, slave, data):
        self.info_slave.electrode_id = ''
        self.info_slave.channels = ''

    def on_canvas_slave__electrode_selected(self, slave, data):
        '''
        .. versionchanged:: 0.11
            Clear any temporary routes (drawn while mouse is down) from routes
            list.

        .. versionchanged:: 0.11.3
            Clear temporary routes by setting ``df_routes`` property of
            :attr:`canvas_slave`.
        '''
        if self.plugin is None:
            return
        # XXX Negative `route_i` corresponds to temporary route being
        # drawn.  Since electrode selection terminates route drawing, clear any
        # rows corresponding to negative `route_i` values from the routes
        # table.
        slave.df_routes = slave.df_routes.loc[slave.df_routes.route_i >=
                                              0].copy()
        state = self.canvas_slave.electrode_states.get(data['electrode_id'], 0)
        self.plugin.execute_async('microdrop.electrode_controller_plugin',
                                  'set_electrode_states',
                                  electrode_states=pd
                                  .Series([not state],
                                          index=[data['electrode_id']]))

    def on_canvas_slave__electrode_pair_selected(self, slave, data):
        '''
        Process pair of selected electrodes.

        For now, this consists of finding the shortest path between the two
        electrodes and appending it to the list of droplet routes for the
        current step.

        Note that the droplet routes for a step are stored in a frame/table in
        the `DmfDeviceController` step options.


        .. versionchanged:: 0.11
            Clear any temporary routes (drawn while mouse is down) from routes
            list.

        .. versionchanged:: 0.11.3
            Clear temporary routes by setting ``df_routes`` property of
            :attr:`canvas_slave`.
        '''
        import networkx as nx

        source_id = data['source_id']
        target_id = data['target_id']

        if self.canvas_slave.device is None or self.plugin is None:
            return
        # XXX Negative `route_i` corresponds to temporary route being
        # drawn.  Since electrode pair selection terminates route drawing,
        # clear any rows corresponding to negative `route_i` values from the
        # routes table.
        slave.df_routes = slave.df_routes.loc[slave.df_routes.route_i >=
                                              0].copy()
        try:
            shortest_path = self.canvas_slave.device.find_path(source_id,
                                                               target_id)
            self.plugin.execute_async('droplet_planning_plugin',
                                      'add_route', drop_route=shortest_path)
        except nx.NetworkXNoPath:
            logger.error('No path found between %s and %s.', source_id,
                         target_id)

    def on_canvas_slave__route_selected(self, slave, route):
        logger.debug('Route selected: %s', route)
        self.plugin.execute_async('droplet_planning_plugin',
                                  'add_route', drop_route=route.electrode_ids)

    def on_canvas_slave__route_electrode_added(self, slave, electrode_id):
        '''
        .. versionchanged:: 0.11
            Draw temporary route currently being formed.

        .. versionchanged:: 0.11.3
            Update routes table by setting ``df_routes`` property of
            :attr:`canvas_slave`.
        '''
        logger.debug('Route electrode added: %s', electrode_id)
        if slave._route.electrode_ids is None:
            return
        df_route = pd.DataFrame([[-1, e, i] for i, e in
                                 enumerate(slave._route.electrode_ids)],
                                columns=['route_i', 'electrode_i',
                                         'transition_i'])
        # XXX Negative `route_i` corresponds to temporary route being
        # drawn.  Append row entries for temporary route to existing routes
        # table.
        df_routes = slave.df_routes.loc[slave.df_routes.route_i >= 0].copy()
        self.canvas_slave.df_routes = pd.concat([df_routes, df_route])

    def on_canvas_slave__surfaces_reset(self, slave, df_surfaces):
        logger.debug('[surfaces reset]\n%s', df_surfaces)
        self.layer_alpha_slave.set_surfaces(df_surfaces)

    def on_layer_alpha_slave__alpha_changed(self, slave, name, alpha):
        logger.debug('[alpha changed] %s -> %.2f', name, alpha)
        self.canvas_slave.set_surface_alpha(name, alpha)
        self.canvas_slave.cairo_surface = flatten_surfaces(self.canvas_slave
                                                           .df_surfaces)
        gtk.idle_add(self.canvas_slave.draw)

    def on_layer_alpha_slave__layers_reordered(self, slave, rows_index):
        reordered_index = self.canvas_slave.df_surfaces.index[rows_index]
        logger.info('[layers reordered] %s', reordered_index)
        self.canvas_slave.reorder_surfaces(reordered_index)
        gtk.idle_add(self.canvas_slave.draw)

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
                                    silent=True)
            except IOError:
                self.on_heartbeat_error()
            else:
                self.heartbeat_alive_timestamp = datetime.now()
                logger.debug('Hub connection alive as of %s',
                             self.heartbeat_alive_timestamp)
                return True

    def on_heartbeat_error(self):
        '''
        .. versionchanged:: 0.6.3
            Close app after cleaning up video process.

        .. versionchanged:: 0.6.4
            Do not close application due to heartbeat timeout.  Instead,
            require explicit shutdown.
        '''
        logger.debug('Timed out waiting for heartbeat ping.')

    def on_plugin_connected(self, plugin):
        self.plugin = plugin

        # Block until device is retrieved from device info plugin.
        self.plugin.execute_async('microdrop.device_info_plugin',
                                  'get_device')
        # Periodically process outstanding plugin socket messages.
        self.socket_timeout_id = gtk.timeout_add(25, self.plugin.check_sockets)
        # Periodically ping hub to verify connection is alive.
        self.heartbeat_timeout_id = gtk.timeout_add(2000, self.ping_hub)

    def on_device_loaded(self, device):
        self.canvas_slave.set_device(device)
        self.info_slave.connection_count = self.canvas_slave.connection_count
        self.info_slave.electrode_count = self.canvas_slave.shape_count
        self.plugin.request_refresh()

    def on_electrode_states_updated(self, states):
        '''
        .. versionchanged:: 0.12
            Refactor to use :meth:`on_electrode_states_set`.
        '''
        states['electrode_states'] = \
            states['electrode_states'].combine_first(self.canvas_slave
                                                     .electrode_states)
        self.on_electrode_states_set(states)

    def on_electrode_states_set(self, states):
        '''
        Render and draw updated **static** electrode actuations layer on
        canvas.
        '''
        if (self.canvas_slave.electrode_states
                .equals(states['electrode_states'])):
            return

        self.canvas_slave.electrode_states = states['electrode_states']

        surface = self.canvas_slave.render_static_electrode_state_shapes()
        self.canvas_slave.set_surface('static_electrode_state_shapes', surface)
        self.canvas_slave.cairo_surface = flatten_surfaces(self.canvas_slave
                                                           .df_surfaces)
        gobject.idle_add(self.canvas_slave.draw)

    def on_dynamic_electrode_states_set(self, states):
        '''
        Render and draw updated **dynamic** electrode actuations layer on
        canvas.


        .. versionadded:: 0.12
        '''
        self.canvas_slave._dynamic_electrodes = states

        surface = self.canvas_slave.render_dynamic_electrode_state_shapes()
        self.canvas_slave.set_surface('dynamic_electrode_state_shapes',
                                      surface)
        self.canvas_slave.cairo_surface = flatten_surfaces(self.canvas_slave
                                                           .df_surfaces)
        gobject.idle_add(self.canvas_slave.draw)

    ###########################################################################
    # ## Slave signal handling ##
    def on_transform_slave__transform_reset(self, slave):
        logger.info('[View] reset transform')
        self.canvas_slave.default_corners = {}
        self.canvas_slave.reset_canvas_corners()
        self.canvas_slave.reset_frame_corners()
        self.canvas_slave.update_transforms()

    def on_transform_slave__transform_rotate_left(self, slave):
        self.canvas_slave.df_canvas_corners[:] = np.roll(self.canvas_slave
                                                         .df_canvas_corners
                                                         .values, 1, axis=0)
        self.canvas_slave.update_transforms()

    def on_transform_slave__transform_rotate_right(self, slave):
        self.canvas_slave.df_canvas_corners[:] = np.roll(self.canvas_slave
                                                         .df_canvas_corners
                                                         .values, -1, axis=0)
        self.canvas_slave.update_transforms()

    def on_transform_slave__transform_modify_toggled(self, slave, active):
        if active:
            self.canvas_slave.mode = 'register_video'
            self.layer_alpha_slave.set_alpha('registration', 1.)
        else:
            self.canvas_slave.mode = 'control'
            self.layer_alpha_slave.set_alpha('registration', 0.)

    def redo(self):
        if self.modify_corners_redo and (self.canvas_slave.mode ==
                                         'register_video'):
            # Save current state of corners to allow *undo*.
            corners_state = {'df_frame_corners':
                             self.canvas_slave.df_frame_corners.copy(),
                             'df_canvas_corners':
                             self.canvas_slave.df_canvas_corners.copy()}
            self.modify_corners_undo.append(corners_state)

            # Apply previous corners state (i.e., redo).
            corners_state = self.modify_corners_redo.pop()
            self.canvas_slave.df_frame_corners[:] = (corners_state
                                                     ['df_frame_corners'])
            self.canvas_slave.df_canvas_corners[:] = (corners_state
                                                      ['df_canvas_corners'])
            self.canvas_slave.update_transforms()

    def undo(self):
        if self.modify_corners_undo and (self.canvas_slave.mode ==
                                         'register_video'):
            # Save current state of corners to allow *redo*.
            corners_state = {'df_frame_corners':
                             self.canvas_slave.df_frame_corners.copy(),
                             'df_canvas_corners':
                             self.canvas_slave.df_canvas_corners.copy()}
            self.modify_corners_redo.append(corners_state)

            # Apply previous corners state (i.e., undo).
            corners_state = self.modify_corners_undo.pop()
            self.canvas_slave.df_frame_corners[:] = (corners_state
                                                     ['df_frame_corners'])
            self.canvas_slave.df_canvas_corners[:] = (corners_state
                                                      ['df_canvas_corners'])
            self.canvas_slave.update_transforms()

    def on_video_mode_slave__video_config_selected(self, slave, video_config):
        logger.info('video config selected\n%s', video_config)
        self.set_video_config(video_config)

    def disable_video(self):
        self.canvas_slave.disable()
        # Hide registration layer (if visible).
        self.layer_alpha_slave.set_alpha('registration', 0.)
        self.cleanup_video()

    def enable_video(self):
        if all([self.video_config is not None,
                self.video_source_process is None]):
            self.set_video_config(self.video_config)

    def set_video_config(self, video_config):
        '''
        .. versionchanged:: 0.6.1
            Log video source process ID.
        '''
        self.video_config = video_config
        if video_config is None:
            self.disable_video()
            return

        py_exe = sys.executable
        port = self.canvas_slave.video_sink.socket_info['port']
        transport = self.canvas_slave.video_sink.socket_info['transport']
        host = (self.canvas_slave.video_sink.socket_info['host']
                .replace('*', 'localhost'))

        # Terminate existing process (if running).
        self.cleanup_video()

        # Launch new video source process using JSON serialized video
        # configuration.
        command = [py_exe, '-m', 'pygst_utils.video_view.video_source',
                   'fromjson', '-p', str(port), transport, host,
                   video_config.to_json()]
        logger.info(' '.join(command))
        self.video_source_process = sp.Popen(command)
        logger.info('Launched video source process: %s',
                    self.video_source_process.pid)
        self.canvas_slave.enable()

    def on_frame_rate_update(self, slave, frame_rate, dropped_rate):
        self.video_info_slave.frames_per_second = frame_rate
        self.video_info_slave.dropped_rate = dropped_rate

    def on_canvas_slave__routes_set(self, slave, df_routes):
        '''
        .. versionadded:: 0.11.3
        '''
        self.canvas_slave.set_surface('routes',
                                      self.canvas_slave.render_routes())
        self.canvas_slave.cairo_surface = flatten_surfaces(self.canvas_slave
                                                           .df_surfaces)
        gtk.idle_add(self.canvas_slave.draw)

    def on_canvas_slave__point_pair_selected(self, slave, data):
        if any([slave.canvas is None or not self.transform_slave.modify or not
                slave.enabled]):
            return
        # Translate canvas event coordinates to shape coordinate space.
        transform = slave.canvas.canvas_to_shapes_transform
        shape_start_xy = transform.dot([data['start_event'].x,
                                        data['start_event'].y, 1.])[:2]
        shape_end_xy = transform.dot([data['end_event'].x, data['end_event'].y,
                                      1.])[:2]

        slave = self.canvas_slave
        # Map GTK event x/y coordinates to the video frame coordinate space.
        frame_point_i = \
            cv2.perspectiveTransform(np.array([[shape_start_xy]], dtype=float),
                                     slave.canvas_to_frame_map).ravel()
        # Find the closest corner point in the frame to the starting point.
        frame_corner_i = find_closest(slave.df_frame_corners, frame_point_i)
        # Find the closest corner point in the canvas to the end point.
        canvas_corner_i = find_closest(slave.df_canvas_corners, shape_start_xy)

        # Save current state of corners to allow undo.
        corners_state = {'df_frame_corners':
                         self.canvas_slave.df_frame_corners.copy(),
                         'df_canvas_corners':
                         self.canvas_slave.df_canvas_corners.copy()}
        self.modify_corners_undo.append(corners_state)
        # Clear redo queue to start new undo branch.
        self.modify_corners_redo = []

        # Replace the corresponding corner point coordinates with the
        # respective new points.
        slave.df_frame_corners.iloc[frame_corner_i.name] = frame_point_i
        slave.df_canvas_corners.iloc[canvas_corner_i.name] = shape_end_xy
        slave.update_transforms()

    def on_canvas_slave__video_disabled(self, slave):
        self.transform_slave.widget.set_sensitive(False)

    def on_canvas_slave__video_enabled(self, slave):
        self.transform_slave.widget.set_sensitive(True)

    def on_canvas_slave__global_command(self, slave, group, command, data):
        def command_callback(reply):
            _L().info('%s.%s()', group, command)
            # Decode content to raise error, if necessary.
            try:
                decode_content_data(reply)
            except Exception:
                _L().error('Global command error.', exc_info=True)
        self.plugin.execute_async(group, command, callback=command_callback)

    def on_canvas_slave__electrode_command(self, slave, group, command,
                                           electrode_data):
        def command_callback(reply):
            logger.info('[on_canvas_slave__electrode_command] %s.%s(%r)',
                        group, command, electrode_data['electrode_id'])
            # Decode content to raise error, if necessary.
            try:
                decode_content_data(reply)
            except Exception:
                logger.error('Electrode command error: %s.%s(%r)', group,
                             command, electrode_data['electrode_id'],
                             exc_info=True)
        self.plugin.execute_async(group, command,
                                  electrode_id=electrode_data['electrode_id'],
                                  callback=command_callback)

    def on_canvas_slave__route_command(self, slave, group, command,
                                       route_data):
        def command_callback(reply):
            logger.info('[on_canvas_slave__route_command] %s.%s(%r)', group,
                        command, route_data['route_ids'])
            # Decode content to raise error, if necessary.
            try:
                decode_content_data(reply)
            except Exception:
                logger.error('Route command error: %s.%s(%r)', group, command,
                             route_data['route_ids'], exc_info=True)
        self.plugin.execute_async(group, command,
                                  route_ids=route_data['route_ids'],
                                  callback=command_callback)


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
