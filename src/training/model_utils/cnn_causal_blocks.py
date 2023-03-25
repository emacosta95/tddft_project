import torch
import torch.nn as nn
from torch.nn import functional as F
from torch.nn.modules.utils import _pair


class MaskedConv2d(nn.Conv2d):
    def __init__(self, *args, **kwargs) -> None:
        # remove mask_type kwargs
        self.mask_type = kwargs.pop("mask_type")
        super(MaskedConv2d, self).__init__(*args, **kwargs)

        _, _, kh, kw = self.weight.shape
        self.register_buffer("mask", torch.ones([kh, kw]))
        # self.mask[kh // 2, kw // 2 + 1 :] = 0
        # type_mask=A excludes the central pixel
        if self.mask_type == "A":
            self.mask[kh // 2, kw // 2] = 0
        self.mask[kh // 2 + 1 :] = 0
        self.weight.data *= self.mask

        print(self.mask)

        # Correction to Xavier initialization
        self.weight.data *= torch.sqrt(self.mask.numel() / self.mask.sum())

    def forward(self, x):
        return F.conv2d(
            x,
            self.mask * self.weight,
            self.bias,
            self.stride,
            self.padding,
            self.dilation,
            self.groups,
        )

    def extra_repr(self):
        return super(
            MaskedConv2d, self
        ).extra_repr() + ", mask_type={mask_type}".format(**self.__dict__)


class MaskedTimeConv2d(nn.Conv2d):
    def __init__(self, *args, **kwargs) -> None:
        # remove mask_type kwargs
        # self.mask_type = kwargs.pop("mask_type")

        super(MaskedTimeConv2d, self).__init__(*args, **kwargs)
        kernel_size = _pair(self.kernel_size)
        stride = _pair(self.stride)
        dilation = _pair(self.dilation)
        padding = [
            int((kernel_size[0] - 1) * dilation[0]),
            int((kernel_size[1] - 1) * dilation[1]) // 2,
        ]
        padding = _pair(padding)
        self.left_padding = padding[0]
        self.up_padding = padding[1]
        self.padding_mode = "zeros"

        _, _, kh, kw = self.weight.shape
        self.register_buffer("mask", torch.ones([kh, kw]))
        # self.mask[kh // 2, kw // 2 + 1 :] = 0
        # type_mask=A excludes the central pixel
        self.mask[kh - 1, kw - 1] = 0
        self.weight.data *= self.mask

        print(self.mask)

        # Correction to Xavier initialization
        self.weight.data *= torch.sqrt(self.mask.numel() / self.mask.sum())

    def forward(self, x):
        x = F.pad(
            x,
            (
                self.up_padding,
                self.up_padding,
                self.left_padding,
                0,
            ),
        )  # asymmetric in time, zero padding
        # print("new inputs->,", inputs.shape)
        return F.conv2d(
            x,
            weight=self.mask * self.weight,
            bias=self.bias,
            stride=self.stride,
            padding=0,
            dilation=self.dilation,
        )


class CausalConv2d(nn.Conv2d):
    def __init__(
        self,
        in_channels,
        out_channels,
        kernel_size,
        stride=1,
        padding=None,
        padding_mode="zeros",
        dilation=1,
        groups=1,
        bias=True,
    ):
        kernel_size = _pair(kernel_size)
        stride = _pair(stride)
        dilation = _pair(dilation)
        if padding is None:
            padding = [
                int((kernel_size[0] - 1) * dilation[0]),
                int((kernel_size[1] - 1) * dilation[1] / 2),
            ]
        else:
            padding = _pair(padding)
        self.left_padding = padding[0]
        self.up_padding = padding[1]
        self.padding_mode = padding_mode
        super().__init__(
            in_channels=in_channels,
            out_channels=out_channels,
            kernel_size=kernel_size,
            stride=stride,
            padding=0,
            dilation=dilation,
            groups=groups,
            bias=bias,
        )

    def forward(self, inputs):
        # print(inputs.shape)
        inputs = F.pad(
            inputs, (0, 0, self.left_padding, 0)
        )  # asymmetric in time, zero padding
        # print("new inputs->,", inputs.shape)
        inputs = F.pad(
            inputs, (self.up_padding, self.up_padding, 0, 0), mode="circular"
        )  # symmetric in space, pbc padding
        # print(inputs.shape)
        output = super().forward(inputs)
        return output
