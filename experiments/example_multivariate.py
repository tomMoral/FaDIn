# %% import stuff
# import libraries
import time
import numpy as np
import torch
from tick.hawkes import SimuHawkes, HawkesKernelTimeFunc

from fadin.kernels import DiscreteKernelFiniteSupport
from fadin.solver import FaDIn
from fadin.utils.utils import projected_grid
from tick.hawkes import HawkesBasisKernels
################################
# Meta parameters
################################
dt = 0.01
L = int(1 / dt)
T = 1_000_000
size_grid = int(T / dt) + 1

# mem = Memory(location=".", verbose=2)

# %% Experiment
################################


# @mem.cache
def simulate_data(baseline, alpha, mu, sigma, T, dt, seed=0):
    L = int(1 / dt)
    discretization = torch.linspace(0, 1, L)
    u = mu - sigma
    n_dim = u.shape[0]
    RC = DiscreteKernelFiniteSupport(dt, n_dim=n_dim, kernel='raised_cosine',
                                     lower=0, upper=1)

    kernel_values = RC.kernel_eval([torch.Tensor(u), torch.Tensor(sigma)],
                                   discretization)
    kernel_values = kernel_values * alpha[:, :, None]

    t_values = discretization.double().numpy()
    k11 = kernel_values[0, 0].double().numpy()
    k12 = kernel_values[0, 1].double().numpy()
    k21 = kernel_values[1, 0].double().numpy()
    k22 = kernel_values[1, 1].double().numpy()

    tf11 = HawkesKernelTimeFunc(t_values=t_values, y_values=k11)
    tf12 = HawkesKernelTimeFunc(t_values=t_values, y_values=k12)
    tf21 = HawkesKernelTimeFunc(t_values=t_values, y_values=k21)
    tf22 = HawkesKernelTimeFunc(t_values=t_values, y_values=k22)

    kernels = [[tf11, tf12], [tf21, tf22]]
    hawkes = SimuHawkes(
        baseline=baseline, kernels=kernels, end_time=T, verbose=False, seed=int(seed)
    )

    hawkes.simulate()
    events = hawkes.timestamps
    return events


# @mem.cache
def run_solver(events, u_init, sigma_init, baseline_init, alpha_init, dt, T,
               ztzG_approx, seed=0):
    start = time.time()
    max_iter = 2000
    solver = FaDIn(2,
                   "raised_cosine",
                   [torch.tensor(u_init),
                    torch.tensor(sigma_init)],
                   torch.tensor(baseline_init),
                   torch.tensor(alpha_init),
                   delta=dt, optim="RMSprop",
                   step_size=1e-3, max_iter=max_iter,
                   optimize_kernel=True, precomputations=True,
                   ztzG_approx=ztzG_approx, device='cpu', log=False, tol=10e-6
                   )

    print(time.time() - start)
    results = solver.fit(events, T)
    results_ = dict(param_baseline=results['param_baseline'][-10:].mean(0),
                    param_alpha=results['param_alpha'][-10:].mean(0),
                    param_kernel=[results['param_kernel'][0][-10:].mean(0),
                                  results['param_kernel'][1][-10:].mean(0)])
    results_["time"] = time.time() - start
    results_["seed"] = seed
    results_["T"] = T
    results_["dt"] = dt
    return results_


baseline = np.array([.1, .2])
alpha = np.array([[1.5, 0.1], [0.1, 1.5]])
mu = np.array([[0.4, 0.6], [0.55, 0.6]])
sigma = np.array([[0.3, 0.3], [0.25, 0.3]])
u = mu - sigma
events = simulate_data(baseline, alpha, mu, sigma, T, dt, seed=1)

print("events of the first process: ", events[0].shape[0])
print("events of the second process: ", events[1].shape[0])


# %%
v = 0.2
baseline_init = baseline + v
alpha_init = alpha + v
mu_init = mu
sigma_init = sigma + v
u_init = mu_init - sigma_init
ztzG_approx = True
results = run_solver(events, u_init, sigma_init,
                     baseline_init, alpha_init,
                     dt, T, ztzG_approx, seed=0)
print(results)

# %%


# %%
non_param = HawkesBasisKernels(1, n_basis=1, kernel_size=int(1 / dt), max_iter=800)
non_param.fit(events)
discretization = np.linspace(0, 1, L)
tick_kernel_values = np.zeros((2, 2, L))
for i in range(2):
    for j in range(2):
        tick_kernel_values[i, j] = non_param.get_kernel_values(i, j, discretization)
tick_kernel_values *= alpha.reshape(2, 2, 1)
tick_kernel_values = torch.tensor(tick_kernel_values)
events_grid = projected_grid(events, dt, L * T)
intensity_temp= torch.zeros(2, 2, size_grid-1)
for i in range(2):
    intensity_temp[i, :, :] = torch.conv_transpose1d(
        events_grid[i].view(1, size_grid-1),
        tick_kernel_values[:, i].reshape(1, 2, L).float())[
            :, :-L + 1]
intensity_tick = intensity_temp.sum(0) + torch.tensor(baseline).unsqueeze(1)

