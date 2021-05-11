# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.11.2
#   kernelspec:
#     display_name: Python 3
#     language: python
#     name: python3
# ---

# %% tags=[]
import cantools
import sys
import pandas as pd
import panel as pn
import holoviews as hv
import geoviews as gv
import datetime as dt
from tqdm import tqdm
from pathlib import Path

if '..' not in sys.path:
    sys.path.append('..')  # Ugly hack to allow imports below to work
from teslalogs import raw
from teslalogs.model_3 import LOG, HRL
from teslalogs.model_3.CL import CL
from teslalogs.signals import SignalViewer

hv.extension('bokeh')
gv.extension('bokeh')
pn.extension()
# %load_ext autoreload
# %autoreload 2

# %% [markdown]
# # Old pre-2020 LOG

# %%
log_df = LOG.parse_file('/tmp/LOG/6.LOG')

# %%
dtmin = log_df['timestamp'] > '2019-07-20'
dtmax = log_df['timestamp'] < '2019-07-22'
log_df = log_df[dtmin & dtmax]

# %%
# Example dbc: https://github.com/joshwardell/model3dbc
dbc = cantools.database.load_file('/tmp/Model3CAN.dbc')

# %%
log_viewer = SignalViewer(log_df, dbc)
log_viewer.nbview()

# %%
wheelFL = log_viewer.get_plot("ID175WheelSpeed", "WheelSpeedFL175")
wheelFR = log_viewer.get_plot("ID175WheelSpeed", "WheelSpeedFR175")
wheelRL = log_viewer.get_plot("ID175WheelSpeed", "WheelSpeedRL175")
wheelRR = log_viewer.get_plot("ID175WheelSpeed", "WheelSpeedRR175")
vehicleSpeed = log_viewer.get_plot("ID257UIspeed", "UIspeed_signed257")
steering = log_viewer.get_plot("ID129SteeringAngle", "SteeringAngle129")

# %%
(wheelFL * wheelFR * wheelRL * wheelRR * vehicleSpeed + steering).cols(1).opts({'Curve':{'height':300}})

# %% [markdown]
# # HRL 

# %%
hrl_path = Path('/tmp/HRL/')    
hrl_df = pd.concat(HRL.parse_file(p) for p in tqdm(hrl_path.glob('*.HRL')) if not 'CUR' in p.name)
hrl_df = hrl_df.sort_values('timestamp').reset_index()

# %%
hrl_viewer = SignalViewer(hrl_df, dbc)
hrl_viewer.nbview()

# %% [markdown]
# # CL

# %%
cl = CL('/tmp/CL/DATA')
headers = cl.get_timespan(tstart=dt.datetime(2020, 3, 4), tend=dt.datetime(2020, 3, 5))
df = cl.parse_objects(headers)
# df = cl.parse_objects(cl.headers[-15:])

# %%
# %%opts Curve [width=1000, height=600] {+framewise}
sig_ids = list(df.groupby('signal').count().sort_values('value', ascending=False).index)

def show_sig(sig_id):
    tmp = df[df['signal'] == int(sig_id, 16)]
    return hv.Curve(tmp, 'timestamp', 'value')
dmap = hv.DynamicMap(show_sig, kdims='sig_id').redim.values(sig_id=list(hex(s) for s in sig_ids))
dmap

# %%

# %% [markdown]
# # Snapshots

# %%
# Sync AP raw can log on crash message (assuming it's present, i.e. the vehicle crashed)
raw_path = Path('/tmp/snapshot.2018.11.05.collision-airbag-deploy.26279595-cb2f-4535-80d0-e53785d09f6e-0001/raw')
raw_rx = raw.parse_file(raw_path / 'canrx.can')
raw_tx = raw.parse_file(raw_path / 'cantx.can')
raw_df = pd.concat((raw_tx, raw_rx)).sort_values('timestamp')

# %%
raw_start_uptime = raw_df[raw_df['arbitration_id'] == 0x11]['timestamp'].iloc[0]
raw_start_timestamp = hrl_df[hrl_df['arbitration_id'] == 0x11]['timestamp'].iloc[0]
raw_df_synced = raw_df.copy()
raw_df_synced['timestamp'] = ((raw_df['timestamp'] - raw_start_uptime) * 1e9).astype('timedelta64[ns]') + raw_start_timestamp

# %%
# Crop log timespan
minutes_before = 10
minutes_after = 2
filt = ((log_df['timestamp'] > (raw_start_timestamp - pd.Timedelta(minutes=minutes_before))) & 
        (log_df['timestamp'] < (raw_start_timestamp + pd.Timedelta(minutes=minutes_after))))
log_df = log_df[filt]

# %%
raw_viewer = SignalViewer(raw_df_synced, dbc)

# %%

# %% [markdown]
# ### Position
# Note that GPS locations are **only** present in snapshot and HRL CAN logs!

# %%
# %%opts Overlay [width=800, height=800]
position = raw_viewer.get_plot("ID04FGPSLatLong", "GPSLongitude04F")
(gv.tile_sources.EsriImagery * gv.Points(position, ['GPSLongitude04F', 'GPSLatitude04F'], label='Position')).opts({'Points': {'size':5}})

# %% [markdown]
# ### Video
# This assumes output generated by our script: teslalogs/snapshot_video/convert_videos.py to synchronize the video and plots

# %%
vidfile = Path('/tmp/processed/overview_downscaled.mp4')
video_time = [float(x) for x in (Path(vidfile).parent / 'time_info.txt').read_text().split(',')]

video = pn.pane.Video(str(vidfile), width=960, height=480, loop=True)
filt = (raw_df['timestamp'] >= video_time[0] - 1) & (raw_df['timestamp'] <= video_time[-1] + 1)
vid_sigviewer = SignalViewer(raw_df[filt], dbc)
time_slider = pn.widgets.FloatSlider(name='Time', start=0, end=video_time[-1]-video_time[0], step=0.05, width=960)

time_slider.jslink(video, value='time', bidirectional=True)
video.jslink(time_slider, time='value')

@pn.depends(vid_sigviewer.param.signal)
def update_sig(signal):
    plt = vid_sigviewer.update_plot().opts(width=960, height=300)
    vline = hv.VLine(video.time + video_time[0]).opts(color='k')
    code = f'glyph.location = source.time + {video_time[0]}'
    link = video.jslink(vline, code={'time': code})
    return plt * vline 

view = pn.Column(video, time_slider, pn.Row(update_sig, vid_sigviewer.nbview()[0]))
view

# %%
