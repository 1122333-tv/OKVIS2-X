# VIO 确定性随机采样实施与验证

## 目标与边界

从 `48ca9d2` 创建 `feat/vio-deterministic-sampling`。仅固定视觉 RANSAC 采样，不改变线程、门限、迭代数、帧调度或输入。保持四相机纯 VIO，关闭回环与 final BA；不承诺轨迹逐位相同。

## 实施步骤

1. 同步应用和 Python pipeline 支持 `--deterministic`、`--deterministic 1`、`--deterministic 0`，默认关闭。兼容原位置参数、`-rpg`、`--imu-support-ns`。
2. FrontendParameters 增加默认关闭的字段，初始化时传给 Frontend；三个 Frame SAC 封装及索引重载转发 OpenGV 的 randomSeed，关闭随机播种时每个实例使用 12345u。覆盖 2D–2D、3D–2D、纯旋转及回环几何验证。
3. manifest、启动日志、报告记录实际模式、种子和作用范围。复用父运行时继承，显式参数覆盖；历史缺省为关闭。不修改第三方源码。
4. 测试采样序列、构造默认行为、参数兼容、继承及转发，完成 Release 构建。
5. 固定二进制和原异常录制，从起点顺序执行关闭/开启各三次。比较轨迹、覆盖率、APE、44–55 s 与 63–66 s RPE 和耗时。采样复现与精度改善分开报告。
6. 实现与测试、文档与实验结论分别提交，不推送、不合并。

## 运行方式

```bash
cmake --build build-vio --target okvis_app_synchronous -j2
python scripts/run_vio_pipeline.py --from-run ORIGINAL_RUN --step all --deterministic 1 --run-name deterministic_on
# 将 1 改为 0 进行关闭对照；每次创建独立 run。
```

## 验收

相同候选对应关系与顺序下采样序列一致；默认行为兼容；配置与二进制来源完整；记录全部六次运行，不能按结果挑选种子。仍有轨迹差异时明确记录，不追加串行化。保留 DBoW2、opengv 已有脏状态。

## 已实现接口

```bash
# 在 OKVIS2-X 根目录，位置参数写在开关前。
build-vio/okvis_app_synchronous CONFIG DATASET OUTPUT --deterministic
build-vio/okvis_app_synchronous CONFIG DATASET OUTPUT --deterministic 1
build-vio/okvis_app_synchronous CONFIG DATASET OUTPUT --deterministic 0

# 原工程入口会转发参数；from-run 未指定开关时继承父运行。
python scripts/run_vio_pipeline.py --from-run ORIGINAL_RUN --step all --deterministic 1
```

直接应用未传开关时关闭。Python `--from-run` 继承父运行的 `sampling`，旧 manifest 缺省关闭；显式 `0` 关闭并覆盖继承。为兼容历史可执行文件，关闭时 pipeline 不追加新参数。仅比较或重做报告时拒绝传该开关，防止重标已有轨迹。

`sampling` 记录 `deterministic`、`seed`、`scope=visual_ransac_only`、`thread_settings_changed=false`。启动日志以 `SAMPLING` 开头。报告首页显示模式，报告 JSON 保留该记录。

OpenGV 已有的 `randomSeed=false` 在每个 SAC 实例中使用 `12345u`，并在实例内持续推进随机数序列。没有共享全局随机数发生器。相同输入顺序与候选集合是采样一致的前提；若上游结果不同，固定种子不会使不同候选集合自动一致。Basalt 同时有逐帧等待状态输出的控制，本次不移植该调度逻辑。

## 构建与测试命令

```bash
cmake -S . -B build-vio -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTS=ON
cmake --build build-vio --target okvis_app_synchronous okvis_deterministic_sampling_test okvis_ceres_test -j2
build-vio/okvis_frontend/okvis_deterministic_sampling_test
build-vio/okvis_ceres/okvis_ceres_test --gtest_filter='*ImuError:*ReprojectionError:*PoseError:*HomogeneousPointError'
/home/yuewang/.local/share/pipx/venvs/evo/bin/python -m unittest discover -s scripts -p 'test_*.py'
build-vio/okvis_app_synchronous --imu-support-ns
git diff --check
```

本轮 Release 构建通过；三类封装的普通/索引构造共六组各 100 次抽样一致，默认构造保留时间播种；35 项 Python 测试及 4 项现有 Ceres 测试通过。`--imu-support-ns` 仍输出 `20000000`。构建沿用 `USE_NN=OFF`、`USE_GPU=OFF`、`BUILD_ROS2=OFF`。

实现提交：`52ecc06`。实验使用该提交构建的冻结二进制，原始历史轨迹只作为输入和评估口径来源，新的关闭模式三次运行才是本轮对照基线。

