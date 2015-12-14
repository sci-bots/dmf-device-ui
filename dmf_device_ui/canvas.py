# -*- coding: utf-8 -*-
from svg_model import svg_polygons_to_df
from svg_model.color import hex_color_to_rgba
from svg_model.connections import extract_connections
from svg_model.shapes_canvas import ShapesCanvas
from pygtkhelpers.ui.views.shapes_canvas_view import GtkShapesCanvasView


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

    Signals are published via a *notifier* member, which *MUST* implement the
    following API:

     - `notify(<python object>)`

    The format of each signal is:

        {'signal': '<signal label>', 'data': {...}}
    '''
    def __init__(self, svg_filepath, notifier, connections_alpha=1.,
                 connections_color=1., **kwargs):
        # Read SVG polygons into dataframe, one row per polygon vertex.
        df_shapes = svg_polygons_to_df(svg_filepath)

        # Add SVG file path as attribute.
        self.svg_filepath = svg_filepath

        self.notifier = notifier

        # Save alpha for drawing connections.
        self.connections_alpha = connections_alpha

        # Save color for drawing connections.
        self.connections_color = connections_color

        self.connections_attrs = {}
        self.last_pressed = None
        self.last_hovered = None
        self.connections_enabled = (self.connections_alpha > 0)

        super(DmfDeviceCanvas, self).__init__(df_shapes, 'path_id', **kwargs)

    def create_ui(self, *args, **kwargs):
        super(DmfDeviceCanvas, self).create_ui(*args, **kwargs)
        # Compute centers.
        svg_canvas = ShapesCanvas(self.df_shapes, 'path_id')
        self.df_shape_connections = extract_connections(self.svg_filepath,
                                                        svg_canvas)

    def on_widget__expose_event(self, widget, event):
        from svg_model import compute_shape_centers

        if self.canvas is None:
            return

        self.canvas.df_canvas_shapes = compute_shape_centers(self.canvas
                                                            .df_canvas_shapes
                                                             [['path_id',
                                                               'vertex_i', 'x',
                                                               'y']],
                                                             'path_id')
        self.canvas.df_shape_centers = (self.canvas.df_canvas_shapes
                                        [['path_id', 'x_center', 'y_center']]
                                        .drop_duplicates()
                                        .set_index('path_id'))
        self.canvas.df_connection_centers =\
            (self.df_shape_connections.join(self.canvas.df_shape_centers
                                            .loc[self.df_shape_connections
                                                 .source]
                                            .reset_index(drop=True))
             .join(self.canvas.df_shape_centers.loc[self.df_shape_connections
                                                    .target]
                   .reset_index(drop=True), lsuffix='_source',
                   rsuffix='_target'))

        self.draw()

    def draw(self):
        self.draw_shapes()
        if self.connections_enabled and self.connections_alpha > 0:
            self.draw_default_connections()

    def draw_default_connections(self):
        self.draw_connections(hex_color=self.connections_color,
                              alpha=self.connections_alpha,
                              **self.connections_attrs)

    def draw_connections(self, indexes=None, hex_color='#fff', alpha=1.,
                         **kwargs):
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
                self.notifier.notify({'signal': 'electrode_selected',
                                      'data': {'electrode_id': shape}})
            else:
                self.notifier.notify({'signal': 'electrode_pair_selected',
                                      'data': {'source_id': self.last_pressed,
                                               'target_id': shape}})
            self.last_pressed = None

    def on_widget__motion_notify_event(self, widget, event):
        '''
        Called when mouse pointer is moved within drawing area.
        '''
        shape = self.canvas.find_shape(event.x, event.y)
        if shape != self.last_hovered:
            if self.last_hovered is not None:
                # Leaving shape
                self.notifier.notify({'signal': 'electrode_mouseout',
                                      'data': {'electrode_id':
                                               self.last_hovered}})
                self.last_hovered = None
            elif shape is not None:
                # Entering shape
                self.last_hovered = shape
                self.notifier.notify({'signal': 'electrode_mouseover',
                                      'data': {'electrode_id':
                                               self.last_hovered}})
