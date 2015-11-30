import os

import gtk
from pygtkhelpers.delegates import SlaveView
from droplet_planning import svg_polygons_to_df
import pandas as pd
from .device import ShapesCanvas


class GtkCairoView(SlaveView):
    """
    SlaveView for Cairo drawing surface.
    """

    def __init__(self, width=None, height=None):
        if width is None:
            self.width = 640
        else:
            self.width = width
        if height is None:
            self.height = 480
        else:
            self.height = height
        super(GtkCairoView, self).__init__()

    def create_ui(self):
        self.widget = gtk.DrawingArea()
        self.widget.set_size_request(self.width, self.height)
        self.window_xid = None
        self._set_window_title = False

    def show_and_run(self):
        self._set_window_title = True
        #import IPython
        #gtk.timeout_add(1000, IPython.embed)
        super(GtkCairoView, self).show_and_run()

    def on_widget__realize(self, widget):
        if not self.widget.window.has_native():
            # Note that this is required (at least for Windows) to ensure that
            # the DrawingArea has a native window assigned.  In Windows, if
            # this is not done, the video is written to the parent OS window
            # (not a "window" in the traditional sense of an app, but rather in
            # the window manager clipped rectangle sense).  The symptom is that
            # the video will be drawn over top of any widgets, etc. in the
            # parent window.
            if not self.widget.window.ensure_native():
                raise RuntimeError, 'Failed to get native window handle'
        if os.name == 'nt':
            self.window_xid = self.widget.window.handle
        else:
            self.window_xid = self.widget.window.xid
        # Copy window xid to clipboard
        clipboard = gtk.Clipboard()
        clipboard.set_text(str(self.window_xid))
        if self._set_window_title:
            self.widget.parent.set_title('[window_xid] %s' % self.window_xid)
        print '[window_xid] %s' % self.window_xid


class GtkShapesCanvasView(GtkCairoView):
    def __init__(self, df_shapes, shape_i_columns, padding_fraction=0,
                 **kwargs):
        self.canvas = None
        self.df_shapes = df_shapes
        self.shape_i_columns = shape_i_columns
        self.padding_fraction = padding_fraction
        self._canvas_reset_request = False
        super(GtkShapesCanvasView, self).__init__(**kwargs)

    @classmethod
    def from_svg(cls, svg_filepath, **kwargs):
        df_shapes = svg_polygons_to_df(svg_filepath)
        return cls(df_shapes, 'path_id', **kwargs)

    def create_ui(self):
        super(GtkShapesCanvasView, self).create_ui()
        self.widget.set_events(gtk.gdk.BUTTON_PRESS |
                               gtk.gdk.BUTTON_RELEASE |
                               gtk.gdk.BUTTON_MOTION_MASK |
                               gtk.gdk.BUTTON_PRESS_MASK |
                               gtk.gdk.BUTTON_RELEASE_MASK |
                               gtk.gdk.POINTER_MOTION_MASK)

    def draw_shapes(self):
        cairo_context = self.widget.window.cairo_create()

        for path_id, df_path_i in (self.canvas.df_canvas_shapes
                                   .groupby(self.canvas
                                            .shape_i_columns)[['x', 'y']]):
            cairo_context.move_to(*df_path_i.iloc[0][['x', 'y']])
            for i, (x, y) in df_path_i[['x', 'y']].iloc[1:].iterrows():
                cairo_context.line_to(x, y)
            cairo_context.close_path()
            cairo_context.set_source_rgb(0, 0, 1)
            cairo_context.fill()

    def on_canvas_reset_tick(self, width, height):
        canvas_shape = pd.Series([width, height], index=['width', 'height'])
        self.canvas = ShapesCanvas(self.df_shapes, self.shape_i_columns,
                                   canvas_shape=canvas_shape,
                                   padding_fraction=self.padding_fraction)
        self._canvas_reset_request = False
        gtk.idle_add(self.widget.queue_draw)
        return False

    ###########################################################################
    # ## Mouse event handling ##
    def on_widget__button_press_event(self, widget, event):
        '''
        Called when any mouse button is pressed.
        '''
        shape = self.canvas.find_shape(event.x, event.y)
        if shape is None: return
        print '[button_press_event]', shape, event.button

    def on_widget__button_release_event(self, widget, event):
        '''
        Called when any mouse button is released.
        '''
        shape = self.canvas.find_shape(event.x, event.y)
        if shape is None: return
        print '[button_release_event]', shape, event.button

    def on_widget__motion_notify_event(self, widget, event):
        '''
        Called when mouse pointer is moved within drawing area.
        '''
        shape = self.canvas.find_shape(event.x, event.y)
        if shape is None: return
        print '[motion_notify_event]', shape

    def on_widget__configure_event(self, widget, event):
        '''
        Called when size of drawing area changes.
        '''
        if event.x < 0 and event.y < 0:
            # Widget has not been allocated a size yet, so do nothing.
            return
        # Use `self._canvas_reset_request` latch to throttle configure event handling.
        # This makes the UI more responsive when resizing the drawing area, for
        # example, by dragging the window border.
        if not self._canvas_reset_request:
            self._canvas_reset_request = True
            #gtk.timeout_add(50, self.on_canvas_reset_tick, event.width,
                            #event.height)
            gtk.idle_add(self.on_canvas_reset_tick, event.width, event.height)

    def on_widget__expose_event(self, widget, event):
        '''
        Called when drawing area is first displayed and, for example, when part
        of drawing area is uncovered after being covered up by another window.
        '''
        if self.canvas is None:
            return
        # Draw shapes from SVG.
        self.draw_shapes()


def parse_args(args=None):
    """Parses arguments, returns (options, args)."""
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

    args = parser.parse_args()
    return args


if __name__ == '__main__':
    args = parse_args()
    view = GtkShapesCanvasView.from_svg(args.svg_filepath,
                                        padding_fraction=args.padding_fraction)
    view.widget.connect('destroy', gtk.main_quit)
    view.show_and_run()
