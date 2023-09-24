import torch
import numpy as np
import matplotlib.pyplot as plt
import torch.nn as nn
from typing import Tuple
from tqdm import trange


def quench_field(
    h_i: torch.Tensor, h_f: torch.Tensor, lambd: float, time: torch.Tensor
):
    h = (
        h_i[None, :, :] * torch.exp(-time[:, None, None] * lambd)
        + (1 - torch.exp(-time[:, None, None] * lambd)) * h_f[None, :, :]
    )
    return h


def compute_the_inverse_jacobian(
    z: torch.Tensor, energy: nn.Module, tol: float = 10**-3
):
    z.requires_grad_(True)
    for i in range(z.shape[-1]):
        f = energy.functional_value(z)[:, 1, i]
        f.backward(torch.ones_like(f), retain_graph=True)
        with torch.no_grad():
            grad_x = z.grad.clone()
            z.grad.zero_()
            if i == 0:
                jacobian = grad_x.unsqueeze(-2)
            else:
                jacobian = torch.cat((jacobian, grad_x.unsqueeze(-2)), dim=-2)

    v, w = torch.linalg.eigh(jacobian)
    v_restored = v + tol
    identity = torch.eye(z.shape[-1])
    v_matrix = torch.einsum("bj,ij->bij", 1 / v_restored, identity)
    inverse_jacobian = torch.einsum("bji,bik,bkr->bjr", w, v_matrix, w.conj())

    return inverse_jacobian.squeeze(0)


def compute_the_gradient(
    m: torch.DoubleTensor, h: torch.DoubleTensor, energy: nn.Module, respect_to: str
) -> torch.DoubleTensor:
    m = m.detach()
    if respect_to == "z":
        z = m[:, 0, :]
        z.requires_grad_(True)
        input = torch.cat((z.unsqueeze(1), m[:, 1, :].unsqueeze(1)), dim=1)
    elif respect_to == "x":
        x = m[:, 1, :]
        x.requires_grad_(True)
        input = torch.cat((m[:, 0, :].unsqueeze(1), x.unsqueeze(1)), dim=1)
    eng = energy(z=input, h=h)[0]
    eng.backward()
    with torch.no_grad():
        if respect_to == "z":
            grad = z.grad.clone()
            z.grad.zero_()
        elif respect_to == "x":
            grad = x.grad.clone()
            x.grad.zero_()
    return grad.detach(), eng.squeeze().item()


def compute_the_gradient_magn2field(
    m: torch.DoubleTensor, h: torch.DoubleTensor, model: nn.Module
) -> torch.DoubleTensor:
    m = m.detach()

    h_ml = model(m).unsqueeze(0)
    h_ml = torch.ones(h_ml.shape[-1])[None, None, :] * h_ml.mean(-1)[:, :, None]
    h_eff = -1 * (h - h_ml)

    return h_eff


def compute_the_gradient_of_the_functional(
    m: torch.DoubleTensor, model: nn.Module, respect_to: str
) -> torch.DoubleTensor:
    m = m.detach()

    if respect_to == "z":
        z = m[:, 0, :]
        z.requires_grad_(True)
        input = torch.cat((z.unsqueeze(1), m[:, 1, :].unsqueeze(1)), dim=1)
        print(input.shape)
    elif respect_to == "x":
        x = m[:, 1, :]
        x.requires_grad_(True)
        input = torch.cat((m[:, 0, :].unsqueeze(1), x.unsqueeze(1)), dim=1)
    eng = model(input)
    eng.backward(torch.ones_like(eng))
    with torch.no_grad():
        if respect_to == "z":
            grad = z.grad.clone()
            z.grad.zero_()
        elif respect_to == "x":
            grad = x.grad.clone()
            x.grad.zero_()

    return grad.detach()


def initialize_psi_from_z_and_x(
    z: torch.DoubleTensor, x: torch.DoubleTensor
) -> torch.ComplexType:
    psi = torch.zeros(size=(z.shape[-1], 2), dtype=torch.complex128)
    teta = torch.acos(x / torch.sqrt(1 - z**2))
    a = torch.sqrt((1 - z) / 2)
    b = torch.sqrt((1 + z) / 2)
    psi[:, 0] = torch.exp(-1j * teta) * a
    psi[:, 1] = b
    return psi


def initialize_psi_from_xyz(
    z: torch.DoubleTensor, x: torch.DoubleTensor, y: torch.DoubleTensor
) -> torch.ComplexType:
    psi = torch.zeros(size=(z.shape[-1], 2), dtype=torch.complex128)
    exp_teta = x / torch.sqrt(1 - z**2) + 1j * y / torch.sqrt(1 - z**2)
    a = torch.sqrt((1 - z) / 2)
    b = torch.sqrt((1 + z) / 2)
    psi[:, 0] = exp_teta * a
    psi[:, 1] = b
    return psi


