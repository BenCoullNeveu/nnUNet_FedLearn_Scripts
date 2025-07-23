# -*- coding: utf-8 -*-
"""
Author: Mathieu Goulet
Modifications from Ben Coull-Neveu

Conversion of CT images and contours to nnUnet-compatible NIfTI datasets.


path_origin points to the path where the DICOM RTS are stored, format of the folder must be : 
Local_storage_folder
├── PatID1
│ ├── GTV.txt
│ ├── CT_0
│ │ ├── RTStruct.dcm
│ │ ├── CT[...slice1...].dcm
│ │ ├── CT[...slice2...].dcm
│ │ ├── CT[...slice3...].dcm
│ │ ├── [...]
│ ├── CT_50
│ │ ├── RTStruct.dcm
│ │ ├── CT[...slice1...].dcm
│ │ ├── CT[...slice2...].dcm
│ │ ├── CT[...slice3...].dcm
│ │ ├── [...]
├── PatID2
[...]

-> GTV.txt contains the name of the GTV(s) in the DICOM
"""

import nibabel as nib
import numpy as np
import os
import glob
import pydicom
import pickle
import random
import shutil
from tqdm import tqdm
from rt_utils import RTStructBuilder

# Set dataset name (used for directory creation under nnUNet_raw)
Dataset_id = 801 # <-- CHANGE THIS as needed (should be unique. Ideally, choose value above 500 to avoid name-conflicts with existing nnUnet datasets)
Dataset_name = "SBRTest" # <-- CHANGE THIS as needed

# Root folder where DICOM files are located (patients in subfolders)
path_origin = "I:\\PHYSICS\\Ben\\DICOM\\"  # <-- CHANGE THIS as needed

# Set to False if ROIs are the same across all phases. Set to None if the algorithm is to auto-detect (assuming a particular format)
use_phase_specific_gtv_names = None  # <-- CHANGE THIS as needed. None, True, False

# Test/train split ratio for dataset preparation. Training will be used in a 5-fold CV scheme. E.g. 20% test / 80% train
Test_split = 0.40  # <-- CHANGE THIS as needed




# Automatically build target path under nnUNet's expected location
full_dataset_name = f"Dataset{Dataset_id}_{Dataset_name}"
path_target = os.environ['nnUNet_raw'] + "/" + full_dataset_name + "/"



