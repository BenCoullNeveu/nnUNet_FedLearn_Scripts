import nibabel as nib
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider
import os

# --- MANUAL PATHS ---
CT_PATH = "nnUnet_raw/Dataset801_SBRTestCROPPED/imagesTr/1207850-2_targets_CT_0_0001.nii.gz"
LABEL_PATH = "nnUnet_raw/Dataset801_SBRTestCROPPED/labelsTr/1207850-2_targets_CT_0_0001.nii.gz"  # Leave as empty string "" if no contour
INCLUDE_CONTOUR = bool(LABEL_PATH)

# --- OPTIONS ---
axis = 'axial'  # Options: 'axial', 'frontal', 'transverse'
rotate = False

# --- LOAD DATA ---
nii_img = nib.load(CT_PATH)
nii_data = nii_img.get_fdata()

if INCLUDE_CONTOUR:
    c_img = nib.load(LABEL_PATH)
    c_data = c_img.get_fdata()

# --- SWAP AXES ---
if axis == "frontal":
    nii_data = np.swapaxes(nii_data, 1, 2)
    if rotate:
        nii_data = np.flip(np.swapaxes(nii_data, 0, 1), 0)
    if INCLUDE_CONTOUR:
        c_data = np.swapaxes(c_data, 1, 2)
        if rotate:
            c_data = np.flip(np.swapaxes(c_data, 0, 1), 0)
elif axis == "transverse":
    nii_data = np.swapaxes(nii_data, 0, 2)
    if rotate:
        nii_data = np.flip(nii_data, 0)
    if INCLUDE_CONTOUR:
        c_data = np.swapaxes(c_data, 0, 2)
        if rotate:
            c_data = np.flip(c_data, 0)

# --- PLOTTING ---
fig, ax = plt.subplots(constrained_layout=True)
axcolor = 'lightgoldenrodyellow'
axpos = plt.axes([0.2, 0.1, 0.65, 0.03], facecolor=axcolor)
nslices = nii_data.shape[2]
spos = Slider(axpos, 'Slice', 0, nslices - 1, valinit=nslices // 2, valstep=1)

axposmin = plt.axes([0.04, 0.1, 0.03, 0.65])
axposmax = plt.axes([0.95, 0.1, 0.03, 0.65])
minval = min(nii_data.min(), 0)
maxval = nii_data.max()
sposmin = Slider(axposmin, "Min", minval, maxval, valinit=minval, orientation='vertical')
sposmax = Slider(axposmax, "Max", minval, maxval, valinit=255, orientation='vertical')

img = ax.imshow(nii_data[:, :, spos.val], cmap='gray', interpolation=None, vmin=minval, vmax=255)
if INCLUDE_CONTOUR:
    c_img = ax.imshow(c_data[:, :, spos.val], cmap='Reds', interpolation=None, vmin=0, vmax=1, alpha=c_data[:, :, spos.val] * 0.7)
ax.axis('off')

def updateslice(val):
    slice = int(spos.val)
    img.set_data(nii_data[:, :, slice])
    if INCLUDE_CONTOUR:
        c_img.set_data(c_data[:, :, slice])
        c_img.set_alpha(c_data[:, :, slice] * 0.7)
    ax.set_title(f"Slice {slice}")
    fig.canvas.draw_idle()

spos.on_changed(updateslice)

def updatehist(val):
    newmin = sposmin.val
    newmax = sposmax.val
    if newmin >= newmax + 100:
        sposmax.set_val(newmax)
        sposmin.set_val(newmax - 100)
    img.set_clim(vmin=newmin, vmax=newmax)

sposmin.on_changed(updatehist)
sposmax.on_changed(updatehist)

plt.show()