def build_hamiltonian(
    field_x: torch.DoubleTensor, field_z: torch.DoubleTensor
) -> torch.ComplexType:
    x_operator = torch.tensor([[0.0, 1.0], [1.0, 0.0]], dtype=torch.complex128)
    z_operator = torch.tensor([[1.0, 0.0], [0.0, -1.0]], dtype=torch.complex128)

    return (
        field_x[:, None, None] * x_operator[None, :, :]
        + field_z[:, None, None] * z_operator[None, :, :]
    )


def compute_the_magnetization(psi: torch.Tensor) -> Tuple[torch.DoubleTensor]:
    x_operator = torch.tensor([[0.0, 1.0], [1.0, 0.0]], dtype=torch.complex128)
    z_operator = torch.tensor([[1.0, 0.0], [0.0, -1.0]], dtype=torch.complex128)
    y_operator = torch.tensor([[0.0, -1j], [1j, 0.0]], dtype=torch.complex128)

    x = torch.einsum("li,ij,lj->l", torch.conj(psi), x_operator, psi)  # .double()
    z = torch.einsum("li,ij,lj->l", torch.conj(psi), z_operator, psi)  # .double()
    y = torch.einsum("li,ij,lj->l", torch.conj(psi), y_operator, psi)  # .double()

    x = torch.real(x).double()
    z = torch.real(z).double()
    y = torch.real(y).double()

    return z.detach(), x.detach(), y.detach()


def compute_the_full_magnetization(psi: torch.Tensor) -> Tuple[torch.DoubleTensor]:
    x_operator = torch.tensor([[0.0, 1.0], [1.0, 0.0]], dtype=torch.complex128)
    z_operator = torch.tensor([[1.0, 0.0], [0.0, -1.0]], dtype=torch.complex128)
    y_operator = torch.tensor([[0.0, -1j], [1j, 0.0]], dtype=torch.complex128)

    x = torch.einsum("li,ij,lj->l", torch.conj(psi), x_operator, psi)  # .double()
    z = torch.einsum("li,ij,lj->l", torch.conj(psi), z_operator, psi)  # .double()
    y = torch.einsum("li,ij,lj->l", torch.conj(psi), y_operator, psi)  # .double()

    x = torch.real(x).double()
    z = torch.real(z).double()
    y = torch.real(y).double()

    m = torch.cat((x.unsqueeze(0), y.unsqueeze(0), z.unsqueeze(0)), dim=0)
    return m


def crank_nicolson_algorithm(
    hamiltonian: torch.ComplexType, psi: torch.ComplexType, dt: float
):
    identity = torch.tensor([[1.0, 0.0], [0.0, 1.0]], dtype=torch.complex128)
    unitary_op = identity[None, :, :] + 0.5j * dt * hamiltonian
    unitary_op_star = identity[None, :, :] - 0.5j * dt * hamiltonian
    unitary = torch.einsum(
        "lab,lbc->lac", torch.linalg.inv(unitary_op), unitary_op_star
    )
    # unitary = torch.matrix_exp(-1j * dt * hamiltonian)
    psi = torch.einsum("lab,lb->la", unitary, psi)
    # psi = psi - 0.5j * dt * torch.einsum("lab,lb->la", hamiltonian, psi)
    # impose the norm
    # psi = psi / torch.linalg.norm(psi, dim=-1)[:, None]
    return psi


def exponentiation_algorithm(
    hamiltonian: torch.ComplexType, psi: torch.ComplexType, dt: float
):
    identity = torch.eye(2, dtype=torch.complex128)
    p_1 = -1j * dt * hamiltonian.clone()
    p_2 = (-1j * dt) * torch.einsum("lab,lbc->lac", p_1, hamiltonian)
    p_3 = (-1j * dt) * torch.einsum("lab,lbc->lac", p_2, hamiltonian)
    p_4 = (-1j * dt) * torch.einsum("lab,lbc->lac", p_3, hamiltonian)

    unitary = (
        identity[None, :, :] + p_1 + p_2 / 2 + p_3 / (2 * 3) + p_4 / (2 * 3 * 4)
    )  # torch.matrix_exp(-1j * dt * hamiltonian)

    psi = torch.einsum("lab,lb->la", unitary, psi)
    psi = psi / torch.linalg.norm(psi, dim=-1)[:, None]
    return psi


