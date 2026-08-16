# Virtual Multiplex Pathology Analyzer

A desktop GUI app for **serial-section whole-slide image (WSI)** analysis
in pathology. Given two consecutive sections stained for different
markers (e.g. Ki67.ndpi and p53.ndpi), it performs:

1. **Cell detection & positivity** — via the [DeepLIIF](https://deepliif.org)
   cloud API (SegRefined mask).
2. **Non-rigid image registration** — SimpleITK Rigid → Affine → B-spline.
3. **Pseudo-fluorescence visualization** — stain-deconvolution based
   (NOT DeepLIIF-generated multiplex IF).
4. **Cell-level matching + validity check** — nearest-neighbor pairing
   plus a null-model diagnostic (see "Honest limitations" below).
5. **Region-level co-localization** — tile-based Pearson/Spearman
   correlation of positive-cell densities.
6. **Export** — CSV / Excel / PNG / PDF / PPTX / JSON.

Runs on **macOS (Apple Silicon/Intel)** and **Windows 11**. GPU is not
required (the DeepLIIF cloud API handles inference).

## ⚠ Important notices

- **Research and education use only. Not for clinical diagnosis.**
- **Non-commercial use only.** This project depends on DeepLIIF, which
  is distributed under Apache 2.0 with the Commons Clause condition.
  This project therefore uses the same license (see `LICENSE`).
- **This project is a personal hobby project** by the author. It is
  **not affiliated with, endorsed by, or a work product of** the author's
  employer. Bug reports and issues are handled on a best-effort basis.
- **Do not upload PHI/PII** (patient-identifying whole-slide images) to
  the DeepLIIF public endpoint. Use anonymized or public sample data.

## Honest limitations (please read before publishing results)

Several aspects of this workflow are known to be imperfect and are
surfaced in the output rather than hidden:

- **The DeepLIIF cloud API returns only segmentation outputs**
  (`Seg`, `SegOverlaid`, `SegRefined`) — it does **not** return the
  Virtual DAPI / Marker / Lap2 modality images that DeepLIIF is known
  for. Those require local (GPU) execution of DeepLIIF, which this
  project does not perform. Consequently:
  - Cell detection and positive/negative classification **are** from
    DeepLIIF (SegRefined).
  - The colored "fluorescence-like" display and the "Pseudo DAPI"
    channel are **stain-deconvolution outputs of the original IHC**
    (Ruifrok–Johnston), not DeepLIIF Virtual IF.
- **Serial sections do not preserve 1:1 cell correspondence.** A Ki67
  nucleus and a p53 nucleus that lie a few micrometers apart across
  adjacent sections are typically **different cells**. This project
  therefore always computes a null-model diagnostic (`match_diagnostics`):
  the observed nearest-neighbor distance distribution is compared with
  the distribution under a random-placement null. If the two are not
  distinguishable, the "co-positive rate" is flagged as not being
  evidence of same-cell co-expression.
- **Region-level co-localization** (tile-based density correlation) is
  the recommended primary readout for serial-section IHC pairs.

## Screenshots

_TODO: add screenshots using public sample data (see below)._

## Sample data (no patient data is bundled)

For demonstration and reproducibility, use publicly available data:

- **DeepLIIF sample tissues** (Nadeem Lab): Ki67 IHC patches for testing
  the cloud API — <https://github.com/nadeemlab/DeepLIIF>
- **OpenSlide demo WSIs**: NDPI/SVS files for testing the WSI loader —
  <https://openslide.org/demo/>
- **Human Protein Atlas** (CC BY-SA 4.0): IHC images for Ki67, p53, etc.
  — <https://www.proteinatlas.org/>

The repository also contains a self-contained synthetic test in
`tests/smoke_pipeline.py` that runs without any external data.

## Requirements

- Python 3.11+
- OpenSlide native library (for `.ndpi` and other WSI formats)

## Installation

```bash
# Clone
git clone https://github.com/Takamoto36/VirtualMultiplexAnalyzer.git
cd VirtualMultiplexAnalyzer

# Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate            # macOS/Linux
# .venv\Scripts\Activate.ps1         # Windows PowerShell

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Native library for .ndpi
brew install openslide               # macOS
# See https://openslide.org/download/ for Windows binaries.
```

## Run

```bash
python app.py
```

## Basic workflow

1. Click "+ WSI を追加" and load two serial sections (e.g. Ki67.ndpi
   and p53.ndpi).
2. Switch to "ROI 選択モード" (default on). Click on the tissue with
   the `2000×2000` preset to place a fixed-size ROI on each section,
   targeting the **same anatomical region** on both.
3. Click "▶ 解析を実行". Analysis takes a few minutes.
4. Read the results dialog carefully — the "Cell Matching 妥当性"
   line tells you whether the cell-level correspondence is
   distinguishable from chance for this field of view.
5. Export via File → Export.

## Tests

```bash
pytest -q
```

All tests should pass without any external services (the API-facing
tests are mocked).

## Citation

If you use this software in academic work, please cite the underlying
DeepLIIF papers (see `THIRD_PARTY_LICENSES.md`). Citation of this
project itself is optional; a `CITATION.cff` may be added later.

## License

Apache License 2.0 with the Commons Clause condition — see `LICENSE`.
Third-party dependencies retain their original licenses; see
`THIRD_PARTY_LICENSES.md`.

## Disclaimer

THIS SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND. It is
not a medical device and must not be used for clinical decision-making.
The developer is not liable for any use of, or reliance on, its output.
