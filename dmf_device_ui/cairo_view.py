import os

import gtk
from pygtkhelpers.ui.views.shapes_canvas_view import GtkShapesCanvasView


class DmfDeviceView(GtkShapesCanvasView):
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
    view = DmfDeviceView.from_svg(args.svg_filepath,
                                  padding_fraction=args.padding_fraction)
    view.widget.connect('destroy', gtk.main_quit)
    view.show_and_run()
