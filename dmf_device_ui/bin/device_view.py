# -*- coding: utf-8 -*-
# # TODO TODO TODO TODO TODO TODO TODO TODO TODO TODO TODO
#
# Use a separate Cairo surface for each layer of the device view (e.g.,
# electrodes, connections).
#
# Cairo surfaces can be composited over one another by using
# `set_source_surface`, which will, by default, blend according to the alpha
# channel of the source and the existing surface content.  Other blending modes
# can be used by selecting the appropriate operator.
#
# See [here][1] and [here][2] for more information.
#
# [1]: http://cairographics.org/operators/
# [2]: http://cairographics.org/FAQ/#paint_from_a_surface
#
# # TODO TODO TODO TODO TODO TODO TODO TODO TODO TODO TODO
import gtk
import logging

from ..view import DmfDeviceView
from ..canvas import DmfDeviceCanvas


def parse_args(args=None):
    '''Parses arguments, returns (options, args).'''
    import sys
    from argparse import ArgumentParser

    if args is None:
        args = sys.argv

    parser = ArgumentParser(description='Example app for drawing shapes from '
                            'dataframe, scaled to fit to GTK canvas while '
                            'preserving aspect ratio (a.k.a., aspect fit).')
    parser.add_argument('-p', '--padding-fraction', type=float, default=0)
    parser.add_argument('-a', '--connections-alpha', type=float, default=.5)
    parser.add_argument('-c', '--connections-color', default='#ffffff')
    parser.add_argument('-w', '--connections-width', type=float, default=1)

    args = parser.parse_args()
    return args


def main():
    logging.basicConfig(level=logging.INFO)

    args = parse_args()
    canvas = DmfDeviceCanvas(connections_color=args.connections_color,
                             connections_alpha=args.connections_alpha,
                             padding_fraction=args.padding_fraction)
    canvas.connections_attrs['line_width'] = args.connections_width
    view = DmfDeviceView(canvas)
    view.widget.connect('destroy', gtk.main_quit)
    view.show_and_run()


if __name__ == '__main__':
    main()