## 实验产物与复现

产物目录：`results/deterministic_sampling/`，不提交二进制或运行输出。`provenance.json` 记录提交、二进制和依赖；`initial_submodules.json` 记录两处已有子模块改动。`input_sha256.json` 对 9,608 张图像、四路索引和 IMU 文件逐一记录内容哈希；实验结束再次核对。

`commands.json` 保存六条完整命令；`completed.json` 保存实际 run 和逐次窗口评估命令；`queue.log`、`pipeline_*.log`、`analysis_*.log` 保留运行日志。分析器从漂移调查分支原样导出，来源与哈希记录在 `provenance.json`；不导入该分支的估计器改动。

```bash
# 使用冻结二进制与原输入，生成新 run；0/1 各重复三次，顺序执行。
PYTHON_BIN=/home/yuewang/.local/share/pipx/venvs/evo/bin/python
for mode in 0 1; do
  for repeat in 1 2 3; do
    "$PYTHON_BIN" scripts/run_vio_pipeline.py \
      --from-run results/20260916_142602_203941_DOHC2_validation_01/run_20260922T172208_vio_4b5dd4 \
      --step all --deterministic "$mode" --run-name "sampling_${mode}_repeat${repeat}" \
      --binary results/deterministic_sampling/binary/okvis_app_synchronous \
      --output results/deterministic_sampling/runs
  done
done
```

APE 为全程 SE(3) 对齐，无尺度拟合。RPE 使用原运行共同 GT 帧对，以首输入帧为零点，按帧对终点归属窗口；跨窗口帧对保留并标注。六次运行必须都覆盖 2,402 个输出时间戳、2,401 个共同评估时间戳，RPE 帧对哈希相同。线程配置及算法 YAML 的有效哈希必须一致。

运行耗时仅作描述：主机其他任务和文件缓存没有受控。固定种子后的单次精度改善不能作为根因已解决的证据。

## 六次完整回放结果（2026-09-30）

六次均输出 **2,402 帧**，共同评估 **2,401 帧**，输出时间戳与历史基线逐项一致。算法有效配置、二进制和各项 RPE 帧对哈希均相同。9,613 个输入文件（含 9,608 张图像）在实验前后内容哈希一致。四相机、并行检测、4 个匹配线程、3 个实时求解线程均保持原配置；回环及 final BA 关闭，`enforce_realtime=false`。

| 模式 / 次数 | APE RMSE (m) | 44–55 s RPE RMSE / p95 / max (cm) | 63–66 s RPE RMSE / p95 / max (cm) | 耗时 (s) |
|---|---:|---:|---:|---:|
| 关闭 1 | 29.377241 | 13.432 / 33.139 / 40.561 | 116.157 / 162.495 / 170.093 | 370.2 |
| 关闭 2 | 142.597190 | 206.750 / 406.284 / 456.442 | 503.968 / 680.983 / 711.384 | 386.2 |
| 关闭 3 | 0.800410 | 15.022 / 31.368 / 68.732 | 2.187 / 5.001 / 5.834 | 358.3 |
| 开启 1 | 2.518778 | 19.189 / 46.039 / 53.157 | 1.598 / 3.179 / 3.966 | 451.8 |
| 开启 2 | 41.565378 | 31.709 / 73.815 / 81.148 | 160.827 / 221.471 / 231.061 | 398.3 |
| 开启 3 | 0.261926 | 12.297 / 24.165 / 62.521 | 0.773 / 1.661 / 1.816 | 370.3 |

### 重复性范围

以下均为三次结果的最小值–最大值，不是置信区间。

| 模式 | APE RMSE (m) | 44–55 s RPE RMSE (cm) | 63–66 s RPE RMSE (cm) | 耗时 (s) |
|---|---:|---:|---:|---:|
| 关闭 | 0.800–142.597 | 13.432–206.750 | 2.187–503.968 | 358.288–386.207 |
| 开启 | 0.262–41.565 | 12.297–31.709 | 0.773–160.827 | 370.295–451.804 |

### 开启模式的轨迹一致性

下表比较同一时间戳的原始输出位姿，不额外对齐两条轨迹。三对 CSV 均非逐字节一致。

| 开启模式比较 | 最大位置差 (m) | 最大旋转差 (°) | 首次位置差 > 1e-8 m 的时间 (s) |
|---|---:|---:|---:|
| 1 vs 2 | 165.469667 | 3.399841 | 0.066668 |
| 1 vs 3 | 6.115114 | 2.165180 | 0.066668 |
| 2 vs 3 | 170.541715 | 3.624588 | 0.100002 |

`1e-8 m` 是检测数值差异的阈值，不是物理漂移起点或根因事件判定。

