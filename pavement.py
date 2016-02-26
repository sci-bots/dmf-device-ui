import platform
import sys

from paver.easy import task, needs, path
from paver.setuputils import setup, install_distutils_tasks

sys.path.insert(0, path('.').abspath())
import version

install_distutils_tasks()

# Platform-independent package requirements.
install_requires = ['microdrop>=2.0.post22.dev158803465',
                    'microdrop-utility>=0.4', 'networkx>=1.10', 'pandas',
                    'path-helpers>=0.2', 'pygst-utils>=0.3.post2',
                    'wheeler.pygtkhelpers>=0.12.post4', 'zmq-plugin>=0.2']

# Platform-specific package requirements.
if platform.system() == 'Windows':
    install_requires += ['opencv-python', 'pygtk2-win', 'pycairo-gtk2-win',
                         'pygst-0.10-win']
else:
    try:
        import gtk
    except ImportError:
        print >> sys.err, ('Please install Python bindings for Gtk 2 using '
                           'your systems package manager.')
    try:
        import cv2
    except ImportError:
        print >> sys.err, ('Please install OpenCV Python bindings using your '
                           'systems package manager.')
    try:
        import gst
    except ImportError:
        print >> sys.err, ('Please install GStreamer Python bindings using '
                           'your systems package manager.')

setup(name='dmf-device-ui',
      version=version.getVersion(),
      description='Device user interface for Microdrop digital microfluidics '
      '(DMF) control software.',
      keywords='',
      author='Christian Fobel',
      author_email='christian@fobel.net',
      url='https://github.com/wheeler-microfluidics/dmf-device-ui',
      license='LGPLv2.1',
      install_requires=install_requires,
      packages=['dmf_device_ui'],
      # Install data listed in `MANIFEST.in`
      include_package_data=True)


@task
@needs('generate_setup', 'minilib', 'setuptools.command.sdist')
def sdist():
    """Overrides sdist to make sure that our setup.py is generated."""
    pass
