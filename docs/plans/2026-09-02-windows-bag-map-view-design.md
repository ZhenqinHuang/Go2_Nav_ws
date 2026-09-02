# Windows Bag Map View Design

## Goal

Use the complete Fast-LIO registered point cloud as a dim static background,
then show the current scan and cumulative robot trajectory as playback advances.

## Design

Before opening the window, the viewer makes one read-only pass over
`/record/cloud_registered` and combines all registered scans into the final map.
The 3D panel renders that map once in dim gray. During playback, the current scan
is highlighted in orange-yellow and `/fastlio_path` is drawn from its first pose
through the current message in green.

The map determines fixed 3D limits at startup. Axes, ticks, labels, panes, and
grid are hidden, so playback never changes scale or shifts the view. RGB and
depth behavior remains unchanged. No new topics or output files are introduced.