### 证据结论与边界

- **已验证**：三类 SAC 封装使用固定种子时，对相同候选索引及顺序给出相同抽样序列；六次启动日志与 manifest 的实际模式一致，CLI、默认行为及来源记录通过验证。
- **未实现全流程复现**：开启三次的 APE RMSE 仍为 2.519 / 41.565 / 0.262 m；固定 RANSAC 种子不足以消除本录制的运行差异。
- **未证明精度修复**：虽然开启组部分指标较好，44–55 s 的三次 RPE RMSE 中位数由关闭组约 15.02 cm 变为开启组约 19.19 cm；不能选择最好一次宣称稳定改善。
- **尚未定位**：本次没有证据将剩余差异具体归因于数据竞争、候选对应关系顺序、异步调度或求解数值变化。固定种子不保证实际每帧的候选集合相同。本轮没有追加串行化或其他参数修改。
- 工程验收完成的是采样开关、兼容性及可审计实验；原局部漂移问题仍未解决。

### 产物索引

冻结二进制 SHA-256：`50b0c4e33ba833fa4af35255078df555bb1b367232f2fcf787ae43bacb919422`。两处子模块的 HEAD 与工作区补丁 SHA-256 在实验前后相同。

| 模式 / 次数 | 完整 run ID 与报告 |
|---|---|
| 关闭 1 | [run_20260930T141520_sampling_0_repeat1_9e49a1](/home/yuewang/Project/VSLAM/four_fisheye_rig/OKVIS2-X/results/deterministic_sampling/runs/run_20260930T141520_sampling_0_repeat1_9e49a1/report/index.html) |
| 关闭 2 | [run_20260930T142156_sampling_0_repeat2_565f36](/home/yuewang/Project/VSLAM/four_fisheye_rig/OKVIS2-X/results/deterministic_sampling/runs/run_20260930T142156_sampling_0_repeat2_565f36/report/index.html) |
| 关闭 3 | [run_20260930T142850_sampling_0_repeat3_ec685b](/home/yuewang/Project/VSLAM/four_fisheye_rig/OKVIS2-X/results/deterministic_sampling/runs/run_20260930T142850_sampling_0_repeat3_ec685b/report/index.html) |
| 开启 1 | [run_20260930T143514_sampling_1_repeat1_9411a9](/home/yuewang/Project/VSLAM/four_fisheye_rig/OKVIS2-X/results/deterministic_sampling/runs/run_20260930T143514_sampling_1_repeat1_9411a9/report/index.html) |
| 开启 2 | [run_20260930T144313_sampling_1_repeat2_19ac31](/home/yuewang/Project/VSLAM/four_fisheye_rig/OKVIS2-X/results/deterministic_sampling/runs/run_20260930T144313_sampling_1_repeat2_19ac31/report/index.html) |
| 开启 3 | [run_20260930T145016_sampling_1_repeat3_a50390](/home/yuewang/Project/VSLAM/four_fisheye_rig/OKVIS2-X/results/deterministic_sampling/runs/run_20260930T145016_sampling_1_repeat3_a50390/report/index.html) |

各运行的 `window_analysis/` 包含 RPE 帧对起止时间、平移/旋转误差及跨窗口标记；同时保留 0.5/1 m、0.1/1 s 和正常区间指标。

- [六次完整指标与轨迹对照 JSON](/home/yuewang/Project/VSLAM/four_fisheye_rig/OKVIS2-X/results/deterministic_sampling/summary.json)
- [可复现运行命令](/home/yuewang/Project/VSLAM/four_fisheye_rig/OKVIS2-X/results/deterministic_sampling/commands.json)
- [逐次窗口评估命令](/home/yuewang/Project/VSLAM/four_fisheye_rig/OKVIS2-X/results/deterministic_sampling/completed.json)
- [构建与二进制来源](/home/yuewang/Project/VSLAM/four_fisheye_rig/OKVIS2-X/results/deterministic_sampling/provenance.json)
- [输入内容复核](/home/yuewang/Project/VSLAM/four_fisheye_rig/OKVIS2-X/results/deterministic_sampling/input_preservation.json)
- [子模块改动保留证明](/home/yuewang/Project/VSLAM/four_fisheye_rig/OKVIS2-X/results/deterministic_sampling/submodule_preservation.json)
- [报告图片嵌入检查](/home/yuewang/Project/VSLAM/four_fisheye_rig/OKVIS2-X/results/deterministic_sampling/report_images_verified.json)

六份 HTML 报告各有 53 张嵌入 PNG，合计 318 张，已通过 Base64 解码与 PNG 完整性检查；放大查看器的隐藏占位图片由点击事件填充，不作为缺图计数。图表读取无需依赖外部图片路径。
