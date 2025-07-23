# CT and RTStruct to nnU-Net Dataset Preparation

This document outlines the file system structure and data flow used by the scripts provided for converting DICOM CT images and RTStructs into an nnU-Net-compatible dataset format.
Additionally, a basic NIfTI viewer is included for quick-and-dirty visualization of the converted files and structures.

## Workflow Overview

1. **DICOM Retrieval**  
   Using a C# script with EvilDICOM and Varian API to retrieve files to `nnUNet_raw` directory (specified by environment variable).
   This script also creates the associated GTV.txt files for each patient (& course). 
   </br>

2. **Preprocessing and Conversion**  
   A Python script processes the DICOM files, extracts CT volumes and associated segmentation masks, and saves them as NIfTI files in the `nnUNet_raw` directory.
   Additionally, the NIfTI files are cropped around the segmentation masks. As of the time of this writing, it only keeps axial slices within 10 slices of a UNET (GTV) structure. Further cropping may or may not be implemented in the future. 
   </br>

3. **Training and Inference**  
   Once converted, the dataset can be used directly by `nnU-Net v2` for training and inference.

---

## Input Directory Format (`path_origin`)

The input directory should be structured as follows:

```yaml
Local_storage_folder/
├── PatID1/
│ ├── GTV.txt # Contains the names of the GTV(s) to extract, one per line
│ ├── CT_0/
│ │ ├── RS[...].dcm
│ │ ├── CT[...slice1...].dcm
│ │ ├── CT[...slice2...].dcm
│ │ └── ...
│ ├── CT_50/
│ │ ├── RS[...].dcm
│ │ ├── CT[...slice1...].dcm
│ │ ├── CT[...slice2...].dcm
│ │ └── ...
├── PatID2/
│ └── ...
```


- Each `PatID` corresponds to a patient.
- Each scan phase (e.g., `CT_0`, `CT_50`) is a subdirectory containing CT slices and an associated RTStruct file.
- `GTV.txt` defines which ROIs to extract. ROIs may be phase-specific (e.g., `UNET1_0`, `UNET1_50`) or shared across phases, depending on the configuration.

---

## Output Directory Format (`nnUNet_raw`)

After processing, the script will populate the following structure under the `nnUNet_raw` environment variable:


```yaml
nnUNet_raw/
└── DatasetXXX_<DatasetName>/
├── imagesTr/
│ ├── PatID1_CT_0_0000.nii.gz
│ ├── PatID1_CT_50_0000.nii.gz
│ └── ...
├── labelsTr/
│ ├── PatID1_CT_0.nii.gz
│ ├── PatID1_CT_50.nii.gz
│ └── ...
├── imagesTs/
│ ├── PatID2_CT_0_0000.nii.gz
│ └── ...
├── labelsTs/
│ ├── PatID2_CT_0.nii.gz
│ └── ...
├── sliceLOCTr/
│ └── PatID1_CT_0_LOC.pkl
├── sliceLOCTs/
│ └── PatID2_CT_0_LOC.pkl
└── dataset.json
```


- `imagesTr/` and `imagesTs/`: contain NIfTI CT images for training and testing.
- `labelsTr/` and `labelsTs/`: contain NIfTI label masks.
- `sliceLOCTr/` and `sliceLOCTs/`: store metadata including slice positions and spacing, saved as `.pkl` files.
- `dataset.json`: provides a summary for nnU-Net, including modality, label mapping, number of training samples, and file ending.

---

## Cropping Output Format (`nnUNet_raw`)
After conversion, the cropping script will copy all relevant files and folders from the desired directory. it will then save the cropped files (CTs and associated structures) in the following structure:


```yaml
nnUNet_raw/
└── DatasetXXX_<DatasetName>CROPPED/
├── imagesTr/
│ ├── PatID1_CT_0_0000.nii.gz
│ ├── PatID1_CT_0_0000.nii.gz
│ └── ...
├── labelsTr/
│ ├── PatID1_CT_0_0000.nii.gz
│ ├── PatID1_CT_0_0001.nii.gz
│ └── ...
├── imagesTs/
│ ├── PatID2_CT_0_0000.nii.gz
│ └── ...
├── labelsTs/
│ ├── PatID2_CT_0_0000.nii.gz
│ └── ...
├── sliceLOCTr/
│ └── PatID1_CT_0_LOC.pkl
├── sliceLOCTs/
│ └── PatID2_CT_0_LOC.pkl
└── dataset.json
```

## Notes

- The script supports automatic detection of phase-specific ROIs if the `GTV.txt` names follow the pattern `ROI_<PhaseNumber>`. For example, `UNET1_0`, `UNET1_50`.
- The number of training and testing cases is determined by the `Test_split` parameter and is randomized at each run unless a dataset already exists.
- Processed patients are skipped on subsequent runs unless `overwrite_converted_data=True` is set.