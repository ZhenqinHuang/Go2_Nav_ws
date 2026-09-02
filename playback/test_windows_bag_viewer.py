import struct
import unittest
from types import SimpleNamespace

import numpy as np

from playback.windows_bag_viewer import (
    axis_bounds,
    build_parser,
    combine_cloud_frames,
    height_colors,
    image_array,
    incremental_entity_path,
    mask_rgba,
    path_xyz,
    pointcloud_xyz,
    rerun_blueprint,
    select_depth_topic,
    validate_topics,
)


class DecoderTest(unittest.TestCase):
    def test_decodes_pointcloud_xyz(self):
        fields = [
            SimpleNamespace(name="x", offset=0, datatype=7, count=1),
            SimpleNamespace(name="y", offset=4, datatype=7, count=1),
            SimpleNamespace(name="z", offset=8, datatype=7, count=1),
        ]
        data = struct.pack("<fffIfffI", 1.0, 2.0, 3.0, 0, 4.0, 5.0, 6.0, 0)
        message = SimpleNamespace(
            fields=fields,
            data=data,
            point_step=16,
            width=2,
            height=1,
            is_bigendian=False,
        )

        np.testing.assert_allclose(
            pointcloud_xyz(message),
            [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]],
        )

    def test_decodes_rgb_image(self):
        message = SimpleNamespace(
            encoding="rgb8",
            height=1,
            width=2,
            step=6,
            data=bytes([255, 0, 0, 0, 255, 0]),
        )

        image = image_array(message)

        self.assertEqual(image.shape, (1, 2, 3))
        np.testing.assert_array_equal(image[0, 1], [0, 255, 0])

    def test_decodes_depth_image(self):
        message = SimpleNamespace(
            encoding="16UC1",
            height=1,
            width=2,
            step=4,
            data=struct.pack("<HH", 1000, 2500),
        )

        np.testing.assert_array_equal(image_array(message), [[1000, 2500]])

    def test_decodes_mono_mask(self):
        message = SimpleNamespace(
            encoding="mono8", height=1, width=2, step=2, data=bytes([0, 255])
        )

        np.testing.assert_array_equal(image_array(message), [[0, 255]])

    def test_extracts_path_xyz(self):
        poses = [
            SimpleNamespace(
                pose=SimpleNamespace(
                    position=SimpleNamespace(x=1.0, y=2.0, z=3.0)
                )
            ),
            SimpleNamespace(
                pose=SimpleNamespace(
                    position=SimpleNamespace(x=4.0, y=5.0, z=6.0)
                )
            ),
        ]

        np.testing.assert_allclose(
            path_xyz(SimpleNamespace(poses=poses)),
            [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]],
        )


class TopicValidationTest(unittest.TestCase):
    def test_prefers_aligned_depth_and_falls_back_to_raw_depth(self):
        aligned = "/camera/aligned_depth_to_color/image_raw"
        raw = "/camera/depth/image_rect_raw"

        self.assertEqual(select_depth_topic({raw, aligned}), aligned)
        self.assertEqual(select_depth_topic({raw}), raw)

    def test_parses_rerun_and_legacy_modes(self):
        parser = build_parser()

        default = parser.parse_args(["bag"])
        legacy = parser.parse_args(["bag", "--legacy"])
        saved = parser.parse_args(["bag", "--save", "session.rrd"])

        self.assertFalse(default.legacy)
        self.assertTrue(legacy.legacy)
        self.assertEqual(saved.save.name, "session.rrd")

    def test_rejects_missing_required_topic(self):
        with self.assertRaisesRegex(ValueError, "/fastlio_path"):
            validate_topics(
                {
                    "/record/cloud_registered",
                    "/camera/color/image_raw",
                    "/camera/depth/image_rect_raw",
                }
            )


class ViewMathTest(unittest.TestCase):
    def test_builds_transparent_red_leakage_overlay(self):
        overlay = mask_rgba(np.asarray([[0, 255]], dtype=np.uint8))

        np.testing.assert_array_equal(overlay[0, 0], [255, 0, 0, 0])
        np.testing.assert_array_equal(overlay[0, 1], [255, 0, 0, 150])

    def test_builds_two_map_tabs(self):
        blueprint = rerun_blueprint()
        tabs = blueprint.root_container.contents[0]

        self.assertEqual(type(blueprint.root_container).__name__, "Horizontal")
        self.assertEqual(type(tabs).__name__, "Tabs")
        self.assertEqual(
            [view.name for view in tabs.contents], ["Complete map", "Incremental map"]
        )

    def test_builds_bounded_height_colors(self):
        colors = height_colors(
            np.asarray([[0.0, 0.0, 0.0], [0.0, 0.0, 10.0]]), brightness=0.5
        )

        self.assertEqual(colors.dtype, np.uint8)
        self.assertEqual(colors.shape, (2, 3))
        np.testing.assert_array_equal(colors, [[0, 38, 20], [128, 90, 18]])

    def test_builds_unique_incremental_entity_path(self):
        self.assertEqual(
            incremental_entity_path(12), "/incremental/map/frame_000012"
        )

    def test_combines_registered_cloud_frames(self):
        combined = combine_cloud_frames(
            [
                np.asarray([[1.0, 2.0, 3.0]]),
                np.asarray([[4.0, 5.0, 6.0], [7.0, 8.0, 9.0]]),
            ]
        )

        np.testing.assert_allclose(
            combined,
            [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]],
        )

    def test_combines_cloud_and_path_bounds(self):
        center, radius = axis_bounds(
            np.asarray([[0.0, 0.0, 0.0], [2.0, 4.0, 6.0]]),
            np.asarray([[-2.0, 1.0, 3.0]]),
        )

        np.testing.assert_allclose(center, [0.0, 2.0, 3.0])
        self.assertEqual(radius, 3.0)

    def test_uses_default_bounds_without_points(self):
        center, radius = axis_bounds(np.empty((0, 3)), np.empty((0, 3)))

        np.testing.assert_array_equal(center, [0.0, 0.0, 0.0])
        self.assertEqual(radius, 1.0)


if __name__ == "__main__":
    unittest.main()