# ===========================
# Main Conversion Function
# ===========================
def main(path_origin, path_target, delete_origin_data=False, overwrite_converted_data=True):
    """Converts DICOM + RTStruct data into nnUNet-style NIfTI images and segmentation masks.
    Saves CTs in 'imagesTr' / 'imagesTest', masks in 'labelsTr' / 'labelsTest'.

    -> delete_origin_data can be set to True if you want to delete each DICOM files as they are processed. 
    -> overwrite_converted_data can be set to True if you want to have a fresh dataset for nnUnet.
    """

    if os.path.exists(path_target):
        print(f"> nnUnet_raw directory exists for {full_dataset_name}")
        if overwrite_converted_data:
            while True:
                cont = str(input("\n!! >> Are you sure you want a fresh directory? This will delete all existing converted data. (y/n)\n")).lower()
                if cont == "y":
                    print(f"> Creating a fresh nnUnet_raw directory for {full_dataset_name}")
                    shutil.rmtree(path_target)
                    os.makedirs(path_target)
                    break
                elif cont == "n":
                    break
    else:
        print(f"> nnUNet_raw directory doesn't exist for {full_dataset_name}. Creating it now...")
        os.makedirs(path_target)

    path_images = path_target + "imagesTr/"
    path_labels = path_target + "labelsTr/"
    path_LOC = path_target + "sliceLOCTr/"
    # originally imageTest, labelsTest, and sliceLOCTest. Changed to follow nnUnet documentation
    path_images_T = path_target + "imagesTs/" 
    path_labels_T = path_target + "labelsTs/"
    path_LOC_T = path_target + "sliceLOCTs/"
    
    for P in [path_images,path_labels,path_LOC,path_images_T,path_labels_T,path_LOC_T]:
        if not os.path.exists(P):
            os.makedirs(P)
        
    # Identify patient folders (e.g., PatID1, PatID2...)
    folder_list = glob.glob(path_origin + "*/")
    ID_list_Origin = [Pa for Pa in os.listdir(path_origin) if os.path.isdir(path_origin+Pa)]

    # Safety check: warn if no valid folders are found
    if len(ID_list_Origin) == 0: 
        print(f"WARNING: No files found in directory: {path_origin+os.listdir(path_origin)[0]}. Check slashes or folder structure.")
            
    # Remove already processed IDs from training/test list (avoids duplicates)
    TEMP = glob.glob(path_images + "*.nii.gz")
    ID_list_Target_Tr = [os.path.basename(P).split("_")[0] for P in TEMP]
    # ID_list_Target_Tr = []
    # for P in TEMP:
    #     P1 = os.path.basename(P)
    #     P1_splits = P1.split("_")
    #     if P1_splits[0] not in ID_list_Target_Tr:
    #         ID_list_Target_Tr.append(P1_splits[0])
            
    TEMP = glob.glob(path_images_T + "*.nii.gz")
    ID_list_Target_Ts = [os.path.basename(P).split("_") for P in TEMP]
    # ID_list_Target_Test = []
    # for P in TEMP:
    #     P1 = os.path.basename(P)
    #     P1_splits = P1.split("_")
    #     if P1_splits[0] not in ID_list_Target_Test:
    #         ID_list_Target_Test.append(P1_splits[0])
    
    # Filter out already-processed patients from the origin list
    ID_list_Origin = [ID for ID in ID_list_Origin if ID not in ID_list_Target_Tr and ID not in ID_list_Target_Ts]

    # Determine how many total cases and how to split them
    total_n_im = len(ID_list_Origin) + len(ID_list_Target_Tr) + len(ID_list_Target_Ts)            
    n_test = int(np.round(total_n_im*(Test_split)))
    n_train = total_n_im - n_test
    n_test_missing = n_test - len(ID_list_Target_Ts)
    
    # Randomly assign remaining cases to test/train
    Test_set =  random.sample(ID_list_Origin, n_test_missing) + ID_list_Target_Ts
    Train_set = [ID for ID in ID_list_Origin if ID not in Test_set] + ID_list_Target_Tr
    
    # -------------------------------
    # Process each patient directory
    # -------------------------------
    for iF,RID in tqdm(enumerate(ID_list_Origin),total = len(folder_list)):
        F = path_origin + RID + "/"

        # Read GTV label(s) from GTV.txt file
        with open(F + "GTV.txt", 'r') as file:
            all_ROIs = [line.strip() for line in file if line.strip()]

        # Auto-detect if GTVs are phase-specific (e.g., UNET1_0, UNET2_50)
        auto_detected_phase_specific = all(('_' in roi and roi.split('_')[-1].isdigit()) for roi in all_ROIs)

        # Final decision: manual override takes priority, else use detection
        phase_specific = use_phase_specific_gtv_names if use_phase_specific_gtv_names is not None else auto_detected_phase_specific
        
        # Getting each phase for a given  patient ID
        Phases = [P for P in os.listdir(F) if os.path.isdir(F + P)]
        OK_to_delete = True
        
        print("# phases: ", len(Phases))
        for P in Phases:
            # Load CT image stack and extract relevant slice metadata
            dcm_array_crop, dcm_slice_ALL, dcm_SliceLoc, ImagePositionPatient, PixelSpacing = import_US_stack(F + P + "/",SIZE_Z = 0)

            # Extract phase suffix (e.g., 0 or 50) from folder name
            phase_suf = ''.join(filter(str.isdigit, P))  # "Phase0" -> "0", "Phase50" -> "50"
            if phase_specific:
                ROIs = [roi for roi in all_ROIs if roi.endswith("_" + phase_suf)]
                print("Contours in phase:", len(ROIs))
            if not ROIs:
                print(f"WARNING: No ROIs for phase {P} in patient {RID}. Skipping phase...")
                continue

            # Convert RTStruct to binary segmentation mask
            mask_ROI = import_US_RTS(F + P + "/",dcm_slice_ALL,dcm_SliceLoc,SIZE_Z = 0, ROIs=ROIs)

            # Skip this phase if segmentation failed
            if isinstance(mask_ROI, int) == False:
                affine = np.eye(4)
                affine[0,0] = float(PixelSpacing[1]) #y pixel resolution
                affine[1,1] = float(PixelSpacing[0]) #x pixel resolution
                affine[2,2] = np.round(dcm_SliceLoc[1] - dcm_SliceLoc[0],2)*10 #Slice thickness
                
                # Setting up save location fror NIfTI files
                if RID in Train_set:
                    save_path_im = path_images + RID + "_" + P + "_0000.nii.gz"
                    save_path_mask = path_labels + RID + "_" + P + ".nii.gz"
                    save_path_LOC = path_LOC + RID+ "_" + P + "_LOC.pkl"
                else: # in Test set
                    save_path_im = path_images_T + RID + "_" + P + "_0000.nii.gz"
                    save_path_mask = path_labels_T + RID + "_" + P + ".nii.gz"
                    save_path_LOC = path_LOC_T + RID+ "_" + P + "_LOC.pkl"
                      
                # Save image as NIfTI
                N_img = nib.Nifti1Image(dcm_array_crop, affine)  # Save axis for data (just identity)
                N_img.header.get_xyzt_units()
                N_img.to_filename(save_path_im)  # Save as NiBabel file
                
                # Save mask as NIfTI
                N_mask = nib.Nifti1Image(mask_ROI, affine)  # Save axis for data (just identity)
                N_mask.header.get_xyzt_units()
                N_mask.to_filename(save_path_mask)  # Save as NiBabel file
                
                # Save metadata (used for debugging, resampling, etc.)
                with open(save_path_LOC , 'wb') as f:
                    pickle.dump([dcm_slice_ALL, dcm_SliceLoc, ImagePositionPatient, PixelSpacing], f)
                    
            else: 
                print("Error while importing RTS for ID = " + RID)
                OK_to_delete = False

        # Optionally delete original data to save disk space            
        if delete_origin_data and OK_to_delete:
            shutil.rmtree(F)

    # Generate nnUNet's dataset.json file        
    Write_dataset_json(path_target,n_train = n_train*2)
            
