# %% Imports


import torch
import numpy as np
import matplotlib.pyplot as plt
from tqdm import trange, tqdm
from src.training.models_adiabatic import Energy_XXZX, Energy_reduction_XXZX
from src.qutip_lab.qutip_class import SpinOperator, SpinHamiltonian, SteadyStateSolver

from src.tddft_methods.kohm_sham_utils import (
    nonlinear_master_equation_step,
    compute_the_gradient,
)
from src.gradient_descent import GradientDescentKohmSham, GradientDescent
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
    def __init__(
        self, h_i: np.array, h_f: np.array, rate: float, idx: int, direction: int
    ) -> None:
        self.hi = h_i
        self.hf = h_f
        self.rate = rate
        self.idx: int = idx
        self.direction = direction

    def field(self, t: float, args):
        return (
            self.hi[self.direction, self.idx] * np.exp(-t * self.rate)
            + (1 - np.exp(-t * self.rate)) * self.hf[self.direction, self.idx]
        )

    def get_the_field(self, t: np.ndarray):
        return (
            self.hi[None, self.direction, :] * np.exp(-t[:, None] * self.rate)
            + (1 - np.exp(-t[:, None] * self.rate)) * self.hf[None, self.direction, :]
        )


class PeriodicDriving:
    def __init__(
        self, h_i: np.array, delta: np.array, rate: float, idx: int, direction: int
    ) -> None:
        self.hi = h_i
        self.delta = delta
        self.rate = rate
        self.idx: int = idx
        self.direction = direction

    def field(self, t: float, args):
        return self.hi[self.direction, self.idx] + (
            self.delta[self.direction, self.idx]
        ) * np.sin(self.rate * t)

    def get_the_field(self, t: np.ndarray):
        return (
            self.hi[None, self.direction, :]
            + (self.delta[None, self.direction, :]) * np.sin(self.rate * t)[:, None]
        )


# %% Data
data = np.load(
    "data/kohm_sham_approach/disorder/zzxyz_model/train_dataset_zzxyz_range_0.0_5.0_j_1_1nn_n_800000_l_8.npz"
)


z = data["density"]

print(z.shape)

l = z.shape[-1]

model = torch.load(
    "model_rep/kohm_sham/disorder/zzxyz_model/model_zzxyz_dataset_fields_0.0_5.0_j_1_1nn_n_800k_unet_l_train_8_[60, 60, 60, 60, 60, 60]_hc_5_ks_1_ps_6_nconv_0_nblock",
    map_location="cpu",
)
model.eval()
model = model.to(dtype=torch.double)
energy = Energy_XXZX(model=model)
energy.eval()
# Implement the Kohm Sham LOOP
z_target = torch.from_numpy(z).double()

# initialization
exponent_algorithm = True
self_consistent_step = 1
eta = 0.1
steps = 2000
tf = 20.0
time = torch.linspace(0.0, tf, steps)
dt = time[1] - time[0]

ndata = 10
rates = np.linspace(0.0, 0.2, ndata)

rates = np.array([0.0, 0.01, 0.05, 0.1, 0.5, 1, 1.5])
rates = np.array([0.1])
ndata = rates.shape[0]


h_tot = np.zeros((ndata, steps, 3, l))
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
gradients_tot = np.zeros((ndata, steps, 3, l))
m_qutip_tot = np.append(
    z_qutip_tot.reshape(ndata, steps, 1, l),
    x_qutip_tot.reshape(ndata, steps, 1, l),
    axis=-2,
)

# is the driving periodic?
periodic = False

# define the initial external field
# zz x quench style (?)
hi = torch.ones((3, l))
hi[0] = 2  # high transverse field
hi[1] = 1.0
hi[2] = 1.0
# define the final external field
hf = torch.ones((3, l))
hf[0] = 1.0
hf[1] = 1.0
hf[2] = 1.0


# define the delta for the periodic driving
delta = torch.ones((3, l))
delta[0] = 0.5
delta[1] = 0.9
delta[2] = 0.0


# %% Compute the initial ground state configuration
print("initial configuration=", torch.mean(z_target, dim=0))

gd = GradientDescentKohmSham(
    loglr=-2,
    energy=energy,
    epochs=4000,
    seed=23,
    num_threads=3,
    device="cpu",
    n_init=torch.mean(z_target, dim=0),
    h=hi,
)


zi = gd.run()


zi = torch.from_numpy(zi)[0]


