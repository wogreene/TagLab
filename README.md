# TagLab: an image segmentation tool oriented to marine data analysis

| &nbsp; [Software Requirements](#software-requirements) &nbsp; | &nbsp; [Install](#installing-taglab) &nbsp; | &nbsp; [Update](#updating-taglab) &nbsp; | &nbsp; [Citation](#citation) &nbsp; |

TagLab was developed to assist with the annotation and extraction of statistical data from ortho-maps of benthic communities. The tool features various AI segmentation networks specifically trained for agnostic recognition (focused solely on contours) and semantic recognition (which also considers species) of corals. TagLab is an ongoing project of the [Visual Computing Lab](http://vcg.isti.cnr.it/).  

![ScreenShot](screenshot.jpg)


## Interaction

TagLab allows users to interactively segment regions using the following methods:

- [`DEXTR: Four-Clicks Tool`](https://github.com/scaelles/DEXTR-PyTorch): This tool involves indicating the extremes of regions with four clicks. It utilizes the `Deep Extreme Cut` model, which has been fine-tuned for complex structures.
- [`RITM: Positive-Negative Clicks Tool`](https://github.com/saic-vul/ritm_interactive_segmentation): This tool enables users to define the interior and exterior of a region through positive and negative clicks. It utilizes the `Reviving Iterative Training with Mask Guidance` model, which has been train to work across various domains.
- [`SAM: Positive-Negative Clicks Tool`](https://github.com/facebookresearch/segment-anything): This tool allows for indicating the interior and exterior of a region within a sub-window using positive and negative clicks. It utilizes the `Segment Anything` model, which has been trained to work across various domains.
- [`SAM: All Regions in an Area Tool`](https://github.com/facebookresearch/segment-anything): This tool allows users to segment all regions inside a sub-window by automatically placing region seeds. It utilizes the `Segment Anything` model, which has been trained to work across various domains.
- [`CoralNet-Toolbox`](https://github.com/Jordan-Pierce/CoralNet-Toolbox): This tool enables users to make predictions on points in TagLab, using a CoralNet model. It utilizes the `CoralNet-Toolbox`, which is an official codebase used to augment processes related to `CoralNet` and `CPCe`.

## Fully Automated Segmentation

TagLab enables users to automatically segment regions by using a custom segmentation model, which are trained using the 
[`DeepLab V3+`](https://github.com/jfzhang95/pytorch-deeplab-xception) backbone. Using a custom model in TagLab is 
accomplished through the following steps:

1. Creating and managing a training dataset
2. Training a model using the `Train Your Network` interface
3. Making predictions with the `Fully Automated Semantic Segmentation` tool

TagLab has many resources for image data management and analysis, including the ability to track changes among time 
points. For additional information, please visit the official TagLab website and documentation 
[page](https://taglab.isti.cnr.it/).

## Software Requirements

TagLab runs on __Linux__, __Windows__, and __MacOS__. To run TagLab, the main requirement is just __64bit Python 3.11.x__.

GPU accelerated computations are not supported on MacOS and on any machine that does not have an NVIDIA graphics card 
with CUDA enabled.

## Installing TagLab

See the instructions on the [wiki](https://github.com/cnr-isti-vclab/TagLab/wiki/Install-TagLab).

## Updating TagLab

This is a customised fork, so the source is updated through git rather than by overwriting it.
`update.py` no longer replaces any code — it only downloads the neural networks, which are not
kept in version control:

```bash
python3 update.py
```
or, on Windows:

```bash
python.exe update.py
```

It also reports whether upstream has released a newer version. To review and merge those changes:

```bash
git fetch upstream
git log --oneline HEAD..upstream/main    # see what changed
git merge upstream/main                  # bring it in, resolving conflicts
```

If the `upstream` remote does not exist yet:

```bash
git remote add upstream https://github.com/cnr-isti-vclab/TagLab.git
```

NOTE: If some package is missing after merging upstream changes, re-launch `install.py`.


# Citation

If you use TagLab, please cite it.

```
@article{TagLab,
	author = {Pavoni, Gaia and Corsini, Massimiliano and Ponchio, Federico and Muntoni, Alessandro and Edwards, Clinton and Pedersen, Nicole and Sandin, Stuart and Cignoni, Paolo},
	title = {TagLab: AI-assisted annotation for the fast and accurate semantic segmentation of coral reef orthoimages},
	year = {2022},
	journal = {Journal of Field Robotics},
	volume = {39},
	number = {3},
	pages = {246 – 262},
	doi = {10.1002/rob.22049}
}
```