def me_exponentiation_algorithm(
    hamiltonian: torch.ComplexType, psi: torch.ComplexType, dt: float
):
    identity = torch.eye(3)

    uni_dt_half = (
        identity[None, :, :] - (dt / 2) * hamiltonian
    )  # torch.matrix_exp(-dt * hamiltonian)
    uni_df_half = torch.linalg.inv(identity[None, :, :] + (dt / 2) * hamiltonian)
    unitary = torch.einsum("lab,lbc->lac", uni_df_half, uni_dt_half)

    # print(
    #     "unitary eig",
    #     torch.real(torch.linalg.eig(unitary)[0]) ** 2
    #     + torch.imag(torch.linalg.eig(unitary)[0]) ** 2,
    # )

    psi = torch.einsum("lab,lb->la", unitary, psi)
    return psi


def time_step_backward_algorithm(
    psi: torch.ComplexType,
    h: torch.Tensor,
    energy: nn.Module,
    dt: float,
    self_consistent_steps: int,
):
    psi0 = psi.clone()
    for i in range(self_consistent_steps):
        hamiltonian, eng = get_the_hamiltonian(psi, h=h, energy=energy)
        unitary = torch.matrix_exp(-1j * dt * hamiltonian)
        psi1 = torch.einsum("lab,lb->la", unitary, psi)
        # psi = psi0 - 1j * dt * torch.einsum("lab,lb->la", hamiltonian, psi)
        psi1 = psi1 / torch.linalg.norm(psi1, dim=-1)[:, None]

        hamiltonian1, eng1 = get_the_hamiltonian(psi1, h=h, energy=energy)
        hamiltonian = 0.5 * (hamiltonian + hamiltonian1)
        psi = torch.einsum("lab,lb->la", unitary, psi)
        psi = psi / torch.linalg.norm(psi, dim=-1)[:, None]
    return psi, eng


def get_the_hamiltonian(psi: torch.ComplexType, h: torch.Tensor, energy: nn.Module):
    x, z = compute_the_magnetization(psi=psi.clone())
    z = torch.cat((z.view(1, -1), x.view(1, -1)), dim=0)
    z = z.unsqueeze(0)  # the batch dimension
    h_eff, eng0 = compute_the_gradient(m=z, h=h, energy=energy, respect_to="z")
    omega_eff, _ = compute_the_gradient(m=z, h=h, energy=energy, respect_to="x")
    hamiltonian = build_hamiltonian(field_x=omega_eff[0], field_z=h_eff[0])
    return hamiltonian, eng0


def time_step_crank_nicolson_algorithm(
    psi: torch.ComplexType,
    h: torch.Tensor,
    h_plus: torch.Tensor,
    energy: nn.Module,
    dt: float,
    self_consistent_steps: int,
):
    for j in range(self_consistent_steps):
        hamiltonian, eng0 = get_the_hamiltonian(psi=psi.clone(), h=h, energy=energy)
        # print(hamiltonian[0, :], "\n")
        psi_1 = crank_nicolson_algorithm(
            hamiltonian=hamiltonian, psi=psi.clone(), dt=dt
        )

        hamiltonian_1, eng = get_the_hamiltonian(psi=psi_1, h=h_plus, energy=energy)
        psi = crank_nicolson_algorithm(
            hamiltonian=0.5 * (hamiltonian_1 + hamiltonian), psi=psi.clone(), dt=dt
        )

    return psi, eng


def heisemberg_matrix(omega_eff: torch.Tensor, h_eff: torch.Tensor):
    hm = torch.zeros(omega_eff.shape[-1], 3, 3, dtype=torch.double)
    hm[:, 0, 1] = h_eff
    hm[:, 1, 0] = -1 * h_eff
    hm[:, 1, 2] = omega_eff
    hm[:, 2, 1] = -1 * omega_eff

    return hm


