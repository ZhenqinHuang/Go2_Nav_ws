from setuptools import setup


setup(
    name="leakage_bringup",
    version="0.0.1",
    packages=["leakage_bringup"],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/leakage_bringup"]),
        ("share/leakage_bringup", ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    entry_points={
        "console_scripts": [
            "record_relay = leakage_bringup.record_relay:main",
            "trajectory_recorder = leakage_bringup.trajectory_recorder:main",
            "leakage_detector = leakage_bringup.leakage_detector:main",
        ]
    },
)
