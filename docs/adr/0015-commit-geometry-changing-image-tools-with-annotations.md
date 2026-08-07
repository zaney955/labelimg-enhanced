# Commit geometry-changing image tools with annotations

An image tool that changes image bounds or dimensions also changes the coordinate space of its annotations. Such a tool must therefore commit and recover the image and its associated annotation resources as one atomic unit, instead of placing coordinate changes in annotation Undo or permitting image-only recovery; this prevents either history from restoring only half of a valid image-annotation pair.
