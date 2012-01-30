from modeldict.base import PersistedDict
import unittest
import mock


class TestCachedDict(unittest.TestCase):

    def setUp(self):
        self.dict = PersistedDict()

    def test_acts_like_a_dictionary(self):
        self.dict['foo'] = 'bar'
        self.assertTrue(self.dict['foo'], 'bar')

    def test_calls_persist_value_on_setitem(self):
        with mock.patch('modeldict.base.PersistedDict._persist') as pv:
          self.dict['foo'] = 'bar'
          pv.assert_called_with('foo', 'bar')

    def test_calls_depersist_on_delitem(self):
        self.dict['foo'] = 'bar'

        with mock.patch('modeldict.base.PersistedDict._depersist') as dp:
            del self.dict['foo']
            dp.assert_called_with('foo')