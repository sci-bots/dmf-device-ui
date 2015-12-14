# -*- coding: utf-8 -*-
import gtk

from ..view import DmfDeviceView
from ..canvas import DmfDeviceCanvas
from ..notifier import DmfDeviceNotifier


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
    canvas = DmfDeviceCanvas(args.svg_filepath, notifier,
                             connections_color=args.connections_color,
                             connections_alpha=args.connections_alpha,
                             padding_fraction=args.padding_fraction)
    canvas.connections_attrs['line_width'] = args.connections_width
    view = DmfDeviceView(canvas)
    view.widget.connect('destroy', gtk.main_quit)
    view.show_and_run()
