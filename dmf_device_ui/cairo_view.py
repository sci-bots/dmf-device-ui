import zmq
import gtk
from pygtkhelpers.ui.views.shapes_canvas_view import GtkShapesCanvasView
from svg_model import svg_polygons_to_df
from svg_model.color import hex_color_to_rgba
from svg_model.connections import extract_connections
from svg_model.shapes_canvas import ShapesCanvas


class DmfDeviceView(GtkShapesCanvasView):
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

        super(DmfDeviceView, self).__init__(df_shapes, 'path_id', **kwargs)

    def create_ui(self, *args, **kwargs):
        super(DmfDeviceView, self).create_ui(*args, **kwargs)
        # Compute centers.
        svg_canvas = ShapesCanvas(self.df_shapes, 'path_id')
        self.df_shape_connections = extract_connections(self.svg_filepath,
                                                        svg_canvas)

    def on_widget__expose_event(self, widget, event):
        from svg_model import compute_shape_centers

        super(DmfDeviceView, self).on_widget__expose_event(widget, event)
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
        if self.connections_alpha > 0:
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
            if (event.state & gtk.gdk.CONTROL_MASK):
                pass
            else:
                self.last_pressed = shape

    def on_widget__button_release_event(self, widget, event):
        '''
        Called when any mouse button is released.
        '''
        shape = self.canvas.find_shape(event.x, event.y)

        if shape is None: return

        if event.button == 1:
            if self.last_pressed == shape:
                self.notifier.notify("[electrode selected] %s" % shape)
            else:
                self.notifier.notify("[electrode pair selected] (%s, %s)" %
                                     (shape, self.last_pressed))

    def on_widget__motion_notify_event(self, widget, event):
        '''
        Called when mouse pointer is moved within drawing area.
        '''
        shape = self.canvas.find_shape(event.x, event.y)
        if shape is None: return
        #print '[motion_notify_event]', shape
        self.notifier.notify("[motion_notify_event] %s" % shape)


class DmfDeviceNotifier(object):
    '''
    Publisher
    '''
    def __init__(self):
        self._context = zmq.Context()
        self._socket = self._context.socket(zmq.PUB)

    def bind(self, bind_addr, bind_to):
        self._bind_addr = "%s:%s" % (bind_addr, bind_to)
        self._socket.bind(self._bind_addr)
        print '*** Broadcasting events on %s' % self._bind_addr

    def notify(self, mssg):
        self._socket.send_pyobj(mssg)


def parse_args(args=None):
    '''Parses arguments, returns (options, args).'''
    import sys
    from argparse import ArgumentParser
    from path_helpers import path

    if args is None:
        args = sys.argv

    parser = ArgumentParser(description='Example app for drawing shapes from '
                            'dataframe, scaled to fit to GTK canvas while '
                            'preserving aspect ratio (a.k.a., aspect fit).')
    parser.add_argument('svg_filepath', type=path, default=None)
    parser.add_argument('-p', '--padding-fraction', type=float, default=0)
    parser.add_argument('-a', '--connections-alpha', type=float, default=1)
    parser.add_argument('-c', '--connections-color', default='#ffffff')
    parser.add_argument('-w', '--connections-width', type=float, default=1)
    parser.add_argument('--address', type=str, default='tcp://*')
    parser.add_argument('--port', type=int, default=5000)

    args = parser.parse_args()
    return args


if __name__ == '__main__':
    args = parse_args()
    notifier = DmfDeviceNotifier()
    notifier.bind(args.address, args.port)
    view = DmfDeviceView(args.svg_filepath, notifier,
                         connections_color=args.connections_color,
                         connections_alpha=args.connections_alpha,
                         padding_fraction=args.padding_fraction)
    view.connections_attrs['line_width'] = args.connections_width
    print view.svg_filepath
    view.widget.connect('destroy', gtk.main_quit)
    view.show_and_run()
