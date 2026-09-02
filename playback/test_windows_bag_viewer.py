import struct
import unittest
from types import SimpleNamespace

import numpy as np

from playback.windows_bag_viewer import image_array, path_xyz, pointcloud_xyz


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


if __name__ == "__main__":
    unittest.main()
