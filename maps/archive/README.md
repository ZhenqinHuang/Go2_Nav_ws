# 历史地图归档

此目录保存由 `scripts/map_bundle.py promote` 归档的历史地图包，不参与当前导航启动。

- 当前生效地图始终是 `maps/` 根目录下的 `MID360.pcd`、`MID360_map.pgm`、`MID360_map.yaml` 和 `map_manifest.yaml`。
- 历史地图文件体积较大，默认不提交 Git；需要长期保留时应使用独立制品存储或离线备份。
- 恢复历史地图时，先复制到 `maps/staging/<session>/`，完成 Manifest 校验后再执行原子切换。
