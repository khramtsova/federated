# Lint as: python3
# Copyright 2018, The TensorFlow Federated Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import collections
import inspect
import itertools

from absl.testing import parameterized
import tensorflow as tf

from tensorflow_federated.python.common_libs import anonymous_tuple
from tensorflow_federated.python.common_libs import test
from tensorflow_federated.python.core.api import computation_types
from tensorflow_federated.python.core.impl import context_base
from tensorflow_federated.python.core.impl import context_stack_impl
from tensorflow_federated.python.core.impl import type_utils
from tensorflow_federated.python.core.impl.utils import function_utils


class SimpleArgSpecTest(test.TestCase):

  def test_str(self):
    arg_spec = function_utils.SimpleArgSpec(
        args=[], varargs=[], keywords=[], defaults=[])
    self.assertEqual('()', str(arg_spec))

    arg_spec = function_utils.SimpleArgSpec(
        args=[1, 2, 3], varargs=[], keywords=[], defaults=[])
    self.assertEqual('(args=[1, 2, 3])', str(arg_spec))

    arg_spec = function_utils.SimpleArgSpec(
        args=[1], varargs=[2., True], keywords={'a': 'b'}, defaults={'x': 3})
    self.assertEqual(
        "(args=[1], varargs=[2.0, True], kwargs={'a': 'b'}, defaults={'x': 3})",
        str(arg_spec))


class NoopIngestContextForTest(context_base.Context):

  def ingest(self, val, type_spec):
    type_utils.check_type(val, type_spec)
    return val

  def invoke(self, comp, arg):
    raise NotImplementedError


