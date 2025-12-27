import pandas as pd
import ast
import io
import numpy as np
import matplotlib.pyplot as plt

# ---------- Paste your CSV rows here ----------
csv_text = """athlete_id,athlete_title,athlete_country_name,athlete_yob,splits,position,total_time,start_num,athlete_profile_image
135829,Gabriel Barac,Croatia,2004.0,"['00:09:29', '00:00:42', '00:26:47', '00:00:36', '00:16:18']",1,00:53:55,3,https://prod-tri-assets.imgix.net/ja.png
130086,Niko Matas,Croatia,2003.0,"['00:09:27', '00:00:41', '00:26:51', '00:00:38', '00:18:13']",2,00:55:52,2,
157909,Tin Rebic,Croatia,2004.0,"['00:09:17', '00:00:44', '00:26:59', '00:00:40', '00:19:10']",3,00:56:52,4,https://prod-tri-assets.imgix.net/db163568-2bb8-47df-89b1-c46e0888d5a9.JPG
30634,Jacopo Butturini,Croatia,1991.0,"['00:09:32', '00:00:44', '00:26:43', '00:00:38', '00:19:15']",4,00:56:53,1,https://prod-tri-assets.imgix.net/WhatsApp_Image_2020-10-29_at_15.45_.38_.jpeg
106537,Martin Štefan,Croatia,1996.0,"['00:10:00', '00:00:45', '00:27:07', '00:00:38', '00:18:51']",5,00:57:22,10,
163918,Zeljko Cota,Croatia,1997.0,"['00:10:36', '00:00:48', '00:27:43', '00:00:43', '00:17:56']",6,00:57:48,11,
96039,Luka Dumančić,Croatia,1998.0,"['00:09:45', '00:00:44', '00:28:37', '00:00:38', '00:18:38']",7,00:58:24,8,https://prod-tri-assets.imgix.net/241314097_1294139597695866_7195337243548614270_n.jpeg
131451,Matko Saric,Croatia,2002.0,"['00:10:53', '00:00:42', '00:27:30', '00:00:40', '00:18:51']",8,00:58:37,61,
170134,Pablo Benko,Croatia,2006.0,"['00:09:32', '00:00:40', '00:28:49', '00:00:40', '00:19:34']",9,00:59:17,12,
75939,Tin Kaurić,Croatia,1997.0,"['00:09:39', '00:00:51', '00:28:38', '00:00:44', '00:19:45']",10,00:59:39,14,https://prod-tri-assets.imgix.net/FB_IMG_15624345167514509.jpg
174905,Filip Carevic,Croatia,2005.0,"['00:10:23', '00:00:51', '00:27:52', '00:00:44', '00:19:51']",11,00:59:44,15,
163932,Marko Ivancic,Croatia,2004.0,"['00:10:35', '00:00:50', '00:27:43', '00:00:47', '00:20:23']",12,01:00:20,17,
157917,Mislav Hanza,Croatia,2004.0,"['00:10:22', '00:00:56', '00:27:49', '00:00:53', '00:20:31']",13,01:00:33,21,
131437,Adrian Zgaljic,Croatia,1992.0,"['00:09:45', '00:00:44', '00:28:36', '00:00:44', '00:21:55']",14,01:01:46,9,
161816,Marin Stipčević,Croatia,2005.0,"['00:09:38', '00:00:41', '00:28:46', '00:00:40', '00:23:40']",15,01:03:27,5,
170135,Vito Obrovac,Croatia,2006.0,"['00:10:36', '00:00:43', '00:29:35', '00:00:54', '00:21:52']",16,01:03:43,13,
174906,Loris Faustini,Croatia,,"['00:10:43', '00:00:50', '00:29:35', '00:00:48', '00:21:45']",17,01:03:44,23,
163931,Mark Surina,Croatia,2005.0,"['00:11:43', '00:00:50', '00:29:50', '00:00:47', '00:20:53']",18,01:04:04,26,
163904,Mario Šporčić,Croatia,1975.0,"['00:12:07', '00:00:58', '00:29:26', '00:00:52', '00:21:17']",19,01:04:42,22,
174907,Borna Matuzalem,Croatia,2006.0,"['00:11:14', '00:00:51', '00:30:28', '00:00:42', '00:21:38']",20,01:04:55,40,
174908,Patrik Smejkal,Croatia,,"['00:11:08', '00:00:51', '00:30:24', '00:00:50', '00:21:59']",21,01:05:14,18,
170840,Davor Varga,Croatia,1995.0,"['00:13:39', '00:00:50', '00:30:07', '00:01:02', '00:20:09']",22,01:05:49,32,
170841,Matej Dolibašić,Croatia,,"['00:12:13', '00:01:27', '00:29:42', '00:01:14', '00:21:52']",23,01:06:29,25,
174909,Borna Dobravac,Croatia,2006.0,"['00:10:55', '00:00:46', '00:30:49', '00:00:51', '00:23:26']",24,01:06:48,29,
130823,Kristian Hrbić,Croatia,1993.0,"['00:09:59', '00:00:50', '00:29:57', '00:00:51', '00:25:14']",25,01:06:53,33,
"""
# ---------------------------------------------------

SEGMENT_LABELS = ["Swim", "T1", "Bike", "T2", "Run"]
CHECKPOINTS = ["Start", "After Swim", "After T1", "After Bike", "After T2", "After Run"]

def hms_to_seconds(t: str) -> float:
    if not isinstance(t, str) or t.strip() == "" or t == "DNF":
        return np.nan
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)

def fmt_hhmmss(sec: float) -> str:
    sec = int(round(sec))
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

