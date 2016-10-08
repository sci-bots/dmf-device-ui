@echo off
REM Construct version tag from Conda [Git environment variables][1].
REM
REM [1]: http://conda.pydata.org/docs/building/environment-vars.html#git-environment-variables
set MINOR_VERSION=%GIT_DESCRIBE_TAG:~1%
if %GIT_DESCRIBE_NUMBER%==0 (
    set PACKAGE_VERSION=%MINOR_VERSION%
) else (
    set PACKAGE_VERSION=%MINOR_VERSION%.post%GIT_DESCRIBE_NUMBER%
)

REM Generate `setup.py` from `pavement.py` definition.
"%PYTHON%" -m paver generate_setup

REM **Workaround** `conda build` runs a copy of `setup.py` named
REM `conda-build-script.py` with the recipe directory as the only argument.
REM This causes paver to fail, since the recipe directory is not a valid paver
REM task name.
REM
REM We can work around this by popping the recipe directory command line
REM argument off if the `setup.py` script is run under the name
REM `conda-build-script.py`.
"%PYTHON%" -c "input_ = open('setup.py', 'r'); data = input_.read(); input_.close(); output_ = open('setup.py', 'w'); output_.write('\n'.join(['import sys', 'import path_helpers as ph', '''if ph.path(sys.argv[0]).name == 'conda-build-script.py':''', '    sys.argv.pop()', data])); output_.close(); print open('setup.py', 'r').read()"

"%PYTHON%" -m pip install --find-links http://192.99.4.95/wheels --trusted-host 192.99.4.95 .
if errorlevel 1 exit 1
