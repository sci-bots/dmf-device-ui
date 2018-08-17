# -*- coding: utf-8 -*-
from collections import OrderedDict
import itertools
import functools as ft
import logging
import threading

from cairo_helpers.surface import flatten_surfaces
from logging_helpers import _L
from pygtkhelpers.ui.views.shapes_canvas_view import GtkShapesCanvasView
from pygtkhelpers.utils import gsignal
from pygst_utils.video_view.video_sink import VideoSink
from pygst_utils.video_view import np_to_cairo
from svg_model import compute_shape_centers
from svg_model.color import hex_color_to_rgba
import cairo
import debounce
import gtk
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class Route(object):
    '''
    Attributes
    ----------
    device : microdrop.dmf_device.DmfDevice
    electrode_ids : list
        Ordered list of **connected** electrodes ids.

        Represents an actuation sequence of electrodes that would support
        liquid movement between the first and last electrode.
    '''
    def __init__(self, device):
        self.device = device
        self.electrode_ids = []

    def __str__(self):
        return '<Route electrode_ids=%s>' % self.electrode_ids

    def append(self, electrode_id):
        '''
        Append the specified electrode to the route.

        The route is not modified (i.e., electrode is not appended) if
        electrode is not connected to the last electrode in the existing route.

        Parameters
        ----------
        electrode_id : str
            Electrode identifier.
        '''
        do_append = False

        if not self.electrode_ids:
            do_append = True
        elif self.device.shape_indexes.shape[0] > 0:
            source = self.electrode_ids[-1]
            target = electrode_id
            if not (source == target):
                source_id, target_id = self.device.shape_indexes[[source,
                                                                  target]]
                try:
                    if self.device.adjacency_matrix[source_id, target_id]:
                        # Electrodes are connected, so append target to current
                        # route.
                        do_append = True
                except IndexError:
                    logger.warning('Electrodes `%s` and `%s` are not '
                                   'connected.', source, target)

        if do_append:
            self.electrode_ids.append(electrode_id)
        return do_append



