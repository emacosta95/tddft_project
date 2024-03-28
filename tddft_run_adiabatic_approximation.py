# %% Imports


import torch
import numpy as np
import matplotlib.pyplot as plt
from tqdm import trange, tqdm
from src.training.models_adiabatic import EnergyReductionXXZXRespect2X
from src.qutip_lab.qutip_class import SpinOperator, SpinHamiltonian, SteadyStateSolver

from src.tddft_methods.kohm_sham_utils import (
    initialize_psi_from_z,
    nonlinear_schrodinger_step_zzxz_model,
    compute_the_gradient_of_the_functional_ux_model,
)
from src.gradient_descent import GradientDescentKohmSham
import qutip
from typing import List
import os


### SET NUM THREADS
# os.environ["OMP_NUM_THREADS"] = "3"
# os.environ["NUMEXPR_NUM_THREADS"] = "3"
# os.environ["MKL_NUM_THREADS"] = "3"
# torch.set_num_threads(3)


# %% Qutip details
class Driving:
    def __init__(self, h_i: np.array, h_f: np.array, rate: float, idx: int) -> None:
        self.hi = h_i
        self.hf = h_f
        self.rate = rate
        self.idx: int = idx

    def field(self, t: float, args):
        return (
            self.hi[self.idx] * np.exp(-t * self.rate)
            + (1 - np.exp(-t * self.rate)) * self.hf[self.idx]
        )

    def get_the_field(self, t: np.ndarray):
        return (
            self.hi[None, :] * np.exp(-t[:, None] * self.rate)
            + (1 - np.exp(-t[:, None] * self.rate)) * self.hf[None, :]
        )


class PeriodicDriving:
    def __init__(self, h_i: np.array, delta: np.array, rate: float, idx: int) -> None:
        self.hi = h_i
        self.delta = delta
        self.rate = rate
        self.idx: int = idx

    def field(self, t: float, args):
        return self.hi[self.idx] + (self.delta[self.idx]) * np.sin(self.rate * t)

    def get_the_field(self, t: np.ndarray):
        return self.hi[None, :] + (self.delta[None, :]) * np.sin(self.rate * t)[:, None]


# %% Data


data = np.load(
    "data/kohm_sham_approach/disorder/zzx_model/train_dataset_reduced_zzx_model_8_l_5.0_h_800000_n.npz.npz"
)


z = data["density"]

print(z.shape)

l = z.shape[-1]


model = torch.load(
    "model_rep/kohm_sham/disorder/zzxz_model/single_input/model_231111_xxzx_fields_0.0_5.0_j_1_1nn_n_1m_unet_l_train_8_[60, 60, 60, 60, 60, 60]_hc_5_ks_1_ps_6_nconv_0_nblock",
    map_location="cpu",
)
model.eval()
model = model.to(dtype=torch.double)
energy = EnergyReductionXXZXRespect2X(model=model)
energy.eval()
# Implement the Kohm Sham LOOP

# initialization
exponent_algorithm = True
self_consistent_step = 1
eta = 0.1
steps = 5000
tf = 50.0
time = torch.linspace(0.0, tf, steps)
dt = time[1] - time[0]
z_target = torch.from_numpy(z).double()
ndata = 10
rates = np.linspace(0.0, 0.2, ndata)

rates = np.array([0.0, 0.1, 0.5, 1, 1.5])
# rates = np.array([0.1])
ndata = rates.shape[0]


h_tot = np.zeros((ndata, steps, 2, l))
z_qutip_tot = np.zeros((ndata, steps, l))
z_tot = np.zeros((ndata, steps, l))
x_qutip_tot = np.zeros((ndata, steps, l))
y_qutip_tot = np.zeros((ndata, steps, l))


x_tot = np.zeros((ndata, steps, l))
y_tot = np.zeros((ndata, steps, l))
eng_tot_z = np.zeros((ndata, steps))
eng_tot_x = np.zeros((ndata, steps))
eng_tot = np.zeros((ndata, steps))
eng_qutip_tot = np.zeros((ndata, steps))
gradients_tot = np.zeros((ndata, steps, 2, l))
m_qutip_tot = np.append(
    z_qutip_tot.reshape(ndata, steps, 1, l),
    x_qutip_tot.reshape(ndata, steps, 1, l),
    axis=-2,
)

# is the driving periodic?
periodic = False

# define the initial external field
# zz x quench style (?)
hi = torch.ones((2, l))
hi[1] = 1.0  # high transverse field
hi[0] = 2.0
# define the final external field
hf = torch.ones((2, l))
hf[1] = 1.0
hf[0] = 1.0


# define the delta for the periodic driving
delta = torch.ones((2, l))
delta[1] = 0.9
delta[0] = 0.0


# %% Compute the initial ground state configuration
print(hi.shape)

gd = GradientDescentKohmSham(
    loglr=-2,
    energy=energy,
    epochs=1000,
    seed=23,
    num_threads=3,
    device="cpu",
    n_init=-0.9 * torch.ones(l),
    h=hi,
)


zi = gd.run()
zi = torch.from_numpy(zi)[0]

