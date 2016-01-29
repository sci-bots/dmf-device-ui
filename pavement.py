import sys

from paver.easy import task, needs, path
from paver.setuputils import setup, install_distutils_tasks

sys.path.insert(0, path('.').abspath())
import version

install_distutils_tasks()

setup(name='dmf-device-ui',
      version=version.getVersion(),
      description='Device user interface for Microdrop digital microfluidics '
      '(DMF) control software.',
      keywords='',
      author='Christian Fobel',
      author_email='christian@fobel.net',
      url='https://github.com/wheeler-microfluidics/dmf-device-ui',
      license='LGPLv2.1',
      packages=['dmf_device_ui'],
      install_requires=['microdrop-utility>=0.4', 'networkx>=1.10', 'pandas',
                        'path-helpers>=0.2', 'svg_model>=0.5.post14',
                        'pygst-utils>=0.2.post20',
                        'wheeler.pygtkhelpers>=0.11.post16',
                        'zmq-plugin>=0.2'],
      # Install data listed in `MANIFEST.in`
      include_package_data=True)


@task
@needs('generate_setup', 'minilib', 'setuptools.command.sdist')
def sdist():
    """Overrides sdist to make sure that our setup.py is generated."""
    pass
