# %%
import torch
import numpy as np
import matplotlib.pyplot as plt
import torch
import numpy as np
import matplotlib.pyplot as plt
from tqdm import trange, tqdm
from src.training.models_adiabatic import EnergyReductionXXZ
from src.qutip_lab.qutip_class import SpinOperator, SpinHamiltonian, SteadyStateSolver
from src.tddft_methods.kohm_sham_utils import (
    initialize_psi_from_z,
    nonlinear_schrodinger_step_zzx_model_full_effective_field,
    get_effective_field,
)
from src.gradient_descent import GradientDescentKohmSham
import qutip
from typing import List
import os


class Driving:
    def __init__(self, h: np.array, idx: int, dt: float) -> None:
        self.h = h
        # self.tf=tf
        self.idx: int = idx
        self.dt: float = dt

    def field(self, t: float, args):

        if int(t / self.dt) == self.h.shape[0]:
            return self.h[-1, self.idx]
        else:
            return self.h[int(t / self.dt), self.idx]

    def get_the_field(
        self,
    ):
        return self.h


index_level = -1

model = torch.load(
    "model_rep/kohm_sham/cnn_field2field/TDDFTCNN_field2field_periodic_time_steps_100_tf_30_240227_periodic_dataset_[80, 80, 80, 80]_hc_[5, 15]_ks_1_ps_4_nconv_1_nblock",
    map_location="cpu",
)

model.eval()


data = np.load(
    "data/dataset_h_eff/periodic/dataset_periodic_nbatch_10_batchsize_500_steps_200_tf_20.0_l_8_240227.npz"
)

h = data["h"]

l=h.shape[-1]
steps = 200
tf = 20.0
time = np.linspace(0.0, tf, steps)
dt = time[1] - time[0]
gamma=1.

# hi = np.random.uniform(1.0, 2.0, size=5)[:, None] * np.ones(l)[None, :]
# hf = np.random.uniform(0.0, 1.0, size=5) * np.ones(l)[None, :]

# h = (
#     hi[None, :,None] * np.exp(-1 * gamma * time[None, :, None])
#     + (1 - np.exp(-1 * gamma * time[None, :, None])) * hf[None, :,None]
# )

h_test = np.einsum("ati->ait", h)

z_exact = data["z"]

density = data["h"][:, :]

density[:, index_level:] = 0.0

plt.plot(density[-1, :, 0])
plt.show()

print(density.shape)
density = np.einsum("ati->ait", density)


h_eff_exact = data["h_eff"][:, 1:]
h_eff_test = np.einsum("ati->ait", h_eff_exact)


density_torch = torch.tensor(density)
h_eff_torch = torch.tensor(h_eff_test)

idx_batch = 5
batch_size = 50
print(idx_batch * batch_size, (idx_batch + 1) * batch_size)
x = density_torch[idx_batch * batch_size : (idx_batch + 1) * batch_size]

y = h_eff_torch[idx_batch * batch_size : (idx_batch + 1) * batch_size]


print(x.shape)
y_hat = model(x.double()).squeeze()
print(y_hat.shape)


h_eff_hat = np.einsum("qit->qti", y_hat.detach().numpy())
for i in range(2):
    for j in range(y.shape[1]):
        fig, ax = plt.subplots(figsize=(10, 10))

        ax.plot(
            y_hat.detach().numpy()[i, j, :index_level],
            color="red",
            linestyle="--",
            linewidth=3,
            label="model",
        )
        ax.plot(
            y.detach().numpy()[i, j, :index_level],
            color="green",
            linewidth=3,
            label="exact",
        )
        ax_twin = ax.twinx()
        ax.set_ylabel(r"$h_{i,eff}(t)$", fontsize=40)
        ax_twin.plot(
            density[i, j, :index_level], color="black", linewidth=3, linestyle="--"
        )
        ax_twin.set_ylabel(r"$z_i(t)$", fontsize=40)
        ax.set_xlabel(r"$t[1/J]$", fontsize=40)
        ax.legend(fontsize=40)
        ax.tick_params(labelsize=20)
        ax_twin.tick_params(labelsize=20)
        plt.show()


# %%
l = 8



model.eval()


# initialization
exponent_algorithm = True
self_consistent_step = 0
nbatch = 1

l = 8
rate = 0.2

min_range_driving = 0.01
max_range_driving = 1.0

shift = 0.5

steps = 1000
tf = 30.0
time = np.linspace(0.0, tf, steps)
dt = time[1] - time[0]
print(dt)


ham0 = SpinOperator(index=[("x", i) for i in range(1)], coupling=[1] * 1, size=1)


