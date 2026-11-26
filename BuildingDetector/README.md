# OSM Building Detector

A local browser tool for reviewing OSM building footprints against the supplied satellite mosaic. It uses the mosaic's companion JSON for exact Web Mercator alignment and the downloaded project OSM data at `../data/osm/buildings.json`.

## Start

1. Install Node.js if it is not already installed.
2. Run `setup.bat` once from this folder. It installs ONNX Runtime Web and Sharp, then downloads the approximately 210 MB HOTOSM model file.
3. Run `start.bat`, then open <http://127.0.0.1:8765> in a browser.
4. Click a square in the mosaic overview and press **Run building model on tile**.

The app reads the image and OSM data from the existing workspace. A small overview and one 256 × 256 satellite crop are served as needed, so the browser does not decode the full 271 MB mosaic. Model inference runs locally in the browser.

## Model

The detector uses HOTOSM's DINOv3-S building segmentation ONNX model. It is documented for high-resolution RGB aerial and satellite imagery, with a 256 × 256 input and a published confidence threshold of 0.4371. The companion model documentation describes 30–50 cm imagery as its best operating range; this mosaic is 50 cm per pixel. Its reported zero-shot building instance F1 on the Banepa scene was 0.30, which is a reminder to review these candidates rather than treat them as correct labels.

The model weights are distributed under Meta's DINOv3 License. See the [model card](https://huggingface.co/hotosm/dinov3s-buildings) and [HOTOSM model documentation](https://github.com/hotosm/fAIr-models/tree/develop/models/dinov3s_buildings) for attribution, terms, and performance details. The app applies the documented RGB channel normalization and default threshold.

## Reading the comparison

OSM footprints are rasterized at 256 × 256 resolution. The app computes polygon-to-component IoU for the selected tile and greedily assigns matches at IoU ≥ 0.25. Green means IoU ≥ 0.50, yellow 0.25–0.49, and red below 0.25 or no match. Cyan indicates AI components that did not match an OSM building. Candidate outlines are connected components of the model's building-probability mask, so adjacent buildings can merge; the confidence and minimum-area controls let you inspect the effect of thresholds.

No polygons are filled. The comparison uses only building geometry from the local OSM buildings extract; it does not modify OSM or upload imagery.
