from glob import glob
import os

from setuptools import find_packages, setup


package_name = "go2_control_gateway"


def data_files_for(directory):
    files = [path for path in glob(os.path.join(directory, "*")) if os.path.isfile(path)]
    if not files:
        return []
    return [(os.path.join("share", package_name, directory), files)]


setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=("test",)),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        *data_files_for("config"),
        *data_files_for("launch"),
        *data_files_for("systemd"),
    ],
    package_data={package_name: ["web/*"]},
    include_package_data=True,
    install_requires=["setuptools", "aiohttp>=3.8"],
    zip_safe=False,
    maintainer="wangzheie",
    maintainer_email="wangzheie@example.com",
    description="Fail-closed external-to-internal control gateway for Unitree Go2.",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={"console_scripts": []},
)
