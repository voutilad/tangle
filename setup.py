"""
Tangle setup

Template via https://github.com/noahp/python-packaging
"""
from setuptools import setup
import unittest


def init_test_suite():
    """ See https://stackoverflow.com/a/37033551 """
    test_loader = unittest.TestLoader()
    test_suite = test_loader.discover('tests', pattern='test_*.py')
    return test_suite


setup(
    name='tangle',
    version='0.0.1',
    description='File synchronization across systems.',
    author='Dave Voutila',
    author_email='voutilad@users.noreply.github.com',
    url='https://github.com/voutilad/tangle',

    packages=['tangle'],
    test_suite='setup.init_test_suite',

    # These scripts are installed to your python environment and should be
    # available on PATH after installing this package. Note that they should
    # be executable (`chmod +x`) and contain an appropriate shebang, such as
    # `#!/usr/bin/env` python for python scripts
    scripts=['tangle/bin/tangle-client.py'],

    # For scripts, this corrects shebang replacement, from:
    #  https://github.com/pybuilder/pybuilder/issues/168
    options={'build_scripts': {'executable': '/usr/bin/env python3'}},
)
