# Third-Party Licenses

This project depends on the following third-party software. Each is
distributed under its own license, and this project does not modify or
supersede those licenses.

Contributors should read this file before redistributing derivatives.

---

## Runtime dependency: DeepLIIF (cloud API)

- **Project**: DeepLIIF — Deep Learning Inferred Multiplex ImmunoFluorescence
- **Upstream**: <https://github.com/nadeemlab/DeepLIIF> (Nadeem Lab, MSKCC)
- **License**: Apache License 2.0 **with Commons Clause**
  (non-commercial academic use)
- **How this project uses it**: this project sends region-of-interest (ROI)
  images to the public cloud endpoint at `https://deepliif.org/api/infer`
  and consumes the returned JSON (segmentation images and scoring). No
  DeepLIIF source code or trained model weights are bundled.
- **Consequence for this project**: because DeepLIIF adds the Commons
  Clause on top of Apache 2.0 (i.e. the software cannot be Sold), any
  workflow that relies on DeepLIIF — including this project — is also
  restricted to non-commercial use. This project therefore adopts the
  same Apache 2.0 + Commons Clause condition (see `LICENSE`) for
  consistency with the upstream constraint.
- **Cite the following DeepLIIF papers when publishing results**:
  - Ghahremani P. et al. *Deep learning-inferred multiplex immuno-
    fluorescence for immunohistochemical image quantification.*
    Nature Machine Intelligence, 2022.
  - Ghahremani P. et al. *An AI-Ready Multiplex Staining Dataset for
    Reproducible and Accurate Characterization of Tumor Immune
    Microenvironment.* MICCAI 2023.
  - See the upstream repository for the full list.

---

## Runtime dependencies (BSD/MIT/Apache family)

The following are used at runtime and are permissively licensed. Their
license terms are compatible with Apache 2.0. This section is a summary;
authoritative license text is shipped inside each installed package
under `site-packages/<package>/LICENSE*`.

| Package                | License              | Purpose                       |
|------------------------|----------------------|-------------------------------|
| PySide6 (Qt for Python)| LGPL v3 / commercial | Desktop GUI framework         |
| SimpleITK              | Apache 2.0           | Image registration            |
| openslide-python       | LGPL v2.1            | Whole-slide image reader      |
| scikit-image           | BSD-3-Clause         | Image processing              |
| NumPy                  | BSD-3-Clause         | Numerics                      |
| SciPy                  | BSD-3-Clause         | Numerics                      |
| OpenCV (opencv-python) | Apache 2.0           | Image processing              |
| pandas                 | BSD-3-Clause         | Tabular I/O                   |
| matplotlib             | PSF-based (BSD-like) | Figures                       |
| imageio                | BSD-2-Clause         | Image I/O                     |
| tifffile               | BSD-3-Clause         | TIFF I/O                      |
| Pillow                 | HPND (MIT-style)     | Image I/O                     |
| openpyxl               | MIT                  | Excel writer                  |
| python-pptx            | MIT                  | PowerPoint writer             |
| requests               | Apache 2.0           | HTTP client                   |

### About PySide6 (LGPL) and openslide-python (LGPL)

Both are dynamically linked as Python extensions. Under LGPL you may
redistribute this project (which uses them via `import`) as long as the
LGPL library itself can be replaced by the user. Because both are
installed from PyPI by the user, this requirement is satisfied.

---

## Native library: OpenSlide

- **Project**: OpenSlide (C library)
- **Upstream**: <https://openslide.org/>
- **License**: LGPL v2.1
- **How this project uses it**: `openslide-python` is a thin binding.
  The user is expected to install the OpenSlide native library
  separately (`brew install openslide` on macOS,
  Windows binary downloads on Windows). It is not bundled here.

---

## No patient data, no model weights, no fonts are redistributed by this
project.

If you fork or repackage this project, you MUST retain this file and
the top-level `LICENSE` in the redistribution.