# ---- Read / parse ----
df = pd.read_csv(io.StringIO(csv_text))
df = df[df["position"] != "DNF"].copy()
df["splits_list"] = df["splits"].apply(ast.literal_eval)

split_secs = np.vstack(df["splits_list"].apply(lambda xs: [hms_to_seconds(x) for x in xs]).to_numpy())
split_df = pd.DataFrame(split_secs, columns=["swim", "t1", "bike", "t2", "run"], index=df.index)

# Cumulative times at checkpoints
cum = pd.DataFrame(index=df.index)
cum["After Swim"] = split_df["swim"]
cum["After T1"]   = split_df["swim"] + split_df["t1"]
cum["After Bike"] = split_df["swim"] + split_df["t1"] + split_df["bike"]
cum["After T2"]   = split_df["swim"] + split_df["t1"] + split_df["bike"] + split_df["t2"]
cum["After Run"]  = split_df["swim"] + split_df["t1"] + split_df["bike"] + split_df["t2"] + split_df["run"]

# Positions at checkpoints
df["start_num"] = pd.to_numeric(df["start_num"], errors="coerce")
pos = pd.DataFrame(index=df.index)
pos["Start"]      = df["start_num"].rank(method="first").astype(int)
pos["After Swim"] = cum["After Swim"].rank(method="first").astype(int)
pos["After T1"]   = cum["After T1"].rank(method="first").astype(int)
pos["After Bike"] = cum["After Bike"].rank(method="first").astype(int)
pos["After T2"]   = cum["After T2"].rank(method="first").astype(int)
pos["After Run"]  = cum["After Run"].rank(method="first").astype(int)

# ---- X layout with narrow transitions ----
seg_widths = np.array([1.0, 1.0/3.0, 1.0, 1.0/3.0, 1.0])
x = np.concatenate(([0.0], np.cumsum(seg_widths)))  # 6 checkpoint positions
seg_mids = (x[:-1] + x[1:]) / 2

t1_span = (x[1], x[2])
t2_span = (x[3], x[4])

def add_transition_bg(ax):
    ax.axvspan(*t1_span, color="grey", alpha=0.15, zorder=0)
    ax.axvspan(*t2_span, color="grey", alpha=0.15, zorder=0)
    for xv in [t1_span[0], t1_span[1], t2_span[0], t2_span[1]]:
        ax.axvline(xv, color="grey", alpha=0.35, linewidth=1.0, zorder=1)

def strip_axes(ax):
    # remove all spines (axis lines)
    for spine in ax.spines.values():
        spine.set_visible(False)
    # keep labels but remove tick marks
    ax.tick_params(axis="both", length=0)

# Plot order by finish time
order = cum["After Run"].sort_values().index

# =======================
# Plot 1: Positions (with names in same color at end)
# =======================
fig, ax = plt.subplots(figsize=(13, 7))
add_transition_bg(ax)

for idx in order:
    y = pos.loc[idx, CHECKPOINTS].to_numpy(dtype=float)
    (line,) = ax.plot(x, y, linewidth=1.6, alpha=0.85, zorder=2)

    # name at end of line (after run checkpoint)
    name = df.loc[idx, "athlete_title"]
    ax.text(
        x[-1] + 0.03, y[-1], name,
        color=line.get_color(),
        va="center", ha="left",
        fontsize=9,
        clip_on=False,
        zorder=3
    )

ax.invert_yaxis()
ax.set_ylabel("Position (lower is better)")
ax.set_xlabel("Race segments (T1/T2 are 1/3 width)")
ax.set_title("Snake-o-tron: Position at Start / Swim / T1 / Bike / T2 / Run")

# remove gridlines entirely (those y=5/10/15 etc.)
ax.grid(False)

# segment labels
ax.set_xticks(seg_mids)
ax.set_xticklabels(SEGMENT_LABELS)

# give room for labels on the right
ax.set_xlim(x.min(), x.max() + 0.9)

plt.tight_layout()
plt.show()

# =======================
# Plot 2: Time behind leader at each checkpoint (leader = 0 at each)
# =======================
# Build a "start" pseudo-time from start_num so we can show start order as a 0-based gap.
# If you *don't* want any start gap on the time plot, set gap_start = 0 for all.
start_rank = df["start_num"].rank(method="first").astype(int)
gap_start = start_rank - start_rank.min()

gap = pd.DataFrame(index=df.index)
gap["Start"] = 0.0

for c in ["After Swim", "After T1", "After Bike", "After T2", "After Run"]:
    gap[c] = cum[c] - cum[c].min()  # leader at that checkpoint => 0

fig, ax = plt.subplots(figsize=(13, 7))
add_transition_bg(ax)

for idx in order:
    y = gap.loc[idx, CHECKPOINTS].to_numpy(dtype=float)
    ax.plot(x, y, linewidth=1.6, alpha=0.85, zorder=2)

# fastest (smallest gap) at the top
ax.invert_yaxis()

ax.set_ylabel("Time behind leader at checkpoint (seconds)")
ax.set_xlabel("Race segments (T1/T2 are 1/3 width)")
ax.set_title("Time behind leader at each checkpoint (leader is always 0)")
ax.grid(False)

ax.set_xticks(seg_mids)
ax.set_xticklabels(SEGMENT_LABELS)

ax.set_xlim(x.min(), x.max())

# Optional: format ticks as HH:MM:SS even though axis is inverted.
# (This keeps 00:00:00 near the top, increasing times lower down.)
yt = ax.get_yticks()
ax.set_yticks(yt)
ax.set_yticklabels([fmt_hhmmss(abs(t)) for t in yt])

plt.tight_layout()
plt.show()
