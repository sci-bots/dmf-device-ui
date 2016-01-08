# -*- coding: utf-8 -*-
import itertools

from pygtkhelpers.ui.views.shapes_canvas_view import GtkShapesCanvasView
from pygtkhelpers.utils import gsignal
from svg_model.color import hex_color_to_rgba
import cairo
import gtk
import numpy as np
import pandas as pd


class Route(object):
    def __init__(self, device):
        self.device = device
        self.electrode_ids = []

    def __str__(self):
        return '<Route electrode_ids=%s>' % self.electrode_ids

    def append(self, electrode_id):
        do_append = False

        if not self.electrode_ids:
            do_append = True
        else:
            source = self.electrode_ids[-1]
            target = electrode_id
            source_id, target_id = self.device.shape_indexes[[source, target]]
            if self.device.adjacency_matrix[source_id, target_id]:
                # Electrodes are connected, so append target to current route.
                do_append = True

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
    gsignal('electrode-selected', object)
    gsignal('electrode-pair-selected', object)
    gsignal('electrode-mouseover', object)
    gsignal('electrode-mouseout', object)
    gsignal('key-press', object)
    gsignal('key-release', object)
    gsignal('route-selected', object)
    gsignal('route-electrode-added', object)
    gsignal('clear-routes', object)
    gsignal('clear-electrode-states')

    def __init__(self, connections_alpha=1., connections_color=1., **kwargs):
        # Read SVG polygons into dataframe, one row per polygon vertex.
        df_shapes = pd.DataFrame(None, columns=['id', 'vertex_i', 'x', 'y'])
        self.device = None
        self.shape_i_column = 'id'

        # Save alpha for drawing connections.
        self.connections_alpha = connections_alpha

        # Save color for drawing connections.
        self.connections_color = connections_color

        self.reset_states()
        self.reset_routes()

        self.connections_attrs = {}
        self.last_pressed = None
        self.last_hovered = None
        self._route = None
        self.connections_enabled = (self.connections_alpha > 0)

        super(DmfDeviceCanvas, self).__init__(df_shapes, self.shape_i_column,
                                              **kwargs)

    def create_ui(self):
        super(DmfDeviceCanvas, self).create_ui()
        self.widget.set_flags(gtk.CAN_FOCUS)
        self.widget.add_events(gtk.gdk.KEY_PRESS_MASK |
                               gtk.gdk.KEY_RELEASE_MASK)

    def reset_canvas(self, width, height):
        from svg_model import compute_shape_centers

        super(DmfDeviceCanvas, self).reset_canvas(width, height)
        if self.device is None:
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
        self.df_shapes = self.device.df_shapes
        self.reset_routes()
        self.reset_states()
        x, y, width, height = self.widget.get_allocation()
        if width > 0 and height > 0:
            gtk.idle_add(self.on_canvas_reset_tick, width, height)
        self.emit('device-set', dmf_device)

    ###########################################################################
    # Properties
    @property
    def connection_count(self):
        return self.device.df_shape_connections.shape[0] if self.device else 0

    @property
    def shape_count(self):
        return self.df_shapes[self.shape_i_column].unique().shape[0]

    ###########################################################################
    # Render methods
    def render_background(self, cairo_context=None):
        if cairo_context is None:
            cairo_context = self.widget.window.cairo_create()

        x, y, width, height = self.widget.get_allocation()
        cairo_context.rectangle(0, 0, width, height)
        cairo_context.set_source_rgb(0, 0, 0)
        cairo_context.fill()

    def render_default_connections(self, cairo_context=None):
        self.render_connections(hex_color=self.connections_color,
                                alpha=self.connections_alpha,
                                cairo_context=cairo_context,
                                **self.connections_attrs)

    def render_connections(self, indexes=None, hex_color='#fff', alpha=1.,
                           cairo_context=None, **kwargs):
        if cairo_context is None:
            cairo_context = self.widget.window.cairo_create()

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
        for i, (target, source, x1, y1, x2, y2) in (df_connection_coords
                                                    .iterrows()):
            cairo_context.move_to(x1, y1)
            cairo_context.set_source_rgba(*rgba)
            for k, v in kwargs.iteritems():
                getattr(cairo_context, 'set_' + k)(v)
            cairo_context.line_to(x2, y2)
            cairo_context.stroke()

    def render_shapes(self, df_shapes=None, cairo_context=None, clip=False):
        if cairo_context is None:
            cairo_context = self.widget.window.cairo_create()

        if df_shapes is None:
            df_shapes = self.canvas.df_canvas_shapes

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
            state = self.electrode_states.get(path_id, 0)
            if state > 0:
                color = 1, 1, 1
            else:
                color = 0, 0, 1
            cairo_context.set_source_rgb(*color)
            cairo_context.fill()

    def render_routes(self, cairo_context=None):
        if cairo_context is None:
            cairo_context = self.widget.window.cairo_create()

        for route_i, df_route in self.df_routes.groupby('route_i'):
            self.draw_drop_route(df_route, cairo_context, line_width=.25)

    def render(self):
        self.reset_cairo_surface()
        cairo_context = cairo.Context(self.cairo_surface)
        self.render_background(cairo_context=cairo_context)
        self.render_shapes(cairo_context=cairo_context)
        if (hasattr(self.canvas, 'df_connection_centers') and
            self.connections_enabled and self.connections_alpha > 0):

            self.render_default_connections(cairo_context=cairo_context)
        self.render_routes(cairo_context=cairo_context)

    ###########################################################################
    # Drawing helper methods
    def draw_drop_route(self, df_route, cr, color=None, line_width=None):
        '''
        Draw a line between electrodes listed in a droplet route.

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
            color_rgb_255 = np.array([96,189,104])
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
        '''
        shape = self.canvas.find_shape(event.x, event.y)

        if shape is None: return
        if event.button == 1:
            self.last_pressed = shape

    def on_widget__button_release_event(self, widget, event):
        '''
        Called when any mouse button is released.
        '''
        shape = self.canvas.find_shape(event.x, event.y)

        if shape is None: return

        if event.button == 1:
            if self.last_pressed == shape:
                if (gtk.gdk.MOD1_MASK | gtk.gdk.BUTTON1_MASK) == event.get_state():
                    # `<Alt>` key is held down.
                    if self._route is None:
                        # Start a new route.
                        self._route = Route(self.device)
                        if self._route.append(shape):
                            self.emit('route-electrode-added', shape)
                else:
                    self.emit('electrode-selected', {'electrode_id': shape,
                                                    'event': event.copy()})
            elif gtk.gdk.BUTTON1_MASK == event.get_state():
                self.emit('electrode-pair-selected',
                          {'source_id': self.last_pressed, 'target_id': shape,
                           'event': event.copy()})
            self.last_pressed = None
        elif event.button == 3:
            # Right-click pop-up menu.
            def clear_electrode_states(widget):
                self.emit('clear-electrode-states')

            def clear_routes(widget):
                self.emit('clear-routes', shape)

            def clear_all_routes(widget):
                self.emit('clear-routes', None)

            menu = gtk.Menu()
            menu_clear_electrode_states = gtk.MenuItem('Clear electrode states')
            menu_clear_electrode_states.connect('activate',
                                                clear_electrode_states)
            menu_clear_routes = gtk.MenuItem('Clear electrode routes')
            menu_clear_routes.connect('activate', clear_routes)
            menu_clear_all_routes = gtk.MenuItem('Clear all electrode routes')
            menu_clear_all_routes.connect('activate', clear_all_routes)

            for item in (menu_clear_electrode_states, menu_clear_routes,
                         menu_clear_all_routes):
                menu.append(item)
                item.show()

            # Make menu popup
            menu.popup(None, None, None, event.button, event.time)

    def on_widget__motion_notify_event(self, widget, event):
        '''
        Called when mouse pointer is moved within drawing area.
        '''
        shape = self.canvas.find_shape(event.x, event.y)

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

                if event.get_state() == gtk.gdk.MOD1_MASK:
                    # `<Alt>` key was held down.
                    if self._route is not None:
                        if self._route.append(shape):
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
        if self._route is not None:
            if event.keyval in [gtk.gdk.keyval_from_name(k)
                                for k in ('Alt_%s' % i for i in 'LR')]:
                # <Alt> key was released.
                if not (event.get_state() & gtk.gdk.MOD1_MASK):
                    # <Alt> key is not pressed now.
                    route = self._route
                    self.emit('route-selected', route)
        # Clear route.
        self._route = None

