# Road vault

Parametric library of road pieces, built fresh (not on junction_net/roads3d).

- `engine.py`: Scene/Arm/Ring -> mesh (asphalt, kerbed pavements, islands, slip lanes, paint, signals, cars, shadows)
- `grade.py`: overpasses/underpasses as ribbons with height profiles
- `elements.py`: 241 extra design elements (posts, furniture, signs, lighting, planting, gantries, barriers, markings, calming, transit, pedestrian, utilities)
- `catalog.py`: the 100 most common types (`make(id, **overrides)`)
- `typelib.py`: 10,000 stratified types out of ~3.3M valid parameter combinations (`python typelib.py out.json`)
- `run_all.py` / `gallery.py`: render the catalogue / the element gallery (`xvfb-run -a python ...`)

Previews come from this engine's own builder, not roads3d.