# %% Compute the initial ground state configuration


for q in range(1):

    for idx in range(l):

        psi0 = np.zeros(2)
        psi0[0] = np.sqrt((1 + z_exact[idx_batch * batch_size + q, 0, idx]) / 2)
        psi0[1] = np.sqrt((1 - z_exact[idx_batch * batch_size + q, 0, idx]) / 2)
        psi0 = qutip.Qobj(
            psi0[:], shape=psi0.shape, dims=([[2 for i in range(1)], [1]])
        )

        # to check if we have the same outcome with the Crank-Nicholson algorithm
        # psi = initialize_psi_from_z_and_x(z=-1 * zi[0], x=zi[1])
        # psi = psi.detach().numpy()
        # for i in range(l):
        #     psi_l = qutip.Qobj(psi[i], shape=psi[i].shape, dims=([[2], [1]]))
        #     if i == 0:
        #         psi0 = psi_l
        #     else:
        #         psi0 = qutip.tensor(psi0, psi_l)
        # compute and check the magnetizations
        obs: List[qutip.Qobj] = []
        obs_x: List[qutip.Qobj] = []
        # for i in range(l):
        #     z_op = SpinOperator(index=[("z", i)], coupling=[1.0], size=l, verbose=1)
        #     # print(f"x[{i}]=", x.qutip_op, "\n")
        #     x_op = SpinOperator(index=[("x", i)], coupling=[1.0], size=l, verbose=0)
        #     obs.append(z_op.qutip_op)
        #     obs_x.append(x_op.qutip_op)

        obs = [
            SpinOperator(
                index=[("z", i) for i in range(1)], coupling=[1] * 1, size=1
            ).qutip_op
        ]

        print(obs[0])

        print("\n INITIALIZE THE HAMILTONIAN \n")
        # build up the time dependent object for the qutip evolution
        hamiltonian = [ham0.qutip_op]

        for i in range(1):
            drive_z = Driving(
                h=(
                    h_eff_hat[q, :, idx] + h[idx_batch * batch_size + q, :, idx]
                ).reshape(-1, 1),
                idx=i,
                dt=time[1] - time[0],
            )

            hamiltonian.append([obs[i], drive_z.field])

        # evolution

        output = qutip.sesolve(hamiltonian, psi0, time)

        psi_t = output.states
        psi_t = np.asarray(psi_t)
        print(psi_t.shape)
        z_eff = np.einsum(
            "ta,ab,tb->t",
            np.conj(psi_t)[:, :, 0],
            SpinOperator(
                index=[("z", i) for i in range(1)], coupling=[1], size=1
            ).qutip_op,
            psi_t[:, :, 0],
        )

        print(z_eff.shape)
        print(z_exact.shape)
        plt.plot(z_eff)
        plt.plot(z_exact[idx_batch * batch_size + q, :, idx])
        plt.show()

        plt.plot(h_eff_exact[idx_batch * batch_size + q, :, idx])
        plt.plot(h_eff_hat[q, :, idx])
        plt.show()

# %%
import numpy as np
data=np.load('data/dataset_h_eff/periodic/dataset_periodic_nbatch_100_batchsize_1000_steps_100_tf_30.0_l_8_240226.npz')

density=data['z']
print('density shape=',density.shape)
density=np.einsum('bti->bit',density)


potential=data['h_eff']
potential=np.einsum('bti->bit',potential)

h=data['h']
h=np.einsum('bti->bit',h)


print(density.shape)
np.savez('data/dataset_h_eff/train_dataset_periodic_driving_ndata_100000_steps_100_240226.npz',potential=potential,density=density,h=h)


# %%
import numpy as np
data=np.load('data/dataset_h_eff/reconstruction_dataset/reconstruction_dataset_quench_nbatch_10_batchsize_100_steps_1000_tf_30.0_l_8.npz')

z=data['z']

z_exact=data['z_exact']

h=data['h']

h_eff=data['h_eff']

h_eff_exact=data['h_eff_exact']

h_eff_reconstruction=data['h_eff_reconstruction']

print(h_eff.shape)
#%%
import matplotlib.pyplot as plt
idx=1

for i in range(h.shape[-1]):
    plt.plot(h_eff[idx,:-1,i])
    plt.plot(h_eff_exact[idx,:,i])
    plt.plot(h_eff_reconstruction[idx,:,i],label='h_eff recon')
    plt.legend()
    plt.show()


# %%
for i in range(h.shape[-1]):
    plt.plot(z[idx,:,i])
    plt.plot(z_exact[idx,:,i])

    plt.legend()
    plt.show()

# %%