# ========================
# JSON Config for nnUNet
# ========================          
def Write_dataset_json(path_target,n_train):
    Base_json = """{ 
 "channel_names": {
   "0": "CT" 
 }, 
 "labels": {
   "background": 0,
   "GTV": [1]
 }, 
 "numTraining": """ + str(n_train) + """, 
 "file_ending": ".nii.gz"
}"""
    
    with open(path_target  + 'dataset.json', 'w') as file:
        # Write content to the file
        file.write(Base_json)
            
# ========================
# Load DICOM CT Stack
# ========================
def import_US_stack(folder,SIZE_Z,im_size = (512,512)):
    dcm_list = glob.glob(folder + 'CT*.dcm')
    print(f"# CT scans found: {len(dcm_list)}")
    if len(dcm_list) == 0:
        dcm_list = glob.glob(folder + '/US*.dcm') # For Ultrasounds
    threshold = im_size[0]*im_size[1] * 0.687
    
    if SIZE_Z > 0:
        dcm_array = np.zeros((im_size[0],im_size[1],SIZE_Z)) #0 padding to make size = SIZE_Z
        
        #Reading all slices, but only keeping non-empty ones
        dcm_slice_ALL = [] #To use with RTStruct
        dcm_slice_nonemp = []
        for i,l in enumerate(dcm_list):
            ds = pydicom.dcmread(l)
            dcm_array_i = ds.pixel_array
            dcm_slice_ALL.append(float(ds.SliceLocation)/10)
            # print(np.sum(dcm_array_i == 0))
            if np.sum(dcm_array_i == 0) < threshold:
                dcm_slice_nonemp.append(float(ds.SliceLocation)/10)
        dcm_slice_ALL.sort()
        for k in range(2):
            if k == 0: dcm_slice_nonemp.sort(reverse = True)
            else: dcm_slice_nonemp.sort()
            dcm_slice_nonemp.pop() #Removing first and last nonempty slice
        if len(dcm_slice_nonemp) >= SIZE_Z: #Keeping only SIZE_Z images
            dcm_SliceLoc = np.array(dcm_slice_nonemp[-SIZE_Z:])
        else:
            dcm_SliceLoc = np.ones(SIZE_Z)*10000
            dcm_SliceLoc[0:len(dcm_slice_nonemp)] = dcm_slice_nonemp
        for i,l in enumerate(dcm_list):
            ds = pydicom.dcmread(l)
            dcm_index = np.where(dcm_SliceLoc == float(ds.SliceLocation)/10)[0]
            if len(dcm_index) == 1:
                dcm_array[:,:,dcm_index[0]] = ds.pixel_array
    else:
        #Reading all slices, but only keeping non-empty ones
        dcm_slice_ALL = [] #To use with RTStruct
        dcm_slice_nonemp = []
        for i,l in enumerate(dcm_list):
            ds = pydicom.dcmread(l)
            dcm_array_i = ds.pixel_array
            dcm_slice_ALL.append(float(ds.SliceLocation)/10)
            # print(np.sum(dcm_array_i == 0))
            if np.sum(dcm_array_i == 0) < threshold:
                dcm_slice_nonemp.append(float(ds.SliceLocation)/10)
        dcm_slice_ALL.sort()
        for k in range(2):
            if k == 0: dcm_slice_nonemp.sort(reverse = True)
            else: dcm_slice_nonemp.sort()
            dcm_slice_nonemp.pop() #Removing first and last nonempty slice
        dcm_SliceLoc = dcm_slice_nonemp[:]
        dcm_array = np.zeros((im_size[0],im_size[1],len(dcm_SliceLoc))) #0 padd
        for i,l in enumerate(dcm_list):
            ds = pydicom.dcmread(l)
            if float(ds.SliceLocation)/10 in dcm_SliceLoc:
                dcm_index = dcm_SliceLoc.index(float(ds.SliceLocation)/10)
                dcm_array[:,:,dcm_index] = ds.pixel_array

    return dcm_array, dcm_slice_ALL, dcm_SliceLoc, ds.ImagePositionPatient, ds.PixelSpacing

