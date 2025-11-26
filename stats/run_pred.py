import numpy as np
import matplotlib.pyplot as plt
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, WhiteKernel, ConstantKernel as C
import time
import pandas as pd
from datetime import datetime, timedelta

def parse_time(time_str):
    parts = time_str.strip().split(":")
    if len(parts) == 3:
        h, m, s = map(int, parts)
        return h * 3600 + m * 60 + s
    elif len(parts) == 2:
        m, s = map(int, parts)
        return m * 60 + s
    return 0

def format_time(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

def date_to_days(dates):
    base_date = min(dates)
    days = np.array([(d - base_date).days for d in dates])
    return days.reshape(-1, 1), base_date

start_time = time.time()

# Load and prepare data
run_times = pd.read_csv("run_times.csv")
dates = [datetime.strptime(d, "%Y-%m-%d") for d in run_times["date"]]
times = np.array([t for t in run_times["time"]])

dates = list(dates)
times = np.array(times)

# Convert dates to days
X, base_date = date_to_days(dates)
y = times

start_time = time.time()

# Prepare prediction range
X_pred = np.linspace(X.min(), X.max(), 200).reshape(-1, 1)
pred_dates = [base_date + timedelta(days=int(d)) for d in X_pred.flatten()]

# Kernel: smooth long-term trend (RBF length_scale ~ 120 days)
kernel = (
    C(1.0, (1e-3, 1e3)) * 
    RBF(length_scale=90, length_scale_bounds=(30, 1e4)) + 
    WhiteKernel(noise_level=30**2, noise_level_bounds=(1, 1e4))
)

gp = GaussianProcessRegressor(
    kernel=kernel,
    n_restarts_optimizer=10,
    normalize_y=True,
    alpha=.1
)

# Fit
gp.fit(X, y)
y_pred, sigma = gp.predict(X_pred, return_std=True)

# Smooth uncertainty taper (more confidence as more races seen)
# taper = np.linspace(1.0, 0.4, len(y_pred))
# sigma_tapered = np.maximum(sigma * taper, 30)  # floor of 30 sec std

# Current form
current_form = y_pred[-1]
# current_std = sigma_tapered[-1]

end_time = time.time()
print(f"Run prediction completed in {end_time - start_time:.2f} seconds")

print(f"Current Form: {current_form/60:.2f} min")

# --- Plot ---
plt.figure(figsize=(10, 5))
plt.title("Run Form Prediction (Smoothed GP with Tapered Uncertainty)", fontsize=13, fontweight='bold')
plt.plot(pred_dates, y_pred / 60, label="Predicted Run Form", linewidth=2.2, color="#3F51B5")
plt.fill_between(pred_dates,
                 (y_pred - sigma) / 60,
                 (y_pred + sigma) / 60,
                 alpha=0.25, label="±1 std", color="#3F51B5")
plt.scatter(dates, times / 60, s=35, color="black", alpha=0.7, label="Observed")
plt.ylabel("Run Time (min)")
plt.xlabel("Date")
plt.legend()
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.show()