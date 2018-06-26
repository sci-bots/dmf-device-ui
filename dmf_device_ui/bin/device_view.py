# -*- coding: utf-8 -*-
from contextlib import closing
import json
import pkgutil
import sys

import gtk
import logging

from ..canvas import DmfDeviceCanvas
from ..view import DmfDeviceFixedHubView, DmfDeviceConfigurableHubView


def parse_args(args=None):
    '''Parses arguments, returns (options, args).'''
    from argparse import ArgumentParser

    if args is None:
        args = sys.argv

    parser = ArgumentParser(description='Example app for drawing shapes from '
                            'dataframe, scaled to fit to GTK canvas while '
                            'preserving aspect ratio (a.k.a., aspect fit).')
    parser.add_argument('-p', '--padding-fraction', type=float, default=0)
    parser.add_argument('--connections-color', default='#ffffff')
    parser.add_argument('--connections-alpha', type=float, default=.5)
    parser.add_argument('--connections-width', type=float, default=1)
    parser.add_argument('-n', '--plugin-name', default=None)
    parser.add_argument('-a', '--allocation', default=None,
                        help='Window allocation: x, y, width, height (JSON'
                        'object)')
    parser.add_argument('-d', '--debug', action='store_true',
                        help='Include IPython button for debugging.')

    subparsers = parser.add_subparsers(help='help for subcommand',
                                       dest='command')

    parser_fixed = subparsers.add_parser('fixed', help='Start view with fixed'
                                         'name and hub URI.')
    parser_fixed.add_argument('hub_uri')

    parser_config = subparsers.add_parser('configurable', help='Start view '
                                          'with configurable name and hub '
                                          'URI.')
    parser_config.add_argument('hub_uri', nargs='?')

    args = parser.parse_args()
    return args


def main():
    logging.basicConfig(level=logging.INFO)

    args = parse_args()
    allocation = (None if args.allocation is None
                  else json.loads(args.allocation))
    canvas = DmfDeviceCanvas(connections_color=args.connections_color,
                             connections_alpha=args.connections_alpha,
                             padding_fraction=args.padding_fraction,
                             width=480, height=240)
    canvas.connections_attrs['line_width'] = args.connections_width

    if args.command == 'fixed':
        view = DmfDeviceFixedHubView(canvas, hub_uri=args.hub_uri,
                                     plugin_name=args.plugin_name,
                                     allocation=allocation,
                                     debug_view=args.debug)
    elif args.command == 'configurable':
        view = DmfDeviceConfigurableHubView(canvas, hub_uri=args.hub_uri,
                                            plugin_name=args.plugin_name,
                                            allocation=allocation,
                                            debug_view=args.debug)

    view.widget.connect('destroy', gtk.main_quit)

    def init_window_titlebar(widget):
        '''
        Set window title and icon.

        .. versionchanged:: v0.11.1
            Load icon from string to support loading from ``.zip`` file.
        '''
        view.widget.parent.set_title('DMF device user interface')

        # [Load icon from string][1] to support loading from `.zip` file.
        #
        # [1]: https://bytes.com/topic/python/answers/29401-pygtk-creating-pixbuf-image-data#post109157
        icon_str = pkgutil.get_data('microdrop', 'microdrop.ico')
        with closing(gtk.gdk.PixbufLoader('ico')) as loader:
            loader.write(icon_str)
        icon_pixbuf = loader.get_pixbuf()
        view.widget.parent.set_icon(icon_pixbuf)

    view.widget.connect('realize', init_window_titlebar)
    if args.command == 'fixed':
        logging.info('Register connect_plugin')
        view.canvas_slave.widget.connect('map-event', lambda *args:
                                         view.connect_plugin())

    view.show_and_run()


if __name__ == '__main__':
    main()