def heisemberg_evolution_runge_kutta_step(
    m: torch.Tensor, h: torch.Tensor, energy: nn.Module, dt: float, idx: int
):
    # first step at t
    density = torch.cat((m[:, 2].unsqueeze(1), m[:, 0].unsqueeze(1)), dim=1)

    omega_eff = compute_the_gradient(
        m=density, h=h[idx].unsqueeze(0), energy=energy, respect_to="x"
    )
    h_eff = compute_the_gradient(
        m=density, h=h[idx].unsqueeze(0), energy=energy, respect_to="z"
    )
    # this is the zero order t+1 step
    matrix0 = heisemberg_matrix(omega_eff=-1 * omega_eff[0], h_eff=-1 * h_eff[0])
    k1 = torch.einsum("lab,ibl->ial", matrix0, m)
    m0_t_plus_1 = m + dt * k1

    density0_t_plus_1 = torch.cat(
        (m0_t_plus_1[:, 2].unsqueeze(1), m0_t_plus_1[:, 0].unsqueeze(1)), dim=1
    )
    omega_eff_0_t_plus_1 = compute_the_gradient(
        m=density0_t_plus_1, h=h[idx + 1].unsqueeze(0), energy=energy, respect_to="x"
    )
    h_eff_0_t_plus_1 = compute_the_gradient(
        m=density0_t_plus_1, h=h[idx + 1].unsqueeze(0), energy=energy, respect_to="z"
    )
    # compute the matrix at time step t+1/2dt
    matrix_t_half = 0.5 * (
        matrix0
        + heisemberg_matrix(
            omega_eff=-1 * omega_eff_0_t_plus_1[0], h_eff=-1 * h_eff_0_t_plus_1[0]
        )
    )
    k2 = torch.einsum("lab,ibl->ial", matrix_t_half, m + 0.5 * dt * k1)
    k3 = torch.einsum("lab,ibl->ial", matrix_t_half, m + 0.5 * dt * k2)

    # compute the matrix at time step t+dt
    m_t_plus_1 = m + (dt / 5) * (k1 + 2 * k2 + 2 * k3)

    density_t_plus_1 = torch.cat(
        (m_t_plus_1[:, 2].unsqueeze(1), m_t_plus_1[:, 0].unsqueeze(1)), dim=1
    )
    omega_eff_t_plus_1 = compute_the_gradient(
        m=density_t_plus_1, h=h[idx + 1].unsqueeze(0), energy=energy, respect_to="x"
    )
    h_eff_t_plus_1 = compute_the_gradient(
        m=density_t_plus_1, h=h[idx + 1].unsqueeze(0), energy=energy, respect_to="z"
    )
    matrix_t_plus_1 = heisemberg_matrix(
        omega_eff=-1 * omega_eff_t_plus_1[0], h_eff=-1 * h_eff_t_plus_1[0]
    )

    k4 = torch.einsum("lab,ibl->ial", matrix_t_plus_1, m + dt * k3)

    return m + (dt / 6) * (k1 + 2 * k2 + 2 * k3 + k4)


def nonlinear_master_equation_step(
    psi: torch.Tensor,
    energy: torch.nn.Module,
    i: int,
    h: torch.Tensor,
    self_consistent_step: int,
    dt: float,
    eta: float,
):
    x = psi[:, 0].double()
    z = psi[:, 2].double()

    m = torch.cat((z.view(1, -1), x.view(1, -1)), dim=0)
    m = m.unsqueeze(0)  # the batch dimension

    x0 = psi[:, 0].double()
    z0 = psi[:, 2].double()
    m0 = torch.cat((z0.view(1, -1), x0.view(1, -1)), dim=0)
    m0 = m0.unsqueeze(0)  # the batch dimension

    # m0 = torch.from_numpy(m_qutip_tot[q, i]).unsqueeze(0)

    omega_eff, engx = compute_the_gradient(
        m=m0, h=h[i].unsqueeze(0), energy=energy, respect_to="x"
    )
    h_eff, engz = compute_the_gradient(
        m=m0, h=h[i].unsqueeze(0), energy=energy, respect_to="z"
    )

    hamiltonian0 = torch.zeros((psi.shape[0], 3, 3))
    hamiltonian0[:, 0, 1] = -1 * h_eff[0]
    hamiltonian0[:, 1, 0] = 1 * h_eff[0]
    hamiltonian0[:, 1, 2] = -1 * omega_eff[0]
    hamiltonian0[:, 2, 1] = 1 * omega_eff[0]

    # hamiltonian0 = build_hamiltonian(
    #     field_x=-1 * omega_eff[0], field_z=-1 * h_eff[0]
    # )
    psi0 = me_exponentiation_algorithm(
        hamiltonian=hamiltonian0,
        psi=psi,
        dt=dt,
    )

    for step in range(self_consistent_step):
        x1 = psi0[:, 0].double()
        z1 = psi0[:, 2].double()

        # z1, x1, _ = compute_the_magnetization(psi=psi1)
        m1 = torch.cat((z1.view(1, -1), x1.view(1, -1)), dim=0)
        m1 = m1.unsqueeze(0)  # the batch dimension

        # m1 = torch.from_numpy(m_qutip_tot[q, i + 1]).unsqueeze(0)

        omega_eff1, eng = compute_the_gradient(
            m=m1, h=h[i + 1], energy=energy, respect_to="x"
        )
        h_eff1, _ = compute_the_gradient(
            m=m1, h=h[i + 1], energy=energy, respect_to="z"
        )

        hamiltonian1 = torch.zeros((psi.shape[0], 3, 3))
        hamiltonian1[:, 0, 1] = -1 * h_eff1[0]
        hamiltonian1[:, 1, 0] = 1 * h_eff1[0]
        hamiltonian1[:, 1, 2] = -1 * omega_eff1[0]
        hamiltonian1[:, 2, 1] = 1 * omega_eff1[0]

        psi1 = me_exponentiation_algorithm(
            hamiltonian=0.5 * (hamiltonian0 + hamiltonian1),
            psi=psi0,
            dt=dt,
        )
        psi0 = psi0 * (1 - eta) + eta * psi1

    psi = me_exponentiation_algorithm(
        hamiltonian=0.5 * (hamiltonian0 + hamiltonian1),
        psi=psi,
        dt=dt,
    )

    return (
        psi,
        engx,
        engz,
        omega_eff,
        h_eff,
    )


