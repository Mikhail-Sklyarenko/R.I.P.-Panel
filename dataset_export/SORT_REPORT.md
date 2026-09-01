# Dataset sort report
Generated: 2026-08-28T13:50:41.469513+00:00

## Counts
- bootstrap_images_on_disk: 5473
- bootstrap_labels_on_disk: 5473
- bootstrap_test_kept: 571
- bootstrap_train_excluded: 2924
- bootstrap_train_kept: 1469
- bootstrap_val_kept: 509
- quarantine_bootstrap_suspicious: 2924
- hn_total_images: 1670
- bootstrap_train_images: 1469
- exclude_train_stems: 2924
- bootstrap_complete: True

## Train PC
hard_negatives updated in vendor/csgobot (in-place).
If bootstrap_complete is false: extract product_v1_bootstrap.rar on Train PC.
BuildProductWithHardNegatives.bat
TrainProductModel.bat --data vendor\csgobot\yolov8\datasets\product_data_hn.yaml --name product_golden_v1