for q, rate in enumerate(rates):
    # Qutip Dynamics
    # Hamiltonian
    ham0 = SpinHamiltonian(
        direction_couplings=[("x", "x")],
        pbc=True,
        coupling_values=[1.0],
        size=l,
    )

    hamExtX = SpinOperator(
        index=[("x", i) for i in range(l)], coupling=hi[1].detach().numpy(), size=l
    )
    hamExtZ = SpinOperator(
        index=[("z", i) for i in range(l)], coupling=hi[0].detach().numpy(), size=l
    )

    eng, psi0 = np.linalg.eigh(ham0.qutip_op + hamExtZ.qutip_op + hamExtX.qutip_op)
    psi0 = qutip.Qobj(psi0[:, 0], shape=psi0.shape, dims=([[2 for i in range(l)], [1]]))

    print("real ground state energy=", eng[0])
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
    obs_y: List[qutip.Qobj] = []
    for i in range(l):
        z_op = SpinOperator(index=[("z", i)], coupling=[1.0], size=l, verbose=1)
        x_op = SpinOperator(index=[("x", i)], coupling=[1.0], size=l, verbose=0)
        y_op = SpinOperator(index=[("y", i)], coupling=[1.0], size=l, verbose=0)

        print(
            z_op.expect_value(psi=psi0) - zi[i].detach().numpy(), zi[i].detach().numpy()
        )

        obs.append(z_op.qutip_op)
        obs_x.append(x_op.qutip_op)
        obs_y.append(y_op.qutip_op)

    print("\n INITIALIZE THE HAMILTONIAN \n")
    # build up the time dependent object for the qutip evolution
    hamiltonian = [ham0.qutip_op]

    print("periodic=", periodic, "\n")
    for i in range(l):
        if periodic:
            drive_z = PeriodicDriving(
                h_i=hi.detach().numpy(),
                delta=delta.detach().numpy(),
                rate=rate,
                idx=i,
                direction=0,
            )
        else:
            drive_z = Driving(
                h_i=hi.detach().numpy(),
                h_f=hf.detach().numpy(),
                rate=rate,
                idx=i,
                direction=0,
            )

        hamiltonian.append([obs[i], drive_z.field])

    h_z = drive_z.get_the_field(time.detach().numpy()).reshape(time.shape[0], 1, -1)
    for i in range(l):
        if periodic:
            drive_x = PeriodicDriving(
                h_i=hi.detach().numpy(),
                delta=delta.detach().numpy(),
                rate=rate,
                idx=i,
                direction=1,
            )
        else:
            drive_x = Driving(
                h_i=hi.detach().numpy(),
                h_f=hf.detach().numpy(),
                rate=rate,
                idx=i,
                direction=1,
            )
        hamiltonian.append([obs_x[i], drive_x.field])
    h_x = drive_x.get_the_field(time.detach().numpy()).reshape(time.shape[0], 1, -1)

    h = np.append(h_z, h_x, axis=1)
    h_tot[q] = h
    h = torch.from_numpy(h)
    print(h.shape)

    # evolution

    output = qutip.sesolve(
        hamiltonian, psi0, time.detach().numpy(), e_ops=obs + obs_x + obs_y
    )

    # %% visualization
    for r in range(l):
        z_qutip_tot[q, :, r] = output.expect[r]
        m_qutip_tot[q, :, 0, r] = output.expect[r]
        x_qutip_tot[q, :, r] = output.expect[l + r]
        m_qutip_tot[q, :, 1, r] = output.expect[l + r]
        y_qutip_tot[q, :, r] = output.expect[2 * l + r]

    #  Kohm Sham step 1) Initialize the state from an initial magnetization
    psi = initialize_psi_from_z(z=-1 * zi)
    # psi = initialize_psi_from_xyz(z=-1 * zi[0], x=zi[1], y=torch.zeros_like(zi[1]))

    t_bar = tqdm(enumerate(time))
    for i in trange(time.shape[0] - 1):
        t = time[i]

        psi, omega_eff, h_eff, z = nonlinear_schrodinger_step_zzxz_model(
            psi=psi,
            model=model,
            i=i,
            h=h,
            self_consistent_step=self_consistent_step,
            dt=dt,
            exponent_algorithm=exponent_algorithm,
        )

        z_tot[q, i, :] = z.detach().numpy()
        gradients_tot[q, i, 1, :] = -1 * omega_eff[0].detach().numpy()
        gradients_tot[q, i, 0, :] = -1 * h_eff[0].detach().numpy()

        if periodic:
            np.savez(
                f"data/kohm_sham_approach/results/tddft_periodic_uniform_zzxxzx_model_h_0_5_omega_0_2_ti_0_tf_{tf:.0f}_hi_{hi[0,0,0].item():.4f}_delta_{delta[0,0].item():.4f}_omegai_{hi[1,0].item():.1f}_delta_{delta[1,0].item():.1f}_steps_{steps}_self_consistent_steps_{self_consistent_step}_ndata_{ndata}_exp_{exponent_algorithm}",
                x_qutip=x_qutip_tot[:, :i],
                z_qutip=z_qutip_tot[:, :i],
                z=z_tot[:, :i],
                x=x_tot[:, :i],
                y=y_tot[:, :i],
                y_qutip=y_qutip_tot[:, :i],
                potential=h_tot[:, :i],
                energy_x=eng_tot_x[:, :i],
                energy_z=eng_tot_z[:, :i],
                energy=eng_tot[:, :i],
                energy_qutip=eng_qutip_tot[:, :i],
                gradient=gradients_tot[:, :i],
                rates=rates,
                time=time[:i],
            )

        else:
            np.savez(
                f"data/kohm_sham_approach/results/dl_functional/zzxz_model/tddft_quench_uniform_model_h_0_2_omega_0_2_ti_0_tf_{tf:.0f}_hi_{hi[0,0].item():.1f}_hf_{hf[0,0].item():.1f}_steps_{steps}_self_consistent_steps_{self_consistent_step}_ndata_{ndata}_exp_{exponent_algorithm}",
                z_qutip=z_qutip_tot[:, :i],
                z=z_tot[:, :i],
                potential=h_tot[:, :i],
                gradient=gradients_tot[:, :i],
                rates=rates,
                time=time[:i],
            )