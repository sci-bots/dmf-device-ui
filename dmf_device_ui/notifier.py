# -*- coding: utf-8 -*-
import zmq


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
