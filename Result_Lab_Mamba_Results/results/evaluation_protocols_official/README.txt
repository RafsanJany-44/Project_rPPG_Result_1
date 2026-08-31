RhythmMamba multi-protocol evaluation outputs
================================================

Each experiment directory contains three protocol directories:

official_mamba
    Exact verified RhythmMamba evaluation: reconstruct the complete recording,
    smoothness-prior detrending, first-order 0.75-2.5 Hz Butterworth filter,
    and Welch dominant-frequency HR in 45-150 BPM.

old
    8-second windows with 1-second stride, third-order 0.67-3.0 Hz filter,
    and a direct 240-point FFT at 30 FPS.

prism
    10-second non-overlapping windows, second-order 0.75-2.5 Hz filter, and
    a 16,384-point zero-padded FFT. This is the PRISM evaluation protocol only,
    not the complete PRISM prediction algorithm.

Inside each protocol directory:

tables/
    Measurement-level, recording-level, spectral-peak, failure, error, and
    extended-summary CSV files plus JSON/text summaries.

plots/
    Recording MAE, predicted-vs-GT HR, error histogram, Bland-Altman, and
    failure-category interactive HTML plots.

signal_comparisons/
    Interactive GT-vs-RhythmMamba waveform and spectrum plots per recording.

signal_tables/
    Sample-level GT and predicted waveform values per recording.

diagnostics/
    Interactive PSD views with GT, half-GT, and double-GT markers.

The top-level all_results_summary.csv contains one row for every
experiment/protocol combination. Checkpoints and caches are never modified.
