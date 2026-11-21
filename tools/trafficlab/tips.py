"""Hover tooltips for every control in the lab UI, keyed by the label shown (a label prefix also matches)."""
TIPS = {
    # top bar
    "Play": "Run the live simulation (Space)", "Pause": "Freeze the live simulation (Space)",
    "Step": "Advance the paused simulation by one time step (.)",
    "x1": "Real time", "x2": "2x real time", "x4": "4x real time", "x8": "8x real time", "x16": "16x real time",
    "max": "As fast as this PC can simulate (the map redraws less often)",
    "Restart": "Rebuild the live run with the current settings and seed (orange = settings changed, a restart is needed)",
    "New seed": "Restart with a different random seed: same settings, different traffic",
    "Help (F1)": "Keys, mouse controls and what each tab does", "Quit": "Close the traffic lab (Esc)",
    # tabs
    "Live": "Live numbers and charts of the running simulation",
    "Inspect": "Details of whatever you clicked: a vehicle, a junction (and its signal plan) or a road",
    "Edit": "Map tools: close roads, place obstacles, incidents, draw the study area",
    "Layers": "What the map shows and how it is coloured",
    "Batch": "Many seeded runs of several variants on all cores, with a statistical report",
    "Explore": "Automatic search for better traffic rules (evolutionary, on all cores)",
    "Report": "Results of the last batch or exploration, and older runs",
    "Scenario": "Save/load scenarios and apply the tuning to the real game",
    "Run": "Density, time of day, duration, time step and seeds", "Drivers": "How drivers accelerate, follow, wait and change lanes",
    "Junctions": "Junction approach, claims and priority", "Signals": "Traffic light timing for all junctions",
    "Roads": "Speed limits per road class", "Fleet": "Vehicle type mix", "Transit": "Buses and trains",
    "Emergency": "Ambulances, fires, breakdowns and sirens", "Advanced": "Every other traffic constant and rule switch found in the game",
    # common buttons
    "Reset this tab to the game's values": "Put every slider on this tab back to what the game uses now",
    "Follow (F)": "Keep the camera on this vehicle", "Unfollow (F)": "Stop following the vehicle",
    "Break down here": "This car stops for 'breakdown time' seconds where it is",
    "Close road": "No car may enter this road (removed from the drive graph)", "Reopen road": "Let traffic use this road again",
    "Back to the game's plan": "Forget the custom signal plan of this junction",
    "Lights off (priority rules instead)": "Switch this junction's lights off; drivers use priority rules",
    "Offset (s)": "Delay of this junction's cycle start, for green waves", "Major green (s)": "Green time of the main road",
    "Cycle (s)": "Length of one full signal cycle", "clear": "Remove all scheduled incidents",
    "Whole map": "Set the study area to the whole map (batches cut it into 700 m tiles)",
    "Back to one tile here": "Shrink the study area to one tile around the current view",
    "x": "Remove this entry",
    "Add variant = current settings": "Add a batch variant with the settings as they are now in the sliders",
    "Reset to one baseline": "Clear the variants; keep only the game's own settings",
    "Sweep last slider": "Turn the slider you last moved into a sweep (5 values between 20 % and 80 % of its range)",
    "Cancel": "Stop / close without changing anything", "Run batch": "Start every variant x seed x tile run on all cores",
    "Stop (then validate the best so far)": "End the search early; the best candidates are still re-tested on fresh seeds",
    "Start exploring": "Start the search with the options below",
    "Load into lab": "Put this candidate's settings in the sliders to watch it live",
    "Apply to game ...": "Write these settings to traffic_tuning.json so the real game uses them (asks first)",
    "Open the validation report": "Open the HTML report of the fresh-seed re-test in the browser",
    "Open the full HTML report": "Charts, confidence intervals, heatmaps and per-tile tables in the browser",
    "all": "Vary every listed parameter", "none": "Vary none of the listed parameters",
    "Save scenario": "Save settings, closures, obstacles, incidents and study area to a file",
    "New (game defaults)": "Start over from the game's current values",
    "Remove game tuning": "Delete traffic_tuning.json: the game goes back to its built-in values",
    "Load the game's current tuning into the lab": "Read traffic_tuning.json into the sliders",
    "Yes": "Confirm", "Close": "Close this window",
    # explore
    "Efficiency": "Weight of the efficiency score (throughput, delay, jams)", "Safety": "Weight of the safety score (collisions, near misses, red runs)",
    "Speed": "Weight of the average speed score",
    "Candidates per generation": "How many rule sets each generation tests", "Generations": "How many rounds of keep-best, mutate and cross",
    "Elite kept": "Best candidates kept as parents for the next generation", "Seeds per candidate": "Runs per candidate; more = fairer but slower",
    "Fresh validation seeds": "Re-test runs of the finalists on seeds nobody was selected on (overfitting guard)",
    "Finalists validated": "How many of the best candidates get the fresh-seed re-test",
    "Informed start (around the game's values)": "On: first guesses are near the game's values. Off: uniformly random, wilder ideas",
    # layers
    "Road class": "Colour roads by class (motorway, primary ...)", "Speed / limit": "Current speed as a share of the limit, red = slow",
    "Density": "Vehicles per km", "Standing heat": "Where cars stood still the longest", "Conflicts": "Where collisions and near misses happened",
    "Junction LOS": "Level of service A-F per junction from control delay", "Lanes": "Lane count per road",
    "Type": "Vehicle colour = type", "Standing time": "Vehicle colour = how long it has been stopped", "Driver pace": "Vehicle colour = driver aggression",
}
SLIDER_HOW = "Drag or mouse wheel to change, right click to reset. The tick marks the game's value; the label turns orange when changed."


def tip(label):
    s = str(label)
    if s in TIPS:
        return TIPS[s]
    for k, v in TIPS.items():
        if len(k) > 3 and s.startswith(k):
            return v
    return ""