for q, rate in enumerate(rates):
    # Qutip Dynamics
    # Hamiltonian
    ham0 = SpinHamiltonian(
        direction_couplings=[("z", "z")],
        pbc=True,
        coupling_values=[1.0],
        size=l,
    )

    hamExtX = SpinOperator(
        index=[("x", i) for i in range(l)], coupling=hi[0].detach().numpy(), size=l
    )
    hamExtZ = SpinOperator(
        index=[("z", i) for i in range(l)], coupling=hi[2].detach().numpy(), size=l
    )
    hamExtY = SpinOperator(
        index=[("y", i) for i in range(l)], coupling=hi[1].detach().numpy(), size=l
    )

    eng, psi0 = np.linalg.eigh(
        ham0.qutip_op + hamExtZ.qutip_op + hamExtY.qutip_op + hamExtX.qutip_op
    )
    psi0 = qutip.Qobj(psi0[:, 0], shape=psi0.shape, dims=([[2 for i in range(l)], [1]]))

    print("real ground state energy=", eng[0])

    obs: List[qutip.Qobj] = []
    obs_x: List[qutip.Qobj] = []
    obs_y: List[qutip.Qobj] = []
    for i in range(l):
        z_op = SpinOperator(index=[("z", i)], coupling=[1.0], size=l, verbose=1)
        x_op = SpinOperator(index=[("x", i)], coupling=[1.0], size=l, verbose=0)
        y_op = SpinOperator(index=[("y", i)], coupling=[1.0], size=l, verbose=0)

        print(x_op.expect_value(psi=psi0) - zi[0, i].detach().numpy())
        print(y_op.expect_value(psi=psi0) - zi[1, i].detach().numpy())
        print(z_op.expect_value(psi=psi0) - zi[2, i].detach().numpy())

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
                direction=2,
            )
        else:
            drive_z = Driving(
                h_i=hi.detach().numpy(),
                h_f=hf.detach().numpy(),
                rate=rate,
                idx=i,
                direction=2,
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
                direction=0,
            )
        else:
            drive_x = Driving(
                h_i=hi.detach().numpy(),
                h_f=hf.detach().numpy(),
                rate=rate,
                idx=i,
                direction=0,
            )
        hamiltonian.append([obs_x[i], drive_x.field])
    h_x = drive_x.get_the_field(time.detach().numpy()).reshape(time.shape[0], 1, -1)

    for i in range(l):
        if periodic:
            drive_y = PeriodicDriving(
                h_i=hi.detach().numpy(),
                delta=delta.detach().numpy(),
                rate=rate,
                idx=i,
                direction=1,
            )
        else:
            drive_y = Driving(
                h_i=hi.detach().numpy(),
                h_f=hf.detach().numpy(),
                rate=rate,
                idx=i,
                direction=1,
            )
        hamiltonian.append([obs_y[i], drive_y.field])
    h_y = drive_y.get_the_field(time.detach().numpy()).reshape(time.shape[0], 1, -1)

    h = np.concatenate((h_x, h_y, h_z), axis=1)
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

    # psi = initialize_psi_from_xyz(z=-1 * zi[0], x=zi[1], y=torch.zeros_like(zi[1]))
    #  Kohm Sham step 1) Initialize the state from an initial magnetization
    psi = torch.zeros((3, l))
    psi[0, :] = zi[0].double()
    psi[1, :] = zi[1].double()
    psi[2, :] = zi[2].double()

    a, _ = compute_the_gradient(
        m=(psi).unsqueeze(0),
        h=h[0],
        energy=energy,
        respect_to="x",
    )

    print("gradient check", a.shape, a)

    # psi[:, 0] = torch.from_numpy(x_qutip_tot[q, 0]).double()
    # psi[:, 1] = torch.from_numpy(y_qutip_tot[q, 0]).double()
    # psi[:, 2] = torch.from_numpy(z_qutip_tot[q, 0]).double()

    t_bar = tqdm(enumerate(time))
    for i in trange(time.shape[0] - 1):
        t = time[i]
        #  Kohm Sham step 2) Build up the fields
        psi, engx, engz, omega_eff, delta_eff, h_eff = nonlinear_master_equation_step(
            psi,
            energy=energy,
            i=i,
            h=h,
            self_consistent_step=self_consistent_step,
            dt=dt,
            eta=eta,
        )

        eng_tot_z[q, i] = engz
        eng_tot_x[q, i] = engx

        z_tot[q, i, :] = psi[2, :].double().detach().numpy()
        x_tot[q, i, :] = psi[0, :].double().detach().numpy()
        y_tot[q, i, :] = psi[1, :].double().detach().numpy()
        gradients_tot[q, i, 0, :] = -1 * omega_eff[0].detach().numpy()
        gradients_tot[q, i, 2, :] = -1 * h_eff[0].detach().numpy()
        gradients_tot[q, i, 1, :] = -1 * delta_eff[0].detach().numpy()

        if periodic:
            np.savez(
                f"data/kohm_sham_approach/results/master_equation/tddft_periodic_uniform_zzxxzx_model_h_0_5_omega_0_2_ti_0_tf_{tf:.0f}_hi_{hi[0,0].item():.4f}_delta_{delta[0,0].item():.4f}_omegai_{hi[1,0].item():.1f}_delta_{delta[1,0].item():.1f}_steps_{steps}_self_consistent_steps_{self_consistent_step}_ndata_{ndata}_exp_{exponent_algorithm}",
                x_qutip=x_qutip_tot,
                z_qutip=z_qutip_tot,
                y_qutip=y_qutip_tot,
                z=z_tot,
                x=x_tot,
                y=y_tot,
                potential=h_tot,
                energy_x=eng_tot_x,
                energy_z=eng_tot_z,
                energy=eng_tot,
                energy_qutip=eng_qutip_tot,
                gradient=gradients_tot,
                rates=rates,
            )

        else:
            np.savez(
                f"data/kohm_sham_approach/results/master_equation/tddft_quench_uniform_model_zzxyz_h_0_2_omega_0_2_ti_0_tf_{tf:.0f}_hi_{hi[0,0].item():.4f}_hf_{hf[0,0].item():.4f}_omegai_{hi[1,0].item():.1f}_omegaf_{hf[1,0].item():.1f}_steps_{steps}_self_consistent_steps_{self_consistent_step}_ndata_{ndata}_exp_{exponent_algorithm}",
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
                time=time[:i],
                rates=rates,
            )
