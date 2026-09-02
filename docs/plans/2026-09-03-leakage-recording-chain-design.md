# Leakage Recording Chain Design

## Goal

Record one ROS 2 session containing replayable Fast-LIO registered point clouds,
odometry/path, D435i RGB, and D435i depth while retaining raw Livox data for
later SLAM reprocessing.

## Chosen approach

Reuse the running `trajectory_recorder` relay. Record its
`/record/cloud_registered` and `/record/odometry` outputs alongside
`/fastlio_path`, raw Livox, TF, RGB, depth, camera info, and metadata. Pass the
existing QoS override file directly to rosbag2. The preflight must receive a
path, registered cloud, RGB frame, and depth frame before recording starts.

This avoids a second recorder node and keeps raw data available without making
the Windows viewer decode Livox custom messages.

## Verification

Static tests enforce the topic list, QoS option, and point-cloud preflight.
After deployment, restart the relay to clear its old path, run the live
preflight, record a bounded session, close rosbag2 with SIGINT, and inspect bag
topic counts before transfer.
