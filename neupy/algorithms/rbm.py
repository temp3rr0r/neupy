import numpy as np
import tensorflow as tf

from neupy.core.config import DumpableObject
from neupy.core.properties import IntProperty, ParameterProperty
from neupy.algorithms.base import BaseNetwork
from neupy.algorithms.constructor import BaseAlgorithm, function
from neupy.algorithms.gd.base import (
    MinibatchTrainingMixin,
    average_batch_errors
)
from neupy.layers.base import create_shared_parameter
from neupy.utils import (
    asfloat, format_data, dot,
    initialize_uninitialized_variables
)
from neupy import init


__all__ = ('RBM',)


def random_binomial(p):
    with tf.name_scope('random-binomial'):
        samples = tf.random_uniform(tf.shape(p), dtype=tf.float32) <= p
        return tf.cast(samples, tf.float32)


def random_sample(data, n_samples):
    with tf.name_scope('random-sample'):
        data_shape = tf.shape(data)
        max_index = data_shape[0]
        sample_indeces = tf.random_uniform(
            (n_samples,), minval=0, maxval=max_index,
            dtype=tf.int32
        )
        return tf.gather(data, sample_indeces)


class RBM(BaseAlgorithm, BaseNetwork, MinibatchTrainingMixin, DumpableObject):
    """
    Boolean/Bernoulli Restricted Boltzmann Machine (RBM).
    Algorithm assumes that inputs are either binary
    values or values between 0 and 1.

    Parameters
    ----------
    n_visible : int
        Number of visible units. Number of features (columns)
        in the input data.

    n_hidden : int
        Number of hidden units. The large the number the more
        information network can capture from the data, but it
        also mean that network is more likely to overfit.

    batch_size : int
        Size of the mini-batch. Defaults to ``10``.

    weight : array-like, Tensorfow variable, Initializer or scalar
        Default initialization methods
        you can find :ref:`here <init-methods>`.
        Defaults to :class:`Normal <neupy.init.Normal>`.

    hidden_bias : array-like, Tensorfow variable, Initializer or scalar
        Default initialization methods
        you can find :ref:`here <init-methods>`.
        Defaults to :class:`Constant(value=0) <neupy.init.Constant>`.

    visible_bias : array-like, Tensorfow variable, Initializer or scalar
        Default initialization methods
        you can find :ref:`here <init-methods>`.
        Defaults to :class:`Constant(value=0) <neupy.init.Constant>`.

    {BaseNetwork.Parameters}

    Methods
    -------
    train(input_train, epochs=100)
        Trains network.

    {BaseSkeleton.fit}

    visible_to_hidden(visible_input)
        Populates data throught the network and returns output
        from the hidden layer.

    hidden_to_visible(hidden_input)
        Propagates output from the hidden layer backward
        to the visible.

    gibbs_sampling(visible_input, n_iter=1)
        Makes Gibbs sampling ``n`` times using visible input.

    Examples
    --------
    >>> import numpy as np
    >>> from neupy import algorithms
    >>>
    >>> data = np.array([
    ...     [1, 0, 1, 0],
    ...     [1, 0, 1, 0],
    ...     [1, 0, 0, 0],  # incomplete sample
    ...     [1, 0, 1, 0],
    ...
    ...     [0, 1, 0, 1],
    ...     [0, 0, 0, 1],  # incomplete sample
    ...     [0, 1, 0, 1],
    ...     [0, 1, 0, 1],
    ...     [0, 1, 0, 1],
    ...     [0, 1, 0, 1],
    ... ])
    >>>
    >>> rbm = algorithms.RBM(n_visible=4, n_hidden=1)
    >>> rbm.train(data, epochs=100)
    >>>
    >>> hidden_states = rbm.visible_to_hidden(data)
    >>> hidden_states.round(2)
    array([[ 0.99],
           [ 0.99],
           [ 0.95],
           [ 0.99],
           [ 0.  ],
           [ 0.01],
           [ 0.  ],
           [ 0.  ],
           [ 0.  ],
           [ 0.  ]])

    References
    ----------
    [1] G. Hinton, A Practical Guide to Training Restricted
        Boltzmann Machines, 2010.
        http://www.cs.toronto.edu/~hinton/absps/guideTR.pdf
    """
    n_visible = IntProperty(minval=1)
    n_hidden = IntProperty(minval=1)
    batch_size = IntProperty(minval=1, default=10)

    weight = ParameterProperty(default=init.Normal())
    hidden_bias = ParameterProperty(default=init.Constant(value=0))
    visible_bias = ParameterProperty(default=init.Constant(value=0))

    def __init__(self, n_visible, n_hidden, **options):
        options.update({'n_visible': n_visible, 'n_hidden': n_hidden})
        super(RBM, self).__init__(**options)

    def init_input_output_variables(self):
        with tf.variable_scope('rbm'):
            self.weight = create_shared_parameter(
                value=self.weight,
                name='weight',
                shape=(self.n_visible, self.n_hidden)
            )
            self.hidden_bias = create_shared_parameter(
                value=self.hidden_bias,
                name='hidden-bias',
                shape=(self.n_hidden,),
            )
            self.visible_bias = create_shared_parameter(
                value=self.visible_bias,
                name='visible-bias',
                shape=(self.n_visible,),
            )

            self.variables.update(
                network_input=tf.placeholder(
                    tf.float32,
                    (None, self.n_visible),
                    name="network-input",
                ),
                network_hidden_input=tf.placeholder(
                    tf.float32,
                    (None, self.n_hidden),
                    name="network-hidden-input",
                )
            )

    def init_variables(self):
        with tf.variable_scope('rbm'):
            self.variables.update(
                h_samples=tf.Variable(
                    tf.zeros([self.batch_size, self.n_hidden]),
                    name="hidden-samples",
                    dtype=tf.float32,
                ),
            )

    def init_methods(self):
        def free_energy(visible_sample):
            with tf.name_scope('free-energy'):
                wx = tf.matmul(visible_sample, self.weight)
                wx_b = wx + self.hidden_bias

                visible_bias_term = dot(visible_sample, self.visible_bias)

                # We can get infinity when wx_b is a relatively large number
                # (maybe 100). Taking exponent makes it even larger and
                # for with float32 it can convert it to infinity. But because
                # number is so large we don't care about +1 value before taking
                # logarithms and therefore we can just pick value as it is
                # since our operation won't change anything.
                hidden_terms = tf.where(
                    # exp(30) is such a big number that +1 won't
                    # make any difference in the outcome.
                    tf.greater(wx_b, 30),
                    wx_b,
                    tf.log1p(tf.exp(wx_b)),
                )

                hidden_term = tf.reduce_sum(hidden_terms, axis=1)
                return -(visible_bias_term + hidden_term)

        def visible_to_hidden(visible_sample):
            with tf.name_scope('visible-to-hidden'):
                wx = tf.matmul(visible_sample, self.weight)
                wx_b = wx + self.hidden_bias
                return tf.nn.sigmoid(wx_b)

        def hidden_to_visible(hidden_sample):
            with tf.name_scope('hidden-to-visible'):
                wx = tf.matmul(hidden_sample, self.weight, transpose_b=True)
                wx_b = wx + self.visible_bias
                return tf.nn.sigmoid(wx_b)

        def sample_hidden_from_visible(visible_sample):
            with tf.name_scope('sample-hidden-to-visible'):
                hidden_prob = visible_to_hidden(visible_sample)
                hidden_sample = random_binomial(hidden_prob)
                return hidden_sample

        def sample_visible_from_hidden(hidden_sample):
            with tf.name_scope('sample-visible-to-hidden'):
                visible_prob = hidden_to_visible(hidden_sample)
                visible_sample = random_binomial(visible_prob)
                return visible_sample

        network_input = self.variables.network_input
        network_hidden_input = self.variables.network_hidden_input
        input_shape = tf.shape(network_input)
        n_samples = input_shape[0]

        weight = self.weight
        h_bias = self.hidden_bias
        v_bias = self.visible_bias
        h_samples = self.variables.h_samples
        step = asfloat(self.step)

        with tf.name_scope('positive-values'):
            # We have to use `cond` instead of `where`, because
            # different if-else cases might have different shapes
            # and it triggers exception in tensorflow.
            v_pos = tf.cond(
                tf.equal(n_samples, self.batch_size),
                lambda: network_input,
                lambda: random_sample(network_input, self.batch_size)
            )
            h_pos = visible_to_hidden(v_pos)

        with tf.name_scope('negative-values'):
            v_neg = sample_visible_from_hidden(h_samples)
            h_neg = visible_to_hidden(v_neg)

        with tf.name_scope('weight-update'):
            weight_update = (
                tf.matmul(v_pos, h_pos, transpose_a=True) -
                tf.matmul(v_neg, h_neg, transpose_a=True)
            ) / asfloat(n_samples)

        with tf.name_scope('hidden-bias-update'):
            h_bias_update = tf.reduce_mean(h_pos - h_neg, axis=0)

        with tf.name_scope('visible-bias-update'):
            v_bias_update = tf.reduce_mean(v_pos - v_neg, axis=0)

        with tf.name_scope('flipped-input-features'):
            # Each row will have random feature marked with number 1
            # Other values will be equal to 0
            possible_feature_corruptions = tf.eye(self.n_visible)
            corrupted_features = random_sample(
                possible_feature_corruptions, n_samples)

            rounded_input = tf.round(network_input)
            # If we scale input values from [0, 1] range to [-1, 1]
            # than it will be easier to flip feature values with simple
            # multiplication.
            scaled_rounded_input = 2 * rounded_input - 1
            scaled_flipped_rounded_input = (
                # for corrupted_features we convert 0 to 1 and 1 to -1
                # in this way after multiplication we will flip all
                # signs where -1 in the transformed corrupted_features
                (-2 * corrupted_features + 1) * scaled_rounded_input
            )
            # Scale it back to the [0, 1] range
            flipped_rounded_input = (scaled_flipped_rounded_input + 1) / 2

        with tf.name_scope('pseudo-likelihood-loss'):
            # Stochastic pseudo-likelihood
            error = tf.reduce_mean(
                self.n_visible * tf.log_sigmoid(
                    free_energy(flipped_rounded_input) -
                    free_energy(rounded_input)
                )
            )

        with tf.name_scope('gibbs-sampling'):
            gibbs_sampling = sample_visible_from_hidden(
                sample_hidden_from_visible(network_input))

        initialize_uninitialized_variables()
        self.methods.update(
            train_epoch=function(
                [network_input],
                error,
                name='rbm/train-epoch',
                updates=[
                    (weight, weight + step * weight_update),
                    (h_bias, h_bias + step * h_bias_update),
                    (v_bias, v_bias + step * v_bias_update),
                    (h_samples, random_binomial(p=h_neg)),
                ]
            ),
            prediction_error=function(
                [network_input],
                error,
                name='rbm/prediction-error',
            ),
            diff1=function(
                [network_input],
                free_energy(flipped_rounded_input),
                name='rbm/diff1-error',
            ),
            diff2=function(
                [network_input],
                free_energy(rounded_input),
                name='rbm/diff2-error',
            ),
            visible_to_hidden=function(
                [network_input],
                visible_to_hidden(network_input),
                name='rbm/visible-to-hidden',
            ),
            hidden_to_visible=function(
                [network_hidden_input],
                hidden_to_visible(network_hidden_input),
                name='rbm/hidden-to-visible',
            ),
            gibbs_sampling=function(
                [network_input],
                gibbs_sampling,
                name='rbm/gibbs-sampling',
            )
        )

    def train(self, input_train, input_test=None, epochs=100,
              summary='table'):
        """
        Train RBM.

        Parameters
        ----------
        input_train : 1D or 2D array-like
        input_test : 1D or 2D array-like or None
            Defaults to ``None``.
        epochs : int
            Number of training epochs. Defaults to ``100``.
        summary : {'table', 'inline'}
            Training summary type. Defaults to ``'table'``.
        """
        return super(RBM, self).train(
            input_train=input_train, target_train=None,
            input_test=input_test, target_test=None,
            epochs=epochs, epsilon=None, summary=summary
        )

    def train_epoch(self, input_train, target_train=None):
        """
        Train one epoch.

        Parameters
        ----------
        input_train : array-like (n_samples, n_features)

        Returns
        -------
        float
        """
        errors = self.apply_batches(
            function=self.methods.train_epoch,
            input_data=input_train,

            description='Training batches',
            show_error_output=True,
        )

        n_samples = len(input_train)
        return average_batch_errors(errors, n_samples, self.batch_size)

    def visible_to_hidden(self, visible_input):
        """
        Populates data throught the network and returns output
        from the hidden layer.

        Parameters
        ----------
        visible_input : array-like (n_samples, n_visible_features)

        Returns
        -------
        array-like
        """
        is_input_feature1d = (self.n_visible == 1)
        visible_input = format_data(visible_input, is_input_feature1d)

        outputs = self.apply_batches(
            function=self.methods.visible_to_hidden,
            input_data=visible_input,

            description='Hidden from visible batches',
            show_progressbar=True,
            show_error_output=False,
            scalar_output=False,
        )
        return np.concatenate(outputs, axis=0)

    def hidden_to_visible(self, hidden_input):
        """
        Propagates output from the hidden layer backward
        to the visible.

        Parameters
        ----------
        hidden_input : array-like (n_samples, n_hidden_features)

        Returns
        -------
        array-like
        """
        is_input_feature1d = (self.n_hidden == 1)
        hidden_input = format_data(hidden_input, is_input_feature1d)

        outputs = self.apply_batches(
            function=self.methods.hidden_to_visible,
            input_data=hidden_input,

            description='Visible from hidden batches',
            show_progressbar=True,
            show_error_output=False,
            scalar_output=False,
        )
        return np.concatenate(outputs, axis=0)

    def prediction_error(self, input_data, target_data=None):
        """
        Compute the pseudo-likelihood of input samples.

        Parameters
        ----------
        input_data : array-like
            Values of the visible layer

        Returns
        -------
        float
            Value of the pseudo-likelihood.
        """
        is_input_feature1d = (self.n_visible == 1)
        input_data = format_data(input_data, is_input_feature1d)

        errors = self.apply_batches(
            function=self.methods.prediction_error,
            input_data=input_data,

            description='Validation batches',
            show_error_output=True,
        )
        return average_batch_errors(
            errors,
            n_samples=len(input_data),
            batch_size=self.batch_size,
        )

    def gibbs_sampling(self, visible_input, n_iter=1):
        """
        Makes Gibbs sampling n times using visible input.

        Parameters
        ----------
        visible_input : 1d or 2d array
        n_iter : int
            Number of Gibbs sampling iterations. Defaults to ``1``.

        Returns
        -------
        array-like
            Output from the visible units after perfoming n
            Gibbs samples. Array will contain only binary
            units (0 and 1).
        """
        is_input_feature1d = (self.n_visible == 1)
        visible_input = format_data(visible_input, is_input_feature1d)

        gibbs_sampling = self.methods.gibbs_sampling

        input_ = visible_input
        for iteration in range(n_iter):
            input_ = gibbs_sampling(input_)

        return input_
