from neupy import layers, plots


def ConvReluBN(*conv_args, **conv_kwargs):
    return layers.join(
        layers.Convolution(*conv_args, **conv_kwargs),
        layers.Relu(),
        layers.BatchNorm(epsilon=0.001),
    )


def Inception_1(conv_filters):
    return layers.join(
        [[
            ConvReluBN((1, 1, conv_filters[0][0])),
        ], [
            ConvReluBN((1, 1, conv_filters[1][0])),
            ConvReluBN((5, 5, conv_filters[1][1]), padding=2),
        ], [
            ConvReluBN((1, 1, conv_filters[2][0])),
            ConvReluBN((3, 3, conv_filters[2][1]), padding=1),
            ConvReluBN((3, 3, conv_filters[2][2]), padding=1),
        ], [
            layers.AveragePooling((3, 3), stride=(1, 1), padding='SAME'),
            ConvReluBN((1, 1, conv_filters[3][0])),
        ]],
        layers.Concatenate(),
    )


def Inception_2(conv_filters):
    return layers.join(
        [[
            ConvReluBN((1, 1, conv_filters[0][0])),
        ], [
            ConvReluBN((1, 1, conv_filters[1][0])),
            ConvReluBN((1, 7, conv_filters[1][1]), padding=(0, 3)),
            ConvReluBN((7, 1, conv_filters[1][2]), padding=(3, 0)),
        ], [
            ConvReluBN((1, 1, conv_filters[2][0])),
            ConvReluBN((7, 1, conv_filters[2][1]), padding=(3, 0)),
            ConvReluBN((1, 7, conv_filters[2][2]), padding=(0, 3)),
            ConvReluBN((7, 1, conv_filters[2][3]), padding=(3, 0)),
            ConvReluBN((1, 7, conv_filters[2][4]), padding=(0, 3)),
        ], [
            layers.AveragePooling((3, 3), stride=(1, 1), padding='SAME'),
            ConvReluBN((1, 1, conv_filters[3][0])),
        ]],
        layers.Concatenate(),
    )


def Inception_3(pooling):
    if pooling not in ('max', 'average'):
        raise ValueError("Invalid pooling option: {}".format(pooling))

    elif pooling == 'max':
        Pooling = layers.MaxPooling

    elif pooling == 'average':
        Pooling = layers.AveragePooling

    return layers.join(
        [[
            ConvReluBN((1, 1, 320)),
        ], [
            ConvReluBN((1, 1, 384)),
            [[
                ConvReluBN((1, 3, 384), padding=(0, 1)),
            ], [
                ConvReluBN((3, 1, 384), padding=(1, 0)),
            ]],
        ], [
            ConvReluBN((1, 1, 448)),
            ConvReluBN((3, 3, 384), padding=1),
            [[
                ConvReluBN((1, 3, 384), padding=(0, 1)),
            ], [
                ConvReluBN((3, 1, 384), padding=(1, 0)),
            ]],
        ], [
            Pooling((3, 3), stride=(1, 1), padding='SAME'),
            ConvReluBN((1, 1, 192)),
        ]],
        layers.Concatenate(),
    )


inception_v3 = layers.join(
    layers.Input((299, 299, 3)),

    ConvReluBN((3, 3, 32), stride=2),
    ConvReluBN((3, 3, 32)),
    ConvReluBN((3, 3, 64), padding=1),
    layers.MaxPooling((3, 3), stride=(2, 2)),

    ConvReluBN((1, 1, 80)),
    ConvReluBN((3, 3, 192)),
    layers.MaxPooling((3, 3), stride=(2, 2)),

    Inception_1([[64], [48, 64], [64, 96, 96], [32]]),
    Inception_1([[64], [48, 64], [64, 96, 96], [64]]),
    Inception_1([[64], [48, 64], [64, 96, 96], [64]]),

    [[
        ConvReluBN((3, 3, 384), stride=2),
    ], [
        ConvReluBN((1, 1, 64)),
        ConvReluBN((3, 3, 96), padding=1),
        ConvReluBN((3, 3, 96), stride=2),
    ], [
        layers.MaxPooling((3, 3), stride=(2, 2))
    ]],
    layers.Concatenate(),

    Inception_2([[192], [128, 128, 192], [128, 128, 128, 128, 192], [192]]),
    Inception_2([[192], [160, 160, 192], [160, 160, 160, 160, 192], [192]]),
    Inception_2([[192], [160, 160, 192], [160, 160, 160, 160, 192], [192]]),
    Inception_2([[192], [192, 192, 192], [192, 192, 192, 192, 192], [192]]),

    [[
        ConvReluBN((1, 1, 192)),
        ConvReluBN((3, 3, 320), stride=2),
    ], [
        ConvReluBN((1, 1, 192)),
        ConvReluBN((1, 7, 192), padding=(0, 3)),
        ConvReluBN((7, 1, 192), padding=(3, 0)),
        ConvReluBN((3, 3, 192), stride=2),
    ], [
        layers.MaxPooling((3, 3), stride=(2, 2))
    ]],
    layers.Concatenate(),

    Inception_3(pooling='average'),
    Inception_3(pooling='max'),

    layers.GlobalPooling('avg'),
    layers.Softmax(1000),
)
plots.layer_structure(inception_v3)
