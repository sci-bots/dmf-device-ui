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
      author='Anonymous',
      author_email='you@mail.com',
      url='https://github.com/wheeler-microfluidics/dmf-device-ui',
      license='GPL',
      packages=['dmf_device_ui', ],
      install_requires=[],
      # Install data listed in `MANIFEST.in`
      include_package_data=True)


@task
@needs('generate_setup', 'minilib', 'setuptools.command.sdist') 
def sdist():
    """Overrides sdist to make sure that our setup.py is generated."""
    pass