class FuncUtilsTest(test.TestCase, parameterized.TestCase):

  def test_is_defun(self):
    self.assertTrue(function_utils.is_defun(tf.function(lambda x: None)))
    fn = tf.function(lambda x: None, (tf.TensorSpec(None, tf.int32),))
    self.assertTrue(function_utils.is_defun(fn))
    self.assertFalse(function_utils.is_defun(lambda x: None))
    self.assertFalse(function_utils.is_defun(None))

  def test_get_defun_argspec_with_typed_non_eager_defun(self):
    # In a non-eager function with a defined input signature, **kwargs or
    # default values are not allowed, but *args are, and the input signature may
    # overlap with *args.
    fn = tf.function(lambda x, y, *z: None, (
        tf.TensorSpec(None, tf.int32),
        tf.TensorSpec(None, tf.bool),
        tf.TensorSpec(None, tf.float32),
        tf.TensorSpec(None, tf.float32),
    ))
    self.assertEqual(
        function_utils.get_argspec(fn),
        function_utils.SimpleArgSpec(
            args=['x', 'y'], varargs='z', keywords=None, defaults=None))

  def test_get_defun_argspec_with_untyped_non_eager_defun(self):
    # In a non-eager function with no input signature, the same restrictions as
    # in a typed eager function apply.
    fn = tf.function(lambda x, y, *z: None)
    self.assertEqual(
        function_utils.get_argspec(fn),
        function_utils.SimpleArgSpec(
            args=['x', 'y'], varargs='z', keywords=None, defaults=None))

  # pyformat: disable
  @parameterized.parameters(
      itertools.product(
          # Values of 'fn' to test.
          [lambda: None,
           lambda a: None,
           lambda a, b: None,
           lambda *a: None,
           lambda **a: None,
           lambda *a, **b: None,
           lambda a, *b: None,
           lambda a, **b: None,
           lambda a, b, **c: None,
           lambda a, b=10: None,
           lambda a, b=10, c=20: None,
           lambda a, b=10, *c: None,
           lambda a, b=10, **c: None,
           lambda a, b=10, *c, **d: None,
           lambda a, b, c=10, *d: None,
           lambda a=10, b=20, c=30, **d: None],
          # Values of 'args' to test.
          [[], [1], [1, 2], [1, 2, 3], [1, 2, 3, 4]],
          # Values of 'kwargs' to test.
          [{}, {'b': 100}, {'name': 'foo'}, {'b': 100, 'name': 'foo'}]))
  # pyformat: enable
  def test_get_callargs_for_argspec(self, fn, args, kwargs):
    argspec = function_utils.get_argspec(fn)
    expected_error = None
    try:
      signature = inspect.signature(fn)
      bound_arguments = signature.bind(*args, **kwargs)
      bound_arguments.apply_defaults()
      expected_callargs = bound_arguments.arguments
    except TypeError as e:
      expected_error = e
      expected_callargs = None

    result_callargs = None
    if expected_error is None:
      try:
        result_callargs = function_utils.get_callargs_for_argspec(
            argspec, *args, **kwargs)
        self.assertEqual(result_callargs, expected_callargs)
      except (TypeError, AssertionError) as test_err:
        raise AssertionError(
            'With argspec {!s}, args {!s}, kwargs {!s}, expected callargs {!s} '
            'and error {!s}, tested function returned {!s} and the test has '
            'failed with message: {!s}'.format(argspec, args, kwargs,
                                               expected_callargs,
                                               expected_error, result_callargs,
                                               test_err))
    else:
      with self.assertRaises(TypeError):
        result_callargs = function_utils.get_callargs_for_argspec(
            argspec, *args, **kwargs)

  # pyformat: disable
  # pylint: disable=g-complex-comprehension
  @parameterized.parameters(
      (function_utils.get_argspec(params[0]),) + params[1:]
      for params in [
          (lambda a: None, [tf.int32], {}),
          (lambda a, b=True: None, [tf.int32, tf.bool], {}),
          (lambda a, b=True: None, [tf.int32], {'b': tf.bool}),
          (lambda a, b=True: None, [tf.bool], {'b': tf.bool}),
          (lambda a=10, b=True: None, [tf.int32], {'b': tf.bool}),
      ]
  )
  # pylint: enable=g-complex-comprehension
  # pyformat: enable
  def test_is_argspec_compatible_with_types_true(self, argspec, args, kwargs):
    self.assertTrue(
        function_utils.is_argspec_compatible_with_types(
            argspec, *[computation_types.to_type(a) for a in args],
            **{k: computation_types.to_type(v) for k, v in kwargs.items()}))

  # pyformat: disable
  # pylint: disable=g-complex-comprehension
  @parameterized.parameters(
      (function_utils.get_argspec(params[0]),) + params[1:]
      for params in [
          (lambda a=True: None, [tf.int32], {}),
          (lambda a=10, b=True: None, [tf.bool], {'b': tf.bool}),
      ]
  )
  # pylint: enable=g-complex-comprehension
  # pyformat: enable
  def test_is_argspec_compatible_with_types_false(self, argspec, args, kwargs):
    self.assertFalse(
        function_utils.is_argspec_compatible_with_types(
            argspec, *[computation_types.to_type(a) for a in args],
            **{k: computation_types.to_type(v) for k, v in kwargs.items()}))

  # pyformat: disable
  @parameterized.parameters(
      (tf.int32, False),
      ([tf.int32, tf.int32], True),
      ([tf.int32, ('b', tf.int32)], True),
      ([('a', tf.int32), ('b', tf.int32)], True),
      ([('a', tf.int32), tf.int32], False),
      (anonymous_tuple.AnonymousTuple([(None, 1), ('a', 2)]), True),
      (anonymous_tuple.AnonymousTuple([('a', 1), (None, 2)]), False))
  # pyformat: enable
  def test_is_argument_tuple(self, arg, expected_result):
    self.assertEqual(function_utils.is_argument_tuple(arg), expected_result)

  # pyformat: disable
  @parameterized.parameters(
      (anonymous_tuple.AnonymousTuple([(None, 1)]), [1], {}),
      (anonymous_tuple.AnonymousTuple([(None, 1), ('a', 2)]), [1], {'a': 2}))
  # pyformat: enable
  def test_unpack_args_from_anonymous_tuple(self, tuple_with_args,
                                            expected_args, expected_kwargs):
    self.assertEqual(
        function_utils.unpack_args_from_tuple(tuple_with_args),
        (expected_args, expected_kwargs))

  # pyformat: disable
  @parameterized.parameters(
      ([tf.int32], [tf.int32], {}),
      ([('a', tf.int32)], [], {'a': tf.int32}),
      ([tf.int32, tf.bool], [tf.int32, tf.bool], {}),
      ([tf.int32, ('b', tf.bool)], [tf.int32], {'b': tf.bool}),
      ([('a', tf.int32), ('b', tf.bool)], [], {'a': tf.int32, 'b': tf.bool}))
  # pyformat: enable
  def test_unpack_args_from_tuple_type(self, tuple_with_args, expected_args,
                                       expected_kwargs):
    args, kwargs = function_utils.unpack_args_from_tuple(tuple_with_args)
    self.assertEqual(len(args), len(expected_args))
    for idx, arg in enumerate(args):
      self.assertTrue(
          type_utils.are_equivalent_types(
              arg, computation_types.to_type(expected_args[idx])))
    self.assertEqual(set(kwargs.keys()), set(expected_kwargs.keys()))
    for k, v in kwargs.items():
      self.assertTrue(
          type_utils.are_equivalent_types(
              computation_types.to_type(v), expected_kwargs[k]))

  def test_pack_args_into_anonymous_tuple_without_type_spec(self):
    self.assertEqual(
        function_utils.pack_args_into_anonymous_tuple([1], {'a': 10}),
        anonymous_tuple.AnonymousTuple([(None, 1), ('a', 10)]))
    self.assertIn(
        function_utils.pack_args_into_anonymous_tuple([1, 2], {
            'a': 10,
            'b': 20
        }), [
            anonymous_tuple.AnonymousTuple([
                (None, 1),
                (None, 2),
                ('a', 10),
                ('b', 20),
            ]),
            anonymous_tuple.AnonymousTuple([
                (None, 1),
                (None, 2),
                ('b', 20),
                ('a', 10),
            ])
        ])
    self.assertIn(
        function_utils.pack_args_into_anonymous_tuple([], {
            'a': 10,
            'b': 20
        }), [
            anonymous_tuple.AnonymousTuple([('a', 10), ('b', 20)]),
            anonymous_tuple.AnonymousTuple([('b', 20), ('a', 10)])
        ])
    self.assertEqual(
        function_utils.pack_args_into_anonymous_tuple([1], {}),
        anonymous_tuple.AnonymousTuple([(None, 1)]))

  # pyformat: disable
  @parameterized.parameters(
      ([1], {}, [tf.int32], [(None, 1)]),
      ([1, True], {}, [tf.int32, tf.bool], [(None, 1), (None, True)]),
      ([1, True], {}, [('x', tf.int32), ('y', tf.bool)],
       [('x', 1), ('y', True)]),
      ([1], {'y': True}, [('x', tf.int32), ('y', tf.bool)],
       [('x', 1), ('y', True)]),
      ([], {'x': 1, 'y': True}, [('x', tf.int32), ('y', tf.bool)],
       [('x', 1), ('y', True)]),
      ([], collections.OrderedDict([('y', True), ('x', 1)]),
       [('x', tf.int32), ('y', tf.bool)],
       [('x', 1), ('y', True)]))
  # pyformat: enable
  def test_pack_args_into_anonymous_tuple_with_type_spec_expect_success(
      self, args, kwargs, type_spec, elements):
    self.assertEqual(
        function_utils.pack_args_into_anonymous_tuple(
            args, kwargs, type_spec, NoopIngestContextForTest()),
        anonymous_tuple.AnonymousTuple(elements))

  # pyformat: disable
  @parameterized.parameters(
      ([1], {}, [(tf.bool)]),
      ([], {'x': 1, 'y': True}, [(tf.int32), (tf.bool)]))
  # pyformat: enable
  def test_pack_args_into_anonymous_tuple_with_type_spec_expect_failure(
      self, args, kwargs, type_spec):
    with self.assertRaises(TypeError):
      function_utils.pack_args_into_anonymous_tuple(args, kwargs, type_spec,
                                                    NoopIngestContextForTest())

  # pyformat: disable
  @parameterized.parameters(
      (None, [], {}, 'None'),
      (tf.int32, [1], {}, '1'),
      ([tf.int32, tf.bool], [1, True], {}, '<1,True>'),
      ([('x', tf.int32), ('y', tf.bool)], [1, True], {}, '<x=1,y=True>'),
      ([('x', tf.int32), ('y', tf.bool)], [1], {'y': True}, '<x=1,y=True>'),
      ([tf.int32, tf.bool],
       [anonymous_tuple.AnonymousTuple([(None, 1), (None, True)])], {},
       '<1,True>'))
  # pyformat: enable
  def test_pack_args(self, parameter_type, args, kwargs, expected_value_string):
    self.assertEqual(
        str(
            function_utils.pack_args(parameter_type, args, kwargs,
                                     NoopIngestContextForTest())),
        expected_value_string)

  # pyformat: disable
  @parameterized.parameters(
      (1, lambda: 10, None, None, None, 10),
      (2, lambda x=1: x + 10, None, None, None, 11),
      (3, lambda x=1: x + 10, tf.int32, None, 20, 30),
      (4, lambda x, y: x + y, [tf.int32, tf.int32], None,
       anonymous_tuple.AnonymousTuple([('x', 5), ('y', 6)]), 11),
      (5, lambda *args: str(args), [tf.int32, tf.int32], True,
       anonymous_tuple.AnonymousTuple([(None, 5), (None, 6)]), '(5, 6)'),
      (6, lambda *args: str(args), [('x', tf.int32), ('y', tf.int32)], False,
       anonymous_tuple.AnonymousTuple([('x', 5), ('y', 6)]),
       '(AnonymousTuple([(\'x\', 5), (\'y\', 6)]),)'),
      (7, lambda x: str(x),  # pylint: disable=unnecessary-lambda
       [tf.int32], None, anonymous_tuple.AnonymousTuple([(None, 10)]), '[10]'))
  # pyformat: enable
  def test_wrap_as_zero_or_one_arg_callable(self, unused_index, fn,
                                            parameter_type, unpack, arg,
                                            expected_result):
    wrapped_fn = function_utils.wrap_as_zero_or_one_arg_callable(
        fn, parameter_type, unpack)
    actual_result = wrapped_fn(arg) if parameter_type else wrapped_fn()
    self.assertEqual(actual_result, expected_result)

  def test_polymorphic_function(self):

    class ContextForTest(context_base.Context):

      def ingest(self, val, type_spec):
        return val

      def invoke(self, comp, arg):
        return 'name={},type={},arg={}'.format(
            comp.name, str(comp.type_signature.parameter), str(arg))

    class TestFunction(function_utils.ConcreteFunction):

      def __init__(self, name, parameter_type):
        self._name = name
        super(TestFunction, self).__init__(
            computation_types.FunctionType(parameter_type, tf.string),
            context_stack_impl.context_stack)

      @property
      def name(self):
        return self._name

    class TestFunctionFactory(object):

      def __init__(self):
        self._count = 0

      def __call__(self, parameter_type):
        self._count = self._count + 1
        return TestFunction(str(self._count), parameter_type)

    with context_stack_impl.context_stack.install(ContextForTest()):
      fn = function_utils.PolymorphicFunction(TestFunctionFactory())
      self.assertEqual(fn(10), 'name=1,type=<int32>,arg=<10>')
      self.assertEqual(
          fn(20, x=True), 'name=2,type=<int32,x=bool>,arg=<20,x=True>')
      self.assertEqual(fn(True), 'name=3,type=<bool>,arg=<True>')
      self.assertEqual(
          fn(30, x=40), 'name=4,type=<int32,x=int32>,arg=<30,x=40>')
      self.assertEqual(fn(50), 'name=1,type=<int32>,arg=<50>')
      self.assertEqual(
          fn(0, x=False), 'name=2,type=<int32,x=bool>,arg=<0,x=False>')
      self.assertEqual(fn(False), 'name=3,type=<bool>,arg=<False>')
      self.assertEqual(
          fn(60, x=70), 'name=4,type=<int32,x=int32>,arg=<60,x=70>')

  def test_concrete_function(self):

    class ContextForTest(context_base.Context):

      def ingest(self, val, type_spec):
        return val

      def invoke(self, comp, arg):
        return comp.invoke_fn(arg)

    class TestFunction(function_utils.ConcreteFunction):

      def __init__(self, type_signature, invoke_fn):
        super(TestFunction, self).__init__(type_signature,
                                           context_stack_impl.context_stack)
        self._invoke_fn = invoke_fn

      def invoke_fn(self, arg):
        return self._invoke_fn(arg)

    with context_stack_impl.context_stack.install(ContextForTest()):
      fn = TestFunction(
          computation_types.FunctionType(tf.int32, tf.bool), lambda x: x > 10)
      self.assertEqual(fn(5), False)
      self.assertEqual(fn(15), True)

      fn = TestFunction(
          computation_types.FunctionType([('x', tf.int32), ('y', tf.int32)],
                                         tf.bool), lambda arg: arg.x > arg.y)
      self.assertEqual(fn(5, 10), False)
      self.assertEqual(fn(10, 5), True)
      self.assertEqual(fn(y=10, x=5), False)
      self.assertEqual(fn(y=5, x=10), True)
      self.assertEqual(fn(10, y=5), True)


if __name__ == '__main__':
  test.main()