def nonlinear_schrodinger_step(
    psi: torch.Tensor,
    energy: torch.nn.Module,
    i: int,
    h: torch.Tensor,
    self_consistent_step: int,
    dt: float,
    eta: float,
    exponent_algorithm: bool,
):
    z, x, y = compute_the_magnetization(psi=psi)
    m = torch.cat((z.view(1, -1), x.view(1, -1)), dim=0)
    m = m.unsqueeze(0)  # the batch dimension

    eng = energy(m, h[i].unsqueeze(0))[0].item()

    z_minus, x_minus, _ = compute_the_magnetization(psi=psi)
    m_minus = torch.cat((z_minus.view(1, -1), x_minus.view(1, -1)), dim=0)
    m_minus = m_minus.unsqueeze(0)  # the batch dimension

    # m0 = torch.from_numpy(m_qutip_tot[q, i]).unsqueeze(0)

    omega_eff, engx = compute_the_gradient(
        m=m_minus, h=h[i].unsqueeze(0), energy=energy, respect_to="x"
    )
    h_eff, engz = compute_the_gradient(
        m=m_minus, h=h[i].unsqueeze(0), energy=energy, respect_to="z"
    )

    hamiltonian_minus = build_hamiltonian(
        field_x=-1 * omega_eff[0], field_z=-1 * h_eff[0]
    )
    if exponent_algorithm:
        psi_minus = exponentiation_algorithm(
            hamiltonian=hamiltonian_minus, psi=psi, dt=dt
        )
    else:
        psi_minus = crank_nicolson_algorithm(
            hamiltonian=hamiltonian_minus, psi=psi, dt=dt
        )

    hamiltonian_plus = hamiltonian_minus.clone()

    for step in trange(self_consistent_step):
        if exponent_algorithm:
            psi_plus = exponentiation_algorithm(
                hamiltonian=0.5 * (hamiltonian_minus + hamiltonian_plus),
                psi=psi,
                dt=dt,
            )
        else:
            psi_plus = crank_nicolson_algorithm(
                hamiltonian=0.5 * (hamiltonian_minus + hamiltonian_plus),
                psi=psi,
                dt=dt,
            )

        z_plus, x_plus, _ = compute_the_magnetization(psi=psi_plus)
        m_plus = torch.cat((z_plus.view(1, -1), x_plus.view(1, -1)), dim=0)
        m_plus = m_plus.unsqueeze(0)  # the batch dimension

        # m1 = torch.from_numpy(m_qutip_tot[q, i]).unsqueeze(0)

        omega_eff, eng = compute_the_gradient(
            m=m_plus, h=h[i].unsqueeze(0), energy=energy, respect_to="x"
        )
        h_eff, _ = compute_the_gradient(
            m=m_plus, h=h[i].unsqueeze(0), energy=energy, respect_to="z"
        )

        hamiltonian_plus = build_hamiltonian(
            field_x=-1 * omega_eff[0], field_z=-1 * h_eff[0]
        )

    if exponent_algorithm:
        psi = exponentiation_algorithm(
            hamiltonian=0.5 * (hamiltonian_plus + hamiltonian_minus),
            psi=psi,
            dt=dt,
        )
    else:
        psi = crank_nicolson_algorithm(
            hamiltonian=0.5 * (hamiltonian_minus + hamiltonian_plus),
            psi=psi,
            dt=dt,
        )

    return psi, omega_eff, h_eff, eng, x, y, z
