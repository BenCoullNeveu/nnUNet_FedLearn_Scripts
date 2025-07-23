import os
import shutil
import nibabel as nib
import numpy as np
from glob import glob
import copy
from scipy.ndimage import label as connected_components

SRC_DIR = "C:\\nnUnet\\nnUnet_raw\\Dataset801_SBRTest"#Dataset801_SBRTest" # <-- CHANGE THIS to desired source directory
fresh_dir = True # <-- CHANGE THIS to overwrite the output directory, if it exists already

## SEE MAIN AT THE BOTTOM

def get_bboxes(mask_img, margin=10):
    """Return list of bounding boxes around connected structures in a binary mask."""
    mask = mask_img.get_fdata()

    labeled_mask, num_features = connected_components(mask)

    bboxes = []
    for i in range(1, num_features + 1):
        structure_mask = (labeled_mask == i)
        coords = np.argwhere(structure_mask)

        if coords.size == 0:
            continue
        
        # CODE FOR 3D-CONSTRAINED BOUNDING BOX 
        # min_coords = np.maximum(coords.min(axis=0) - margin, 0)
        # max_coords = np.minimum(coords.max(axis=0) + margin + 1, mask.shape)
        # bbox = tuple(slice(min_c, max_c) for min_c, max_c in zip(min_coords, max_coords))

        # CODE FOR 1D-CONSTRAINED BOUNDING BOX
        zmin = np.maximum(coords[:, 2].min() - margin, 0)
        zmax = np.minimum(coords[:, 2].max() + margin + 1, mask.shape[2])
        bbox = (slice(0, mask.shape[0]), slice(0, mask.shape[1]), slice(zmin, zmax))
        
        bboxes.append(bbox)
        print(f"    -> Structure {i}: bbox shape = {[s.stop - s.start for s in bbox]}")

    return bboxes

def crop_and_save(ct_path, mask_path, ct_out, label_out):
    """Crop CT and mask images around the mask ROI using memory-efficient nibabel slicer and save to output_dir."""
    ct_img = nib.load(ct_path)
    mask_img = nib.load(mask_path)

    bboxes = get_bboxes(mask_img)
    if not bboxes:
        print(f"No structures found in mask: {mask_path}")
        return

    for i, bbox in enumerate(bboxes):
        if len(bbox) != 3:
            print(f" >> Skipping bbox {i} from {mask_path} because it has {len(bbox)} dimensions instead of the required 3.")
            continue

        # Use slicer for memory-efficient cropping
        cropped_ct = ct_img.slicer[bbox[0], bbox[1], bbox[2]]
        cropped_mask = mask_img.slicer[bbox[0], bbox[1], bbox[2]]

        ct_base_name = os.path.basename(ct_path).replace("_0000.nii.gz", "")

        ct_out_path = os.path.join(ct_out, f"{ct_base_name}_{i:04}.nii.gz")
        mask_out_path = os.path.join(label_out, f"{ct_base_name}_{i:04}.nii.gz")

        nib.save(cropped_ct, ct_out_path)
        nib.save(cropped_mask, mask_out_path)


def crop_cts(ct_dir, label_dir, ct_out, label_out):
    ct_paths = sorted(glob(os.path.join(ct_dir, "*.nii.gz")))
    label_paths = sorted(glob(os.path.join(label_dir, "*.nii.gz")))

    for ct_path, label_path in zip(ct_paths, label_paths):
        print(f"\nCropping scan: {os.path.basename(ct_path)}")
        crop_and_save(ct_path, label_path, ct_out, label_out)


def copy_dir_wo_files(src, dst, exclude_file_dirs):
    """Copy directory tree from src to dst, excluding files in certain subdirectories."""
    for root, _, files in os.walk(src):
        # Determine the relative path from the source root
        rel_path = os.path.relpath(root, src)
        dest_dir = os.path.join(dst, rel_path)

        # Make the directory in destination
        os.makedirs(dest_dir, exist_ok=True)

        # If this directory should not have its files copied
        if os.path.basename(root) in exclude_file_dirs:
            continue

        # Copy all files in this directory
        for file in files:
            src_file = os.path.join(root, file)
            dst_file = os.path.join(dest_dir, file)
            shutil.copy2(src_file, dst_file)

if __name__ == "__main__":

    print("Starting the cropping script...")

    crop_dir = SRC_DIR + "CROPPED"
    exclude_file_dirs = {"imagesTr", "labelsTr", "imagesTs", "labelsTs"}

    if not os.path.exists(crop_dir):
        copy_dir_wo_files(SRC_DIR, crop_dir, exclude_file_dirs)
    elif fresh_dir:
        shutil.rmtree(crop_dir)
        copy_dir_wo_files(SRC_DIR, crop_dir, exclude_file_dirs)

    imagesTr_dir = os.path.join(SRC_DIR, "imagesTr")
    labelsTr_dir = os.path.join(SRC_DIR, "labelsTr")
    imagesTs_dir = os.path.join(SRC_DIR, "imagesTs")
    labelsTs_dir = os.path.join(SRC_DIR, "labelsTs")

    itr_out = os.path.join(crop_dir, "imagesTr")
    ltr_out = os.path.join(crop_dir, "labelsTr")
    its_out = os.path.join(crop_dir, "imagesTs")
    lts_out = os.path.join(crop_dir, "labelsTs")

    crop_cts(imagesTr_dir, labelsTr_dir, itr_out, ltr_out)
    crop_cts(imagesTs_dir, labelsTs_dir, its_out, lts_out)

    print(f"\n{'-'*5} Cropping script completed {'-'*5}")