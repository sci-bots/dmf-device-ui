# -*- coding: utf-8 -*-
from pygtkhelpers.utils import refresh_gui
import uuid


def gtk_wait(wait_duration_s):
    refresh_gui()


def generate_plugin_name(prefix='plugin-'):
    '''
    Generate unique plugin name.
    '''
    return prefix + str(uuid.uuid4()).split('-')[0]
