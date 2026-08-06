# Ship image tools with the core runtime

Image tools are a first-class LabelImg Enhanced capability rather than an optional plugin, so the Image menu and its processing, preview, metadata, and recovery behavior must work in every supported installation. The distribution therefore carries the headless OpenCV, NumPy, and Pillow runtime despite the larger installation size; this avoids Qt plugin conflicts from GUI OpenCV builds and prevents an advertised core workflow from depending on undeclared local packages.
