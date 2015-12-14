import sys
import zmq
import time


def main():
    port = 5000
    if len(sys.argv) > 1:
        port =  sys.argv[1]
        int(port)

    bind_addr = "tcp://localhost:%s" % port

    context = zmq.Context()
    socket = context.socket(zmq.SUB)
    socket.connect(bind_addr)
    socket.setsockopt(zmq.SUBSCRIBE,'')

    print "Listening for events on %s ..." % bind_addr
    while True:
        try:
            try:
                mssg = socket.recv(zmq.NOBLOCK)
                print mssg
            except zmq.error.Again:
                time.sleep(0.001)
        except KeyboardInterrupt:
            break


if __name__ == '__main__':
    main()
