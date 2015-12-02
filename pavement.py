import sys

from paver.easy import task, needs, path, sh, cmdopts, options
from paver.setuputils import setup, install_distutils_tasks
from distutils.extension import Extension
from distutils.dep_util import newer

sys.path.insert(0, path('.').abspath())
import version

setup(name='dmf-device-ui',
      version=version.getVersion(),
      description='Add description here.',
      keywords='',
      author='Christian Fobel',
      author_email='christian@fobel.net',
      url='https://github.com/wheeler-microfluidics/dmf-device-ui',
      license='GPL',
      packages=['dmf_device_ui', ],
      install_requires=['svg_model>=0.4.post2', 'pymunk==2.1.0',
                        'wheeler.pygtkhelpers>=0.11.post1'],
      # Install data listed in `MANIFEST.in`
      include_package_data=True)


@task
@needs('generate_setup', 'minilib', 'setuptools.command.sdist')
def sdist():
    """Overrides sdist to make sure that our setup.py is generated."""
    pass