class DmfDeviceCanvas(GtkShapesCanvasView):
    '''
    Draw device layout from SVG file.

    Mouse events are handled as follows:

     - Click and release on the same electrode emits electrode selected signal.
     - Click on one electrode, drag, and release on another electrode emits
       electrode *pair* selected signal, with *source* electrode and *target*
       electrode.
     - Moving mouse cursor over electrode emits electrode mouse over signal.
     - Moving mouse cursor out of electrode emits electrode mouse out signal.

    Signals are emitted as gobject signals.  See `emit` calls for payload
    formats.
    '''
    gsignal('device-set', object)
    gsignal('electrode-command', str, str, object)
    gsignal('electrode-mouseout', object)
    gsignal('electrode-mouseover', object)
    gsignal('electrode-pair-selected', object)
    gsignal('electrode-selected', object)
    #: .. versionadded:: 0.13
    gsignal('global-command', str, str, object)
    gsignal('key-press', object)
    gsignal('key-release', object)
    gsignal('route-command', str, str, object)
    gsignal('route-electrode-added', object)
    gsignal('route-selected', object)
    #: .. versionadded:: 0.11.3
    gsignal('routes-set', object)
    gsignal('surface-rendered', str, object)
    gsignal('surfaces-reset', object)

    # Video signals
    gsignal('point-pair-selected', object)
    gsignal('video-enabled')
    gsignal('video-disabled')

    def __init__(self, connections_alpha=1., connections_color=1.,
                 transport='tcp', target_host='*', port=None, **kwargs):
        # Video sink socket info.
        self.socket_info = {'transport': transport,
                            'host': target_host,
                            'port': port}
        # Identifier for video incoming socket check.
        self.callback_id = None
        self._enabled = False  # Video enable
        self.start_event = None  # Video modify start click event
        # Matched corner points between canvas and video frame.  Used to
        # generate map between coordinate spaces.
        self.df_canvas_corners = pd.DataFrame(None, columns=['x', 'y'],
                                              dtype=float)
        self.df_frame_corners = pd.DataFrame(None, columns=['x', 'y'],
                                             dtype=float)
        # Matrix map from frame coordinates to canvas coordinates.
        self.frame_to_canvas_map = None
        # Matrix map from canvas coordinates to frame coordinates.
        self.canvas_to_frame_map = None
        # Shape of canvas (i.e., drawing area widget).
        self.shape = None

        self.mode = 'control'

        # Read SVG polygons into dataframe, one row per polygon vertex.
        df_shapes = pd.DataFrame(None, columns=['id', 'vertex_i', 'x', 'y'])
        self.device = None
        self.shape_i_column = 'id'

        # Save alpha for drawing connections.
        self.connections_alpha = connections_alpha

        # Save color for drawing connections.
        self.connections_color = connections_color

        #: ..versionadded:: 0.12
        self._dynamic_electrodes = pd.Series()
        self.reset_states()
        self.reset_routes()

        self.connections_attrs = {}
        self.last_pressed = None
        self.last_hovered = None
        self._route = None
        self.connections_enabled = (self.connections_alpha > 0)

        self.default_corners = {}  # {'canvas': None, 'frame': None}

        #: .. versionadded:: 0.13
        #:     Registered global commands
        self.global_commands = OrderedDict()
        # Registered electrode commands
        self.electrode_commands = OrderedDict()
        # Register test command
        #self.register_electrode_command('ping',
                                        #group='microdrop.device_info_plugin')
        # Registered route commands
        self.route_commands = OrderedDict()

        super(DmfDeviceCanvas, self).__init__(df_shapes, self.shape_i_column,
                                              **kwargs)

    @property
    def df_routes(self):
        '''
        .. versionadded:: 0.11.3
        '''
        return self._df_routes

    @df_routes.setter
    def df_routes(self, value):
        '''
        .. versionadded:: 0.11.3
        '''
        self._df_routes = value
        try:
            self.emit('routes-set', self._df_routes.copy())
        except TypeError:
            pass

    def reset_canvas_corners(self):
        self.df_canvas_corners = (self.default_corners
                                  .get('canvas',
                                       self.default_shapes_corners()))

    def reset_frame_corners(self):
        self.df_frame_corners = (self.default_corners
                                 .get('frame', self.default_frame_corners()))

    def default_shapes_corners(self):
        if self.canvas is None:
            return self.df_canvas_corners
        width, height = self.canvas.source_shape
        return pd.DataFrame([[0, 0], [width, 0], [width, height], [0, height]],
                            columns=['x', 'y'], dtype=float)

    def default_frame_corners(self):
        if self.video_sink.frame_shape is None:
            return self.df_frame_corners
        width, height = self.video_sink.frame_shape
        return pd.DataFrame([[0, 0], [width, 0], [width, height], [0, height]],
                            columns=['x', 'y'], dtype=float)

    def update_transforms(self):
        from opencv_helpers.safe_cv import cv2

        if (self.df_canvas_corners.shape[0] == 0 or
            self.df_frame_corners.shape[0] == 0):
            return

        self.canvas_to_frame_map = cv2.findHomography(self.df_canvas_corners
                                                      .values,
                                                      self.df_frame_corners
                                                      .values)[0]
        self.frame_to_canvas_map = cv2.findHomography(self.df_frame_corners
                                                      .values,
                                                      self.df_canvas_corners
                                                      .values)[0]

        # Translate transform shape coordinate space to drawing area coordinate
        # space.
        transform = self.frame_to_canvas_map
        if self.canvas is not None:
            transform = (self.canvas.shapes_to_canvas_transform.values
                         .dot(transform))
        self.video_sink.transform = transform
        self.set_surface('registration', self.render_registration())

    def create_ui(self):
        '''
        .. versionchanged:: 0.9
            Update device registration in real-time while dragging video
            control point to new position.

        .. versionchanged:: 0.12
            Add ``dynamic_electrode_state_shapes`` layer to show dynamic
            electrode actuations.
        '''
        super(DmfDeviceCanvas, self).create_ui()
        self.video_sink = VideoSink(*[self.socket_info[k]
                                      for k in ['transport', 'host', 'port']])
        # Initialize video sink socket.
        self.video_sink.reset()
        # Required to have key-press and key-release events trigger.
        self.widget.set_flags(gtk.CAN_FOCUS)
        self.widget.add_events(gtk.gdk.KEY_PRESS_MASK |
                               gtk.gdk.KEY_RELEASE_MASK)
        # Create initial (empty) cairo surfaces.
        surface_names = ('background', 'shapes', 'connections', 'routes',
                         'channel_labels', 'static_electrode_state_shapes',
                         'dynamic_electrode_state_shapes', 'registration')
        self.df_surfaces = pd.DataFrame([[self.get_surface(), 1.]
                                         for i in xrange(len(surface_names))],
                                        columns=['surface', 'alpha'],
                                        index=pd.Index(surface_names,
                                                       name='name'))

        def _update_registration(event):
            try:
                start_event = self.start_event.copy()
                self.start_event = event.copy()
                self.emit('point-pair-selected', {'start_event': start_event,
                                                  'end_event': event})
            except AttributeError:
                # Mouse button was released, causing `self.start_event` to be
                # `None` before event was handled here.
                pass

        # Debounce calls to `_update_registration` function to prevent too many
        # calls being triggered from mouse movement events.
        update_registration = debounce.Debounce(_update_registration, wait=10)

        def _on_mouse_move(area, event):
            # XXX Need to make a copy of the event here since the original
            # event will be deallocated before the debounced
            # `update_registration` function is called.
            event = event.copy()

            if self.mode == 'register_video' and self.start_event is not None:
                update_registration(event.copy())

        # Connect video registration update event to mouse movement event.
        self.widget.connect("motion_notify_event", _on_mouse_move)

    def reset_canvas(self, width, height):
        super(DmfDeviceCanvas, self).reset_canvas(width, height)
        if self.device is None or self.canvas.df_canvas_shapes.shape[0] == 0:
            return

        self.canvas.df_canvas_shapes =\
            compute_shape_centers(self.canvas.df_canvas_shapes
                                  [[self.shape_i_column, 'vertex_i', 'x',
                                    'y']], self.shape_i_column)
        self.canvas.df_shape_centers = (self.canvas.df_canvas_shapes
                                        [[self.shape_i_column, 'x_center',
                                          'y_center']].drop_duplicates()
                                        .set_index(self.shape_i_column))
        df_shape_connections = self.device.df_shape_connections
        self.canvas.df_connection_centers =\
            (df_shape_connections.join(self.canvas.df_shape_centers
                                       .loc[df_shape_connections.source]
                                       .reset_index(drop=True))
             .join(self.canvas.df_shape_centers.loc[df_shape_connections
                                                    .target]
                   .reset_index(drop=True), lsuffix='_source',
                   rsuffix='_target'))

    def reset_states(self):
        self.electrode_states = pd.Series(name='electrode_states')
        self.electrode_states.index.name = 'electrode_id'

    def reset_routes(self):
        self.df_routes = pd.DataFrame(None, columns=['route_i', 'electrode_i',
                                                     'transition_i'])

    def set_device(self, dmf_device):
        self.device = dmf_device
        # Index channels by electrode ID for fast look up.
        self.electrode_channels = (self.device.df_electrode_channels
                                   .set_index('electrode_id'))
        self.df_shapes = self.device.df_shapes
        self.reset_routes()
        self.reset_states()
        x, y, width, height = self.widget.get_allocation()
        if width > 0 and height > 0:
            self.canvas = None
            self._dirty_size = width, height
        self.emit('device-set', dmf_device)

    def get_labels(self):
        if self.device is None:
            return pd.Series(None, index=pd.Index([], name='channel'))
        return (self.electrode_channels.astype(str)
                .groupby(level='electrode_id', axis=0)
                .agg(lambda v: ', '.join(v))['channel'])

    ###########################################################################
    # Properties
    @property
    def connection_count(self):
        return self.device.df_shape_connections.shape[0] if self.device else 0

    @property
    def shape_count(self):
        return self.df_shapes[self.shape_i_column].unique().shape[0]

    @property
    def enabled(self):
        return self._enabled

    @property
    def mode(self):
        return self._mode

    @mode.setter
    def mode(self, value):
        if value in ('register_video', 'control'):
            self._mode = value
    ###########################################################################
    # ## Mutators ##
    def insert_surface(self, position, name, surface, alpha=1.):
        '''
        Insert Cairo surface as new layer.


        Args
        ----

            position (int) : Index position to insert layer at.
            name (str) : Name of layer.
            surface (cairo.Context) : Surface to render.
            alpha (float) : Alpha/transparency level in the range `[0, 1]`.
        '''
        if name in self.df_surfaces.index:
            raise NameError('Surface already exists with `name="{}"`.'
                            .format(name))
        self.df_surfaces.loc[name] = surface, alpha

        # Reorder layers such that the new surface is placed at the specified
        # layer position (relative to the background surface).
        surfaces_order = self.df_surfaces.index.values.tolist()
        surfaces_order.remove(name)
        base_index = surfaces_order.index('background') + 1
        if position < 0:
            position = len(surfaces_order) + position
        surfaces_order.insert(base_index + position, name)
        self.reorder_surfaces(surfaces_order)

    def append_surface(self, name, surface, alpha=1.):
        '''
        Append Cairo surface as new layer on top of existing layers.

        Args
        ----

            name (str) : Name of layer.
            surface (cairo.ImageSurface) : Surface to render.
            alpha (float) : Alpha/transparency level in the range `[0, 1]`.
        '''
        self.insert_surface(position=self.df_surfaces.index.shape[0],
                            name=name, surface=surface, alpha=alpha)

    def remove_surface(self, name):
        '''
        Remove layer from rendering stack and flatten remaining layers.

        Args
        ----

            name (str) : Name of layer.
        '''
        self.df_surfaces.drop(name, axis=0, inplace=True)

        # Order of layers may have changed after removing a layer. Trigger
        # refresh of surfaces.
        self.reorder_surfaces(self.df_surfaces.index)

    def clone_surface(self, source_name, target_name, target_position=-1,
                      alpha=1.):
        '''
        Clone surface from existing layer to a new name, inserting new surface
        at specified position.

        By default, new surface is appended as the top surface layer.

        Args
        ----

            source_name (str) : Name of layer to clone.
            target_name (str) : Name of new layer.
        '''
        source_surface = self.df_surfaces.surface.ix[source_name]
        source_width = source_surface.get_width()
        source_height = source_surface.get_height()
        source_format = source_surface.get_format()

        target_surface = cairo.ImageSurface(source_format, source_width,
                                            source_height)
        target_cairo_context = cairo.Context(target_surface)
        target_cairo_context.set_source_surface(source_surface, 0, 0)
        target_cairo_context.paint()
        self.insert_surface(target_position, target_name, target_surface,
                            alpha)

    def enable(self):
        if self.callback_id is None:
            self._enabled = True
            self.set_surface('shapes', self.render_shapes())

            # Add layer to which video frames will be rendered.
            if 'video' in self.df_surfaces.index:
                self.set_surface('video', self.render_shapes())
            else:
                self.df_surfaces.loc['video'] = self.render_shapes(), 1.

            # Reorder layers such that the video layer is directly on top of
            # the background layer.
            surfaces_order = self.df_surfaces.index.values.tolist()
            surfaces_order.remove('video')
            surfaces_order.insert(surfaces_order.index('background') + 1,
                                  'video')
            self.reorder_surfaces(surfaces_order)

            self.render()
            self.callback_id = self.video_sink.connect('frame-update',
                                                       self.on_frame_update)
            self.emit('video-enabled')

    def disable(self):
        if self.callback_id is not None:
            self._enabled = False
            self.set_surface('shapes', self.render_shapes())
            self.video_sink.disconnect(self.callback_id)
            self.callback_id = None
            if 'video' in self.df_surfaces.index:
                self.df_surfaces.drop('video', axis=0, inplace=True)
                self.reorder_surfaces(self.df_surfaces.index)
            self.emit('video-disabled')
        self.on_frame_update(None, None)

    ###########################################################################
    # ## Drawing area event handling ##
    def check_dirty(self):
        if self._dirty_size is not None:
            width, height = self._dirty_size
            self.set_shape(width, height)
            transform_update_required = True
        else:
            transform_update_required = False
        result = super(DmfDeviceCanvas, self).check_dirty()
        if transform_update_required:
            gtk.idle_add(self.update_transforms)
        return result

    def set_shape(self, width, height):
        logger.debug('[set_shape]: Set drawing area shape to %sx%s', width,
                     height)
        self.shape = width, height
        # Set new target size for scaled frames from video sink.
        self.video_sink.shape = width, height
        self.update_transforms()
        if not self._enabled:
            gtk.idle_add(self.on_frame_update, None, None)

    ###########################################################################
    # ## Drawing methods ##
    def get_surfaces(self):
        surface1 = cairo.ImageSurface(cairo.FORMAT_ARGB32, 320, 240)
        surface1_context = cairo.Context(surface1)
        surface1_context.set_source_rgba(0, 0, 1, .5)
        surface1_context.rectangle(0, 0, surface1.get_width(), surface1.get_height())
        surface1_context.fill()

        surface2 = cairo.ImageSurface(cairo.FORMAT_ARGB32, 800, 600)
        surface2_context = cairo.Context(surface2)
        surface2_context.save()
        surface2_context.translate(100, 200)
        surface2_context.set_source_rgba(0, 1, .5, .5)
        surface2_context.rectangle(0, 0, surface1.get_width(), surface1.get_height())
        surface2_context.fill()
        surface2_context.restore()

        return [surface1, surface2]

    def draw_surface(self, surface, operator=cairo.OPERATOR_OVER):
        x, y, width, height = self.widget.get_allocation()
        if width <= 0 and height <= 0 or self.widget.window is None:
            return
        cairo_context = self.widget.window.cairo_create()
        cairo_context.set_operator(operator)
        cairo_context.set_source_surface(surface)
        cairo_context.rectangle(0, 0, width, height)
        cairo_context.fill()

    ###########################################################################
    # Render methods
    def render_dynamic_electrode_state_shapes(self):
        '''
        Render **dynamic** states reported by the electrode controller.

        **Dynamic** electrode states are only applied while a protocol is
        running -- _not_ while in real-time programming mode.

        See also :meth:`render_electrode_shapes()`.


        .. versionadded:: 0.12
        '''
        df_shapes = self.canvas.df_canvas_shapes.copy()
        # Only include shapes for electrodes reported as actuated.
        on_electrodes = self._dynamic_electrodes[self._dynamic_electrodes > 0]
        df_shapes = (df_shapes.set_index('id').loc[on_electrodes.index]
                     .reset_index())

        return self.render_electrode_shapes(df_shapes=df_shapes,
                                            shape_scale=0.75,
                                            # Lignt blue
                                            fill=(136 / 255.,
                                                  189 / 255.,
                                                  230 / 255.))

    def render_static_electrode_state_shapes(self):
        '''
        Render **static** states reported by the electrode controller.

        **Static** electrode states are applied while a protocol is **running**
        _or_ while **real-time** control is activated.

        See also :meth:`render_electrode_shapes()`.


        .. versionadded:: 0.12
        '''
        df_shapes = self.canvas.df_canvas_shapes.copy()
        if self.electrode_states.shape[0]:
            df_shapes['state'] = self.electrode_states.ix[df_shapes.id].values
        else:
            df_shapes['state'] = 0
        df_shapes = df_shapes.loc[df_shapes.state > 0].dropna(subset=['state'])

        return self.render_electrode_shapes(df_shapes=df_shapes)

    def render_electrode_shapes(self, df_shapes=None, shape_scale=0.8,
                                fill=(1, 1, 1)):
        '''
        Render electrode state shapes.

        By default, draw each electrode shape filled white.

        See also :meth:`render_shapes()`.

        Parameters
        ----------
        df_shapes = : pandas.DataFrame


        .. versionadded:: 0.12
        '''
        surface = self.get_surface()
        if df_shapes is None:
            if hasattr(self.canvas, 'df_canvas_shapes'):
                df_shapes = self.canvas.df_canvas_shapes
            else:
                return surface
        if 'x_center' not in df_shapes or 'y_center' not in df_shapes:
            # No center points have been computed for shapes.
            return surface

        cairo_context = cairo.Context(surface)

        df_shapes = df_shapes.copy()
        # Scale shapes to leave shape edges uncovered.
        df_shapes[['x', 'y']] = (df_shapes[['x_center', 'y_center']] +
                                 df_shapes[['x_center_offset',
                                            'y_center_offset']].values *
                                 shape_scale)

        for path_id, df_path_i in (df_shapes.groupby(self.canvas
                                                     .shape_i_columns)[['x',
                                                                        'y']]):
            # Use attribute lookup for `x` and `y`, since it is considerably
            # faster than `get`-based lookup using columns name strings.
            vertices_x = df_path_i.x.values
            vertices_y = df_path_i.y.values
            cairo_context.move_to(vertices_x[0], vertices_y[0])
            for x, y in itertools.izip(vertices_x[1:], vertices_y[1:]):
                cairo_context.line_to(x, y)
            cairo_context.close_path()

            # Draw filled shape to indicate actuated electrode state.
            cairo_context.set_source_rgba(*fill)
            cairo_context.fill()
        return surface

    def render_background(self):
        surface = self.get_surface()
        context = cairo.Context(surface)
        context.set_source_rgb(0, 0, 0)
        context.paint()
        return surface

    def render_connections(self, indexes=None, hex_color='#fff', alpha=1.,
                           **kwargs):
        surface = self.get_surface()
        if not hasattr(self.canvas, 'df_connection_centers'):
            return surface
        cairo_context = cairo.Context(surface)
        coords_columns = ['source', 'target',
                          'x_center_source', 'y_center_source',
                          'x_center_target', 'y_center_target']
        df_connection_coords = (self.canvas.df_connection_centers
                                [coords_columns])
        if indexes is not None:
            df_connection_coords = df_connection_coords.loc[indexes].copy()

        rgba = hex_color_to_rgba(hex_color, normalize_to=1.)
        if rgba[-1] is None:
            rgba = rgba[:-1] + (alpha, )
        cairo_context.set_line_width(2.5)
        for i, (target, source, x1, y1, x2, y2) in (df_connection_coords
                                                    .iterrows()):
            cairo_context.move_to(x1, y1)
            cairo_context.set_source_rgba(*rgba)
            for k, v in kwargs.iteritems():
                getattr(cairo_context, 'set_' + k)(v)
            cairo_context.line_to(x2, y2)
            cairo_context.stroke()
        return surface

    def render_shapes(self, df_shapes=None, clip=False):
        '''
        Render static electrode shapes (independent of actuation state).

        If video is enabled, draw white outline for each electrode (no fill).

        If video is disabled, draw white outline for each electrode and fill
        blue.

        See also :meth:`render_electrode_state_shapes()`.
        '''
        surface = self.get_surface()
        if df_shapes is None:
            if hasattr(self.canvas, 'df_canvas_shapes'):
                df_shapes = self.canvas.df_canvas_shapes
            else:
                return surface

        cairo_context = cairo.Context(surface)

        for path_id, df_path_i in (df_shapes
                                   .groupby(self.canvas
                                            .shape_i_columns)[['x', 'y']]):
            # Use attribute lookup for `x` and `y`, since it is considerably
            # faster than `get`-based lookup using columns name strings.
            vertices_x = df_path_i.x.values
            vertices_y = df_path_i.y.values
            cairo_context.move_to(vertices_x[0], vertices_y[0])
            for x, y in itertools.izip(vertices_x[1:], vertices_y[1:]):
                cairo_context.line_to(x, y)
            cairo_context.close_path()

            if self.enabled:
                # Video is enabled.

                # Draw white border around electrode.
                line_width = 1
                if path_id not in self.electrode_channels.index:
                    #         on  off on  off
                    dashes = [10, 10]
                    color = (1, 0, 1)
                    line_width *= 2
                else:
                    dashes = []
                    color = (1, 1, 1)
                cairo_context.set_dash(dashes)
                cairo_context.set_line_width(line_width)
                cairo_context.set_source_rgb(*color)
                cairo_context.stroke()
            else:
                # Video is enabled.  Fill electrode blue.
                color = ((0, 0, 1) if path_id in self.electrode_channels.index
                         else (1, 0, 1))
                cairo_context.set_source_rgb(*color)
                cairo_context.fill_preserve()
                # Draw white border around electrode.
                cairo_context.set_line_width(1)
                cairo_context.set_source_rgba(1, 1, 1)
                cairo_context.stroke()
        return surface

    def render_routes(self):
        surface = self.get_surface()

        if (not hasattr(self.device, 'df_shape_connections') or
                not hasattr(self.canvas, 'df_shape_centers')):
            return surface

        cairo_context = cairo.Context(surface)
        connections = self.device.df_shape_connections
        for route_i, df_route in self.df_routes.groupby('route_i'):
            source_id = df_route.electrode_i.iloc[0]
            source_connections = connections.loc[(connections.source ==
                                                  source_id) |
                                                 (connections.target ==
                                                  source_id)]

            # Colors from ["Show me the numbers"][1].
            #
            # [1]: http://blog.axc.net/its-the-colors-you-have/
            # LiteOrange = rgb(251,178,88);
            # MedOrange = rgb(250,164,58);
            # LiteGreen = rgb(144,205,151);
            # MedGreen = rgb(96,189,104);
            if source_connections.shape[0] == 1:
                # Electrode only has one adjacent electrode, assume reservoir.
                color_rgb_255 = np.array([250, 164, 58, 255])
            else:
                color_rgb_255 = np.array([96, 189, 104, 255])
            color = (color_rgb_255 / 255.).tolist()
            self.draw_route(df_route, cairo_context, color=color,
                            line_width=.25)
        return surface

    def render_channel_labels(self, color_rgba=None):
        return self.render_labels(self.get_labels(), color_rgba=color_rgba)

    def render_registration(self):
        '''
        Render pinned points on video frame as red rectangle.
        '''
        surface = self.get_surface()
        if self.canvas is None or self.df_canvas_corners.shape[0] == 0:
            return surface

        corners = self.df_canvas_corners.copy()
        corners['w'] = 1

        transform = self.canvas.shapes_to_canvas_transform
        canvas_corners = corners.values.dot(transform.T.values).T

        points_x = canvas_corners[0]
        points_y = canvas_corners[1]

        cairo_context = cairo.Context(surface)
        cairo_context.move_to(points_x[0], points_y[0])
        for x, y in zip(points_x[1:], points_y[1:]):
            cairo_context.line_to(x, y)
        cairo_context.line_to(points_x[0], points_y[0])
        cairo_context.set_source_rgb(1, 0, 0)
        cairo_context.stroke()
        return surface

    def set_surface(self, name, surface):
        self.df_surfaces.loc[name, 'surface'] = surface
        self.emit('surface-rendered', name, surface)

    def set_surface_alpha(self, name, alpha):
        if 'alpha' not in self.df_surfaces:
            self.df_surfaces['alpha'] = 1.
        if name in self.df_surfaces.index:
            self.df_surfaces.loc[name, 'alpha'] = alpha

    def reorder_surfaces(self, surface_names):
        assert(len(surface_names) == self.df_surfaces.shape[0])
        self.df_surfaces = self.df_surfaces.ix[surface_names]
        self.emit('surfaces-reset', self.df_surfaces)
        self.cairo_surface = flatten_surfaces(self.df_surfaces)

    def render(self):
        '''
        .. versionchanged:: 0.12
            Add ``dynamic_electrode_state_shapes`` layer to show dynamic
            electrode actuations.
        '''
        # Render each layer and update data frame with new content for each
        # surface.
        surface_names = ('background', 'shapes', 'connections', 'routes',
                         'channel_labels', 'static_electrode_state_shapes',
                         'dynamic_electrode_state_shapes', 'registration')
        for k in surface_names:
            self.set_surface(k, getattr(self, 'render_' + k)())
        self.emit('surfaces-reset', self.df_surfaces)
        self.cairo_surface = flatten_surfaces(self.df_surfaces)

    ###########################################################################
    # Drawing helper methods
    def draw_route(self, df_route, cr, color=None, line_width=None):
        '''
        Draw a line between electrodes listed in a route.

        Arguments
        ---------

         - `df_route`:
             * A `pandas.DataFrame` containing a column named `electrode_i`.
             * For each row, `electrode_i` corresponds to the integer index of
               the corresponding electrode.
         - `cr`: Cairo context.
         - `color`: Either a RGB or RGBA tuple, with each color channel in the
           range [0, 1].  If `color` is `None`, the electrode color is set to
           white.
        '''
        df_route_centers = (self.canvas.df_shape_centers
                            .ix[df_route.electrode_i][['x_center',
                                                       'y_center']])
        df_endpoint_marker = (.6 * self.get_endpoint_marker(df_route_centers)
                              + df_route_centers.iloc[-1].values)

        # Save cairo context to restore after drawing route.
        cr.save()
        if color is None:
            # Colors from ["Show me the numbers"][1].
            #
            # [1]: http://blog.axc.net/its-the-colors-you-have/
            # LiteOrange = rgb(251,178,88);
            # MedOrange = rgb(250,164,58);
            # LiteGreen = rgb(144,205,151);
            # MedGreen = rgb(96,189,104);
            color_rgb_255 = np.array([96,189,104, .8 * 255])
            color = (color_rgb_255 / 255.).tolist()
        if len(color) < 4:
            color += [1.] * (4 - len(color))
        cr.set_source_rgba(*color)
        cr.move_to(*df_route_centers.iloc[0])
        for electrode_i, center_i in df_route_centers.iloc[1:].iterrows():
            cr.line_to(*center_i)
        if line_width is None:
            line_width = np.sqrt((df_endpoint_marker.max().values -
                                  df_endpoint_marker.min().values).prod()) * .1
        cr.set_line_width(4)
        cr.stroke()

        cr.move_to(*df_endpoint_marker.iloc[0])
        for electrode_i, center_i in df_endpoint_marker.iloc[1:].iterrows():
            cr.line_to(*center_i)
        cr.close_path()
        cr.set_source_rgba(*color)
        cr.fill()
        # Restore cairo context after drawing route.
        cr.restore()

    def get_endpoint_marker(self, df_route_centers):
        df_shapes = self.canvas.df_canvas_shapes
        df_endpoint_electrode = df_shapes.loc[df_shapes.id ==
                                              df_route_centers.index[-1]]
        df_endpoint_bbox = (df_endpoint_electrode[['x_center_offset',
                                                   'y_center_offset']]
                            .describe().loc[['min', 'max']])
        return pd.DataFrame([[df_endpoint_bbox.x_center_offset['min'],
                              df_endpoint_bbox.y_center_offset['min']],
                             [df_endpoint_bbox.x_center_offset['min'],
                              df_endpoint_bbox.y_center_offset['max']],
                             [df_endpoint_bbox.x_center_offset['max'],
                              df_endpoint_bbox.y_center_offset['max']],
                             [df_endpoint_bbox.x_center_offset['max'],
                              df_endpoint_bbox.y_center_offset['min']]],
                            columns=['x_center_offset', 'y_center_offset'])

    ###########################################################################
    # ## Mouse event handling ##
    def on_widget__button_press_event(self, widget, event):
        '''
        Called when any mouse button is pressed.


        .. versionchanged:: 0.11
            Do not trigger `route-electrode-added` event if `ALT` key is
            pressed.
        '''
        if self.mode == 'register_video' and event.button == 1:
            self.start_event = event.copy()
            return
        elif self.mode == 'control':
            shape = self.canvas.find_shape(event.x, event.y)

            if shape is None: return
            state = event.get_state()
            if event.button == 1:
                # Start a new route.
                self._route = Route(self.device)
                self._route.append(shape)
                self.last_pressed = shape
                if not (state & gtk.gdk.MOD1_MASK):
                    # `<Alt>` key is not held down.
                    self.emit('route-electrode-added', shape)

    def on_widget__button_release_event(self, widget, event):
        '''
        Called when any mouse button is released.


        .. versionchanged:: 0.11.3
            Always reset pending route, regardless of whether a route was
            completed.  This includes a) removing temporary routes from routes
            table, and b) resetting the state of the current route electrode
            queue.  This fixes
            https://github.com/sci-bots/microdrop/issues/256.
        '''
        event = event.copy()
        if self.mode == 'register_video' and (event.button == 1 and
                                              self.start_event is not None):
            self.emit('point-pair-selected', {'start_event': self.start_event,
                                              'end_event': event.copy()})
            self.start_event = None
            return
        elif self.mode == 'control':
            # XXX Negative `route_i` corresponds to temporary route being
            # drawn.  Since release of mouse button terminates route drawing,
            # clear any rows corresponding to negative `route_i` values from
            # the routes table.
            self.df_routes = self.df_routes.loc[self.df_routes.route_i >=
                                                0].copy()
            shape = self.canvas.find_shape(event.x, event.y)

            if shape is not None:
                electrode_data = {'electrode_id': shape, 'event': event.copy()}
                if event.button == 1:
                    if gtk.gdk.BUTTON1_MASK == event.get_state():
                        if self._route.append(shape):
                            self.emit('route-electrode-added', shape)
                        if len(self._route.electrode_ids) == 1:
                            # Single electrode, so select electrode.
                            self.emit('electrode-selected', electrode_data)
                        else:
                            # Multiple electrodes, so select route.
                            route = self._route
                            self.emit('route-selected', route)
                    elif (event.get_state() == (gtk.gdk.MOD1_MASK |
                                                gtk.gdk.BUTTON1_MASK) and
                        self.last_pressed != shape):
                        # `<Alt>` key was held down.
                        self.emit('electrode-pair-selected',
                                {'source_id': self.last_pressed,
                                 'target_id': shape, 'event': event.copy()})
                    self.last_pressed = None
                elif event.button == 3:
                    # Create right-click pop-up menu.
                    menu = self.create_context_menu(event, shape)

                    # Display menu popup
                    menu.popup(None, None, None, event.button, event.time)
            # Clear route.
            self._route = None

    def create_context_menu(self, event, shape):
        '''
        Parameters
        ----------
        event : gtk.gdk.Event
            GTK mouse click event.
        shape : str
            Electrode shape identifier (e.g., `"electrode028"`).

        Returns
        -------
        gtk.Menu
            Context menu.


        .. versionchanged:: 0.13
            - Deprecate hard-coded commands (e.g., clear electrodes, clear
              routes).
            - Add anonymous global commands section at head of menu (i.e.,
              commands not specific to an electrode or route).
            - Add "Electrode" and "Route(s)" sub-menus.
        '''
        routes = self.df_routes.loc[self.df_routes.electrode_i == shape,
                                    'route_i'].astype(int).unique().tolist()

        def _connect_callback(menu_item, command_signal, group, command, data):
            callback_called = threading.Event()

            def _callback(signal, widget, *args):
                if callback_called.is_set():
                    return
                callback_called.set()

                _L().debug('`%s`: %s %s %s', signal, group, command, data)
                gtk.idle_add(self.emit, command_signal, group, command, data)
            menu_item.connect('activate', ft.partial(_callback, 'activate'))
            menu_item.connect('button-press-event',
                              ft.partial(_callback, 'button-press-event'))

            if group is not None:
                menu_item.set_tooltip_text(group)

        menu = gtk.Menu()

        # Add menu items/groups for registered global commands.
        if self.global_commands:
            data = {'event': event.copy()}
            command_signal = 'global-command'

            for group, commands in self.global_commands.iteritems():
                for command, title in commands.iteritems():
                    menu_item_j = gtk.MenuItem(title)
                    menu.append(menu_item_j)

                    _connect_callback(menu_item_j, command_signal, group,
                                      command, data)

        # Add menu items/groups for registered electrode commands.
        if self.electrode_commands:
            separator = gtk.SeparatorMenuItem()
            menu.append(separator)

            # Add electrode sub-menu.
            menu_e = gtk.Menu()
            menu_head_e = gtk.MenuItem('_Electrode')
            menu_head_e.set_submenu(menu_e)
            menu_head_e.set_use_underline(True)
            menu.append(menu_head_e)

            command_signal = 'electrode-command'
            data = {'electrode_id': shape, 'event': event.copy()}

            for group, commands in self.electrode_commands.iteritems():
                for command, title in commands.iteritems():
                    menu_item_j = gtk.MenuItem(title)
                    menu_e.append(menu_item_j)
                    _connect_callback(menu_item_j, command_signal, group,
                                      command, data)

        # Add menu items/groups for registered route commands.
        if routes and self.route_commands:
            # TODO: Refactor electrode/route command menu code to reduce code
            # duplication (i.e., DRY).
            separator = gtk.SeparatorMenuItem()
            menu.append(separator)

            # Add route sub-menu.
            menu_r = gtk.Menu()
            menu_head_r = gtk.MenuItem('_Route(s)')
            menu_head_r.set_submenu(menu_r)
            menu_head_r.set_use_underline(True)
            menu.append(menu_head_r)

            command_signal = 'route-command'
            data = {'route_ids': routes, 'event': event.copy()}
            for group, commands in self.route_commands.iteritems():
                for command, title in commands.iteritems():
                    menu_item_j = gtk.MenuItem(title)
                    menu_r.append(menu_item_j)

                    _connect_callback(menu_item_j, command_signal, group,
                                      command, data)

        menu.show_all()
        return menu

    def on_widget__motion_notify_event(self, widget, event):
        '''
        Called when mouse pointer is moved within drawing area.


        .. versionchanged:: 0.11
            Do not trigger `route-electrode-added` event if `ALT` key is
            pressed.
        '''
        if self.canvas is None:
            # Canvas has not been initialized.  Nothing to do.
            return
        elif event.is_hint:
            pointer = event.window.get_pointer()
            x, y, mod_type = pointer
        else:
            x = event.x
            y = event.y
        shape = self.canvas.find_shape(x, y)

        # Grab focus to [enable notification on key press/release events][1].
        #
        # [1]: http://mailman.daa.com.au/cgi-bin/pipermail/pygtk/2003-August/005770.html
        self.widget.grab_focus()

        if shape != self.last_hovered:
            if self.last_hovered is not None:
                # Leaving shape
                self.emit('electrode-mouseout', {'electrode_id':
                                                 self.last_hovered,
                                                 'event': event.copy()})
                self.last_hovered = None
            elif shape is not None:
                # Entering shape
                self.last_hovered = shape

                if self._route is not None:
                    if self._route.append(shape) and not (event.get_state() &
                                                          gtk.gdk.MOD1_MASK):
                        # `<Alt>` key was not held down.
                        self.emit('route-electrode-added', shape)

                self.emit('electrode-mouseover', {'electrode_id':
                                                  self.last_hovered,
                                                  'event': event.copy()})
    def on_widget__key_press_event(self, widget, event):
        '''
        Called when key is pressed when widget has focus.
        '''
        self.emit('key-press', {'event': event.copy()})

    def on_widget__key_release_event(self, widget, event):
        '''
        Called when key is released when widget has focus.
        '''
        self.emit('key-release', {'event': event.copy()})

    ###########################################################################
    # ## Slave signal handling ##
    def on_video_sink__frame_shape_changed(self, slave, old_shape, new_shape):
        # Video frame is a new shape.
        if old_shape is not None:
            # Switched video resolution, so scale existing corners to maintain
            # video registration.
            old_shape = pd.Series(old_shape, dtype=float, index=['width',
                                                                 'height'])
            new_shape = pd.Series(new_shape, dtype=float, index=['width',
                                                                 'height'])
            old_aspect_ratio = old_shape.width / old_shape.height
            new_aspect_ratio = new_shape.width / new_shape.height
            if old_aspect_ratio != new_aspect_ratio:
                # The aspect ratio has changed.  The registration will have the
                # proper rotational orientation, but the scale will be off and
                # will require manual adjustment.
                logger.warning('Aspect ratio does not match previous frame.  '
                               'Manual adjustment of registration is required.')

            corners_scale = new_shape / old_shape
            df_frame_corners = self.df_frame_corners.copy()
            df_frame_corners.y = old_shape.height - df_frame_corners.y
            df_frame_corners *= corners_scale.values
            df_frame_corners.y = new_shape.height - df_frame_corners.y
            self.df_frame_corners = df_frame_corners
        else:
            # No existing frame shape, so nothing to scale from.
            self.reset_frame_corners()
        self.update_transforms()

    def on_frame_update(self, slave, np_frame):
        if self.widget.window is None:
            return
        if np_frame is None or not self._enabled:
            if 'video' in self.df_surfaces.index:
                self.df_surfaces.drop('video', axis=0, inplace=True)
                self.reorder_surfaces(self.df_surfaces.index)
        else:
            cr_warped, np_warped_view = np_to_cairo(np_frame)
            self.set_surface('video', cr_warped)
        self.cairo_surface = flatten_surfaces(self.df_surfaces)
        # Execute a few gtk main loop iterations to improve responsiveness when
        # using high video frame rates.
        #
        # N.B., Without doing this, for example, some mouse over events may be
        # missed, leading to problems drawing routes, etc.
        for i in xrange(5):
            if not gtk.events_pending():
                break
            gtk.main_iteration_do()

        self.draw()
    ###########################################################################
    # ## Electrode operation registration ##
    def register_global_command(self, command, title=None, group=None):
        '''
        .. versionadded:: 0.13


        Register global command (i.e., not specific to electrode or route).

        Add global command to context menu.
        '''
        commands = self.global_commands.setdefault(group, OrderedDict())
        if title is None:
            title = (command[:1].upper() + command[1:]).replace('_', ' ')
        commands[command] = title

    def register_electrode_command(self, command, title=None, group=None):
        '''
        Register electrode command.

        Add electrode plugin command to context menu.
        '''
        commands = self.electrode_commands.setdefault(group, OrderedDict())
        if title is None:
            title = (command[:1].upper() + command[1:]).replace('_', ' ')
        commands[command] = title

    ###########################################################################
    # ## Route operation registration ##
    def register_route_command(self, command, title=None, group=None):
        '''
        Register route command.

        Add route plugin command to context menu.
        '''
        commands = self.route_commands.setdefault(group, OrderedDict())
        if title is None:
            title = (command[:1].upper() + command[1:]).replace('_', ' ')
        commands[command] = title
