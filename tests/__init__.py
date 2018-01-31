"""
Test Suite for tangle
"""
import unittest


def init_test_suite():
    """ See https://stackoverflow.com/a/37033551 """
    test_loader = unittest.TestLoader()
    test_suite = test_loader.discover('tests', pattern='test_*.py')
    return test_suite
