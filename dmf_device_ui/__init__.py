# -*- coding: utf-8 -*-
import gtk
import uuid


def gtk_wait(wait_duration_s):
    gtk.main_iteration_do()


def generate_plugin_name(prefix='plugin-'):
    '''
    Generate unique plugin name.
    '''
    return prefix + str(uuid.uuid4()).split('-')[0]