# ========================
# Load RTStruct Masks
# ========================
def import_US_RTS(folder,dcm_slice_ALL,dcm_SliceLoc,SIZE_Z,ROIs,im_size = (512,512)):
    dcm_SliceLoc = list(dcm_SliceLoc)
    
    if SIZE_Z == 0 :
        SIZE_Z = len(dcm_SliceLoc)
    
    if len(ROIs) == 1:
        mask_ROI = np.zeros((im_size[0],im_size[1],SIZE_Z))
    else:
        mask_ROI = np.zeros((len(ROIs),im_size[0],im_size[1],SIZE_Z))
    rts_list = glob.glob(folder + 'RS*.dcm')
    print(f"RTS files found: {len(rts_list)}")
    
    # Match RS*.dcm files — you may need to update this if your files are named differently
    size_rts = os.path.getsize(rts_list[0])
    if size_rts < 20000:
        print("Empty RT struct, folder = " + folder)
        return 0
    else: #More than 20ko, typical if not empty
        # Parse RTStruct
        rtstruct = RTStructBuilder.create_from(
              dicom_series_path=folder, 
              rt_struct_path=rts_list[0]
            )
        
        for iR,ROI in enumerate(ROIs):
            if ROI in rtstruct.get_roi_names():
                TEMP = rtstruct.get_roi_mask_by_name(ROI)
            else: 
                print("Missing ROI! " + ROI + ", folder = " + folder)
                return 0
        
            for i,sl in enumerate(dcm_slice_ALL):
                if sl in dcm_SliceLoc:
                    dcm_index = dcm_SliceLoc.index(sl)
                    if len(ROIs) == 1:
                        mask_ROI[:,:,dcm_index] = TEMP[:,:,i]
                    else:
                        mask_ROI[iR,:,:,dcm_index] = TEMP[:,:,i]
                     
        # return mask_ROI
        if mask_ROI.ndim == 4:
            return np.any(mask_ROI, axis=0).astype(np.uint8) # combining all structures in a phase
        # else
        return mask_ROI
            

# ========================
# Run the script
# ========================
if __name__ == '__main__':
    main(path_origin, path_target, delete_origin_data = False)