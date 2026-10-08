# run_vio_pipeline.py 中文使用说明

入口与示例更新：2026-10-08。适用仓库：`/home/yuewang/Project/VSLAM/four_fisheye_rig/OKVIS2-X`。

本入口运行四目离线 OKVIS VIO，复用已有 Basalt run 的预处理数据、Basalt 轨迹和 IMU 真值，输出对比评测及自包含 HTML 报告。入口调用 `vio_pipeline_common.main()`，本文依据当前源码与 `--help`。

完整流水线统一通过 `scripts/run_vio_pipeline.py` 启动。新运行显式传入 `--calibration-dir`，算法模板通过 `--config` 选择；解释器由调用命令指定。

本文结构参考 [Basalt VIO 使用说明](/home/yuewang/Project/VSLAM/four_fisheye_rig/basalt-monado/doc/run_vio_pipeline使用说明.md)，但两个入口的参数、阶段和复用规则不同。

## 🧭 功能与流程

```mermaid
flowchart LR
    accTitle: OKVIS VIO 评测流程
    accDescr: 从已有 Basalt 运行读取准备数据及参考轨迹，转换标定和掩膜后运行 OKVIS，再评测并生成报告。
    prepare["01 输入检查与标定转换"] --> reference["02 导入 Basalt 与 GT"]
    reference --> vio["03 OKVIS VIO"]
    vio --> compare["04 轨迹对比"]
    compare --> report["report HTML 报告"]
```

- 没有 `--dataset` 参数：数据包身份及准备数据路径来自 `--basalt-run`。
- 不重新运行 Basalt，也不重新估计 mocap 时间偏移。GT 原样导入。
- `prepare`、`reference`、`vio`、`compare` 是处理阶段；`report` 是报告生成阶段。`reference` 不能单独通过 `--step` 选择。
- 除 `--step report` 外，每次调用创建新 run；不会在失败 run 中续跑。

## 📦 输入与运行前提

| 输入 | 要求 |
| --- | --- |
| Basalt run | 包含 `manifest.yaml`，`prepare`、`gt`、`vio` 阶段均为 `complete` 或 `reused`；即使本次只做 prepare，也必须满足 |
| 准备数据 | 四路 `cam0`～`cam3` CSV 时间戳完全一致、严格递增，图像存在且分辨率匹配标定；IMU CSV 为七列有限数值 |
| 参考轨迹与 GT | Basalt 轨迹和 GT 时间有交集；GT 旁的 `conversion.json` 包含 `valid_segments_ns` |
| 标定交付 | 至少 `calibration.json`、`export_manifest.json`；schema 1，物理相机顺序为 cam0～cam3，声明时间参考相机 |
| 相机模型 | 当前转换器仅支持完整四目 KB4；对有效掩膜区域执行模型兼容性审计 |
| IMU 标定 | 当前转换器要求 `calib_accel_bias`、`calib_gyro_bias` 修正数组全零；四类三轴噪声参数均为正、各向同性 |
| 掩膜 | Basalt run 中启用并保存的掩膜，或显式 `--camera-mask-dir`；必须有四张同分辨率 PNG |
| 二进制 | 默认 `build-vio/okvis_app_synchronous`，支持 `--imu-support-ns`；prepare 阶段就会调用它 |
| 构建环境 | prepare 会现场编译相机审计程序，需要 `c++`、Eigen、OpenCV 开发文件和 `pkg-config opencv4` |
| Python | NumPy、Pillow、PyYAML、Matplotlib、evo；交互 evo 窗口另需 Qt 后端 |

本入口不要求重新提供原始 mocap 录制或 mocap 标定来生成 GT，但不会自动证明本次交付与导入 GT 的物理 IMU 坐标系、marker–IMU 外参完全一致。

数据集仍通过符号链接引用 Basalt 准备目录及原始图像。保留这些目录和挂载；不能仅复制一个 OKVIS run 就假定完全独立。

## 🚀 完整运行示例

### 选择 Python 与构建程序

本机现有 evo 环境能加载入口所需依赖。以下变量供后续同一终端中的命令复用：

```bash
cd /home/yuewang/Project/VSLAM/four_fisheye_rig/OKVIS2-X
export PYTHON_BIN=/home/yuewang/.local/share/pipx/venvs/evo/bin/python
export BASALT_RUN=/home/yuewang/Project/VSLAM/four_fisheye_rig/basalt-monado/results/20260921_171047_017923_DOHC2_debug/run_20260922T105652_d91c1b
export CALIBRATION_DIR=/mnt/Datasets/VSLAM_benchmark/v0.1/OAK4pNew/Layout_0921/calibration
export MASK_DIR=/home/yuewang/Project/VSLAM/four_fisheye_rig/OKVIS2-X/config/oak4p/layout0921_masks

"$PYTHON_BIN" scripts/run_vio_pipeline.py --help
```

需要首次构建或源码变更后重编译时：

```bash
BUILD_JOBS=8 bash scripts/build_vio.sh
```

该脚本构建 Release CPU 版本并复制词袋文件。Python 依赖版本记录在 `scripts/requirements-vio.txt`；其他机器需要自己的可用 Python 环境，不能直接沿用本机解释器路径。evo 可执行文件应位于所选 Python 解释器同一 `bin` 目录。直接运行 `python3` 时，环境可能缺少 NumPy。

### 跑完整 Layout0921 数据

下面使用已生成的 Layout0921 掩膜。目录不存在时，先执行后面的“生成标定专用掩膜”。

```bash
"$PYTHON_BIN" scripts/run_vio_pipeline.py \
  --basalt-run "$BASALT_RUN" \
  --calibration-dir "$CALIBRATION_DIR" \
  --config /home/yuewang/Project/VSLAM/four_fisheye_rig/OKVIS2-X/config/oak4p/layout0916_vio.yaml \
  --camera-mask-dir "$MASK_DIR" \
  --step all \
  --run-name layout0921_full \
  --vio-max-frames 0
```

参考 Basalt run 对应数据包 `/mnt/Datasets/VSLAM_benchmark/v0.1/OAK4pNew/Layout_0921/20260921_171047_017923_DOHC2_debug`。模板名中的 `layout0916` 不表示使用旧标定：四目内外参、IMU 噪声、相机时间偏移由 `--calibration-dir` 注入。

默认无 GUI。需要实时窗口时追加 `--show-gui`；需要结束后打开 evo 评测窗口时追加 `--evo-show-gui`。两者相互独立。

### 恢复策略的两种运行模式

以下两个模板均启用 `visual_recovery: true`、`huber_loss_scale: 5.0`，保持 10 次迭代、四相机纯 VIO、关闭实时超时限制、回环及 final BA。该策略是有效缓解，未通过全部局部精度验收。

| 模式 | `config/oak4p/` 下的模板 | 配套 CLI | 检测 | 匹配线程 | 实时求解线程 |
| --- | --- | --- | --- | ---: | ---: |
| 稳定复现 | `layout0916_vio_recovery_deterministic.yaml` | `--deterministic 1` | 串行 | 1 | 1 |
| 正常运行 | `layout0916_vio_recovery.yaml` | `--deterministic 0` | 并行 | 4 | 3 |

`--deterministic` 仍是命令行选项，不由 YAML 文件名自动启用。两个模板的算法内容只在上述三个线程设置上不同；物理标定及 `image_delay` 由流水线注入。未启用的全图优化线程仍保留 3，不参与本轮纯 VIO 运行。正常模式不承诺逐帧复现；下方记录了两段录制各一次 GUI 回放，不代表重复运行的精度范围已验证。

历史 `layout0916_vio.yaml` 和 `layout0916_vio_debug.yaml` 均未启用上述恢复策略，分别保留原并行基线和原串行调试基线。

### 稳定复现模式与 GUI

以下使用当前 `build-vio/okvis_app_synchronous`。2026-10-08 核对时它与 2026-09-30 最终候选冻结二进制字节一致；后续重新编译后以新 run 保存的哈希为准。

```bash
cd /home/yuewang/Project/VSLAM/four_fisheye_rig/OKVIS2-X
BASE=results/20260916_142602_203941_DOHC2_validation_01/run_20260922T172208_vio_4b5dd4

/home/yuewang/.local/share/pipx/venvs/evo/bin/python scripts/run_vio_pipeline.py \
  --basalt-run ../basalt-monado/results/20260916_142602_203941_DOHC2_validation_01/run_20260918T151707_4586ee \
  --calibration-dir /home/yuewang/Project/Calib/calibration_workspace/runs/layout0916_DOHC2_joint_dynamic_01_retry01/delivery/vio/kalibr_handeye \
  --config config/oak4p/layout0916_vio_recovery_deterministic.yaml \
  --camera-mask-dir "$BASE/01_preparation/inputs/source_masks" \
  --run-name drift_recovery_gui \
  --step all --deterministic 1 --show-gui
```

切换正常运行模式时，将两处参数改为：

```bash
--config config/oak4p/layout0916_vio_recovery.yaml --deterministic 0
```

每次默认创建 `results/20260916_142602_203941_DOHC2_validation_01/run_<时间>_drift_recovery_gui_<随机ID>/`，轨迹保存在 `03_vio/outputs/`，评测在 `04_vio_comparison/`，嵌入图片的报告为 `report/index.html`。

2026-10-08 的 `run_20261008T144113_drift_recovery_gui_944d06` 使用原实验配置完成 GUI 回放，online/final/final-ba 三个文件与最终候选均字节一致。新稳定模板在注入相同标定和 mask 后与该配置等价；提取模板后未再次运行 VIO。系统库变化不应被推断为必然改变结果，跨环境复现仍需实际校验。

正常模式的已保存回放结果（均为共同帧、SE(3) 无尺度拟合）：

| 录制与新 run | 对照 | APE RMSE：对照 → 新运行 | VIO 耗时：对照 → 新运行 |
| --- | --- | --- | --- |
| Layout0916 `20260916_142602_203941_DOHC2_validation_01` / `run_20261008T145957_recovery_normal_gui_3a160e` | 当天稳定模式 `run_20261008T144113_drift_recovery_gui_944d06` | 7.138 → 5.408 cm | 461.98 → 347.93 s |
| Layout0921 `20260921_171047_017923_DOHC2_debug` / `run_20261008T151536_recovery_normal_gui_d550a0` | 历史普通模式 `run_20260923T103406_vio_dfd46d` | 5.200 → 8.261 cm | 190.71 → 188.05 s |

Layout0916 两次均输出 2402 帧、共同评估 2401 帧；Layout0921 均输出并评估 1195 帧。后者 0.5/1 m RPE RMSE 有所改善，但 APE 恶化 58.9%，不能称为整体精度提升。Layout0916 对照同时改变线程和随机采样；Layout0921 对照还使用不同历史二进制。均不是单变量、重复运行的因果验证。耗时只统计 VIO 进程，包含 GUI，不包括准备、评估和报告阶段。

## ⚙️ 全部命令行参数

共 **14 项选项**，包含帮助，别名合并计数。下表默认值指新运行。

| 参数 | 含义 | 默认值与限制 |
| --- | --- | --- |
| `-h` / `--help` | 显示帮助 | 不运行流水线，但入口导入依赖仍需可用 |
| `--basalt-run` | Basalt 参考 run 目录 | 新运行必填；不是 Basalt 仓库根目录 |
| `--calibration-dir` | 四目标定交付目录 | 新运行必填；没有默认标定环境变量 |
| `--from-run` | 复用已有 OKVIS run | 要求 `format: okvis-vio`、`version: 2`；不能传 Basalt run |
| `--output` | 结果父目录 | `OKVIS2-X/results/<数据包名称>`；不能位于原始数据、准备数据或 Basalt run 内部，也不能等于它们 |
| `--config` | OKVIS 算法 YAML 模板 | `config/oak4p/layout0916_vio.yaml`；不是 Basalt JSON |
| `--camera-mask-dir` | 覆盖从 Basalt run 选取的掩膜 | 默认读取 Basalt run；黑色有效、白色排除；没有掩膜时须显式提供 |
| `--step` | 阶段选择 | `all`、`prepare`、`vio`、`compare`、`report`；默认 `all` |
| `--run-name` | 新 run 名称中的标签 | `vio`；仅允许非空 ASCII 字母、数字、下划线和短横线；不是完整目录名 |
| `--show-gui` | OKVIS 实时窗口 | 默认关闭；只在本次实际执行 VIO 时生效 |
| `--evo-show-gui` | 交互评测窗口 | 默认关闭；仅 `all`、`compare` 完成后调用 |
| `--vio-max-frames` | 最多输入多少组四目图像 | 非负整数，`0` 为全段；未指定时继承旧 run 的 `vio.max_frames`，否则为 `0` |
| `--binary` | OKVIS 可执行文件 | 仓库 `build-vio/okvis_app_synchronous`；不从旧 run 继承；其目录还需匹配的 `CMakeCache.txt` 和词袋文件 |
| `--deterministic [0\|1]` | 固定视觉 RANSAC 采样种子为 12345 | 新运行默认关闭；单独传开关或传 `1` 开启，`0` 关闭；复用时未指定则继承。只控制采样，不改变线程；`compare`/`report` 不接受 |

`--show-gui`、`--evo-show-gui` 不附加数值；`--deterministic` 可带 `0` 或 `1`，不接受 `true`/`false`。本入口不接受 `--run-id`、`--save-times`、`--start-time`、`--reference-camera`、`--max-offset`、`--stereo-debug` 或任意 C++ 参数透传。

## 🔀 阶段选择与复用规则

| `--step` | 没有 `--from-run` | 指定 `--from-run` |
| --- | --- | --- |
| `all` | prepare → reference → vio → compare → report | 复用 prepare、reference，重新运行 vio → compare → report |
| `prepare` | prepare → reference | 复制并校验 prepare、reference，不重跑模型审计 |
| `vio` | 不支持 | 复用 prepare、reference，仅重跑 VIO，不自动评测 |
| `compare` | 不支持 | 复用 prepare、reference、vio，重做评测和报告 |
| `report` | 不支持 | 直接重生成原 run 的 `report/`；不创建新 run、不执行 VIO 或 evo |

1. `--from-run` 禁止同时传 `--basalt-run`、`--calibration-dir`、`--config`、`--camera-mask-dir`，即使值与旧 run 相同也会报错。修改这些输入应新开运行。
2. 被复用阶段必须完成，且实体产物 SHA-256 与原 manifest 一致；数据索引另外核对哈希。失败 run 中已经完整记录的前置阶段仍可复用。
3. 复用复制阶段目录，保留符号链接并调整指向旧 run 内部的链接；会占用额外空间。图像内容不重新计算全量哈希，新 prepare 检查图像存在性和尺寸。
4. GUI 开关不继承。帧数限制会继承；从短段 run 恢复全段须明确 `--vio-max-frames 0`。限制仅影响 VIO，不减少新 prepare 检查的图像数量。
5. 新运行名为 `run_<本机本地时间YYYYMMDDTHHMMSS>_<run-name>_<随机6位后缀>`；本机时区为 Asia/Shanghai。manifest 的开始／结束时间为 UTC。
6. `report` 是原地更新的例外：修改报告文件，不改变原 manifest 的运行状态或重新计算其中旧 report 阶段的哈希。最新报告生成记录看 `report/generation.json`。

## 🛠️ 常用操作

### 先验证 prepare，再跑完整 VIO

第一步会完成模型审计和参考导入：

```bash
"$PYTHON_BIN" scripts/run_vio_pipeline.py \
  --basalt-run "$BASALT_RUN" \
  --calibration-dir "$CALIBRATION_DIR" \
  --camera-mask-dir "$MASK_DIR" \
  --step prepare \
  --run-name layout0921_prepare
```

脚本会打印新目录。后续 `--from-run` 应填那个目录。下面用已有成功 prepare run 演示可复制命令：

```bash
"$PYTHON_BIN" scripts/run_vio_pipeline.py \
  --from-run /home/yuewang/Project/VSLAM/four_fisheye_rig/OKVIS2-X/results/20260921_171047_017923_DOHC2_debug/run_20260922T184259_layout0921_domain_prepare_3f91cc \
  --step all --run-name layout0921_retry --vio-max-frames 0 --show-gui
```

### 短段检查

在上一条复用命令中改为 `--step vio --vio-max-frames 300`，只运行前 300 组，不自动评测。输出位姿数量仍以 `trajectory_summary.json` 为准。

### 只重做评测

```bash
"$PYTHON_BIN" scripts/run_vio_pipeline.py \
  --from-run /home/yuewang/Project/VSLAM/four_fisheye_rig/OKVIS2-X/results/20260921_171047_017923_DOHC2_debug/run_20260922T184322_layout0921_domain_full_7b3d24 \
  --step compare --run-name compare_retry
```

### 只更新 HTML 报告

```bash
"$PYTHON_BIN" scripts/run_vio_pipeline.py \
  --from-run /home/yuewang/Project/VSLAM/four_fisheye_rig/OKVIS2-X/results/20260921_171047_017923_DOHC2_debug/run_20260922T184322_layout0921_domain_full_7b3d24 \
  --step report
```

报告支持展示不完整 run 的缺失项，不会通过补跑估计器来填充结果。也可直接使用 `scripts/generate_pipeline_report.py --run <OKVIS run目录>`。

## 🎭 掩膜与标定转换

### 黑白语义与时间偏移

- `--camera-mask-dir` 接收 **Basalt 语义**：灰度 `<=127` 有效，`>127` 排除。
- 转换后的 `01_preparation/outputs/masks/` 使用 **OKVIS 语义**：白色有效，黑色排除。不要把这个目录再次当成 Basalt 掩膜输入。
- `T_SC = T_imu_cam`，以物理 IMU 为传感器坐标系。
- 有效相机时间偏移为交付偏移加上 Basalt 准备阶段记录的帧组参考修正，必须等于准备数据记录的偏移。
- 自动设置 `image_delay = -cam_time_offset_ns / 1e9`，即 `t_imu = t_camera + cam_time_offset_ns`。不要再平移 CSV 时间戳。

### 生成标定专用掩膜

`Camera model compatibility gate failed` 可能说明旧掩膜保留了超出本次 KB4 可逆范围的像素。先读 `camera_models.json`，不能把“图像检查通过”当作模型审计通过，也不应直接关闭检查。

以下为 Layout0921 的生成命令。**只在输出目录尚不存在时执行**；要试其他余量，换一个新的输出目录，并同步更新 `MASK_DIR`。

```bash
"$PYTHON_BIN" scripts/make_kb4_domain_masks.py \
  --calibration "$CALIBRATION_DIR/calibration.json" \
  --source-mask-dir "$BASALT_RUN/01_preparation/inputs/camera_masks" \
  --output "$MASK_DIR" \
  --margin-px 2
```

脚本适用于四目 KB4：在原有效区域上取与第一单调、前向可逆分支的交集，默认保留 2 像素的保守径向余量。它只新增排除，不恢复原来遮掉的区域；生成后仍需运行 prepare 模型审计。

输出包括 `cam0.png`～`cam3.png`、`manifest.json` 和 `generator.py`。`generator.py` 是生成时源码快照，用于追溯；可复用入口是 `scripts/make_kb4_domain_masks.py`。本机 `config/oak4p/layout0921_masks/` 是已忽略的生成产物，不随 Git 分发。改变掩膜后若要进行相同有效视野下的算法比较，Basalt 也须使用相同有效区域重跑。

## 🖥️ GUI 与算法配置

`--show-gui` 开启原生 OpenCV 窗口，与 `--evo-show-gui` 不同。

| 窗口／元素 | 行为 |
| --- | --- |
| `OKVIS 2 Cameras` | 单窗口 2×2：上排 cam0/cam1，下排 cam2/cam3；原始分辨率拼接，窗口可缩放 |
| 图像大小 | 1280×800 四目加每格 32 像素标签栏，画布为 2560×1664；初始窗口约 1280×832；缩小显示仍会丢失可见细节，放大可查看原始像素 |
| 特征圆圈和短线 | 观测位置、尺度及特征方向；绿色为已初始化有限深度路标，黄色为尚未初始化分支 |
| 青色点与数字 | 路标重投影位置和 ID；连接观测点的线表示重投影残差 |
| `Keyframe` / Tracking 状态 | 关键帧着色，以及 good / marginal / lost 状态 |
| `OKVIS 2 Top View` | 独立、可缩放的 500×500 XY 俯视图；包含轨迹、路标、位置、速度和 IMU 偏置 |
| `s` 键 | 将俯视图保存为 VIO 输出目录下的 `saved.png` |
| evo 窗口 | `all` / `compare` 完成后逐项打开；关闭当前窗口才能继续 |

GUI 不改变估计输入分辨率，但有绘制、图像复制和显示开销。不要将旧版 640×400 预缩放实现的微基准视为当前原始分辨率拼接的端到端性能结果。当前 GUI 没有报告中的红绿 mask 叠加，也没有暂停／单步控制。

算法参数通过 `--config` 指定的 YAML 修改，例如特征数量、匹配线程数、关键帧窗口。默认模板为每路最多 1000 个关键点、5 个关键帧、3 个 IMU 帧。本入口要求以下设置关闭，不能用其运行 SLAM／在线标定：

- `estimator_parameters.do_loop_closures`、`do_final_ba`、`enforce_realtime`。
- `camera_parameters.online_calibration.do_extrinsics`、`do_extrinsics_final_ba`。
- `frontend_parameters.use_cnn`。

## 🌍 环境变量与路径规则

| 项目 | 当前行为 |
| --- | --- |
| `PYTHON_BIN` | 本文用作 shell 变量，必须通过 `"$PYTHON_BIN"` 启动；脚本内部对子进程设置为 `sys.executable` |
| `BUILD_JOBS` | 仅供 `build_vio.sh`，默认 8 |
| `MPLBACKEND` | 非交互子进程强制 `Agg`；交互 evo 使用 `QtAgg` |
| `OKVIS_FEATURE_AUDIT` | VIO 子进程设为 `1`，记录四路特征与排除区域审计 |
| 相对路径 | 用户传入的路径相对于启动时的当前工作目录解析；默认配置、二进制和结果根目录由脚本定位到仓库 |

自定义二进制应提供绝对路径。脚本不自动构建估计器；prepare 会单独编译审计程序。`--help` 成功不代表 C++ 构建、数据、模型和 GUI 环境都通过验证。

## 📂 结果目录与检查方法

| 路径（相对本次 run） | 内容 |
| --- | --- |
| `manifest.yaml` | 阶段状态、命令、参数、Git 状态、源码哈希、二进制和软件环境记录 |
| `provenance/` | 运行时 Python／审计程序源码与 vendor 快照 |
| `01_preparation/inputs/` | 标定交付、默认／用户算法模板、Basalt manifest 与准备记录 |
| `01_preparation/inputs/source_masks/` | 实际选用的原始掩膜，Basalt 语义 |
| `01_preparation/inputs/basalt_default_masks/` | 新 prepare 保存的 Basalt 默认掩膜快照；历史 run 可能没有 |
| `01_preparation/outputs/dataset` | 指向 Basalt 准备数据的链接 |
| `01_preparation/outputs/okvis2.yaml` | 转换后的配置；同目录含标定、掩膜、转换记录和 IMU 支持检查 |
| `01_preparation/diagnostics/camera_models.json` | 每路模型检查的成功／失败像素、投影误差及有效域诊断 |
| `02_reference/inputs/` | 原样导入的 Basalt 轨迹、GT、GT 转换记录和来源 SHA-256 |
| `03_vio/inputs/okvis2.yaml` | 本次实际交给估计器的配置 |
| `03_vio/outputs/okvis2-vio_trajectory.csv` | 估计器原始轨迹 |
| `03_vio/outputs/trajectory_euroc.csv`、`trajectory.tum` | 标准化输出轨迹 |
| `03_vio/outputs/trajectory_summary.json` | 输出帧数、缺帧、首尾覆盖、耗时、峰值 RSS 和特征统计 |
| `03_vio/diagnostics/` | `resource_usage.txt`、`feature_summary.json` |
| `04_vio_comparison/native/`、`common/` | 两种覆盖范围下的 OKVIS／Basalt 指标、轨迹和图表 |
| `04_vio_comparison/summary/summary.json` | 汇总指标、有效时间范围和匹配统计 |
| `report/index.html` | 自包含中文 HTML 报告 |
| `report/mask_overlays/` | 每个 cam 的 PNG 前后掩膜叠加图 |
| `report/report_data.json`、`generation.json` | 结构化报告数据、来源哈希和生成状态 |
| 阶段 `logs/stage.log` | 子进程日志；prepare 模型编译日志位于 diagnostics |

先看 manifest 的 `status` 和 `error`，再看对应阶段日志。模型检查失败读 `camera_models.json`，不能只看 stage.log。`Run complete` 表示所请求阶段完成，不保证精度达标，也不代表已经验证桌面窗口显示。

## 📊 报告与评测口径

- **Native**：各算法自身与 GT 匹配的有效覆盖范围。
- **Common**：双方与 GT 均有效的精确共同时间戳；各自进行 SE(3) 无尺度对齐。
- 输出 APE 平移及 0.1 m、0.5 m、1 m 的距离 RPE。距离配对不足的指标明确标记不可计算；不会伪造零误差。
- 时间偏移使用导入的冻结 GT，不通过拟合 VIO 再调时间。报告同时展示配置差异、覆盖率、资源统计和对齐诊断。
- 掩膜按有效像素比较，消除两套黑白语义反转。有变化时自动展开，无变化时折叠；四张叠加图一行四列。
- 叠加图：黑色保持有效，白色保持排除，绿色新增排除，红色减少排除。每路列出两类变化数量。
- 默认掩膜优先读取 prepare 快照；历史 run 回退读取 Basalt 源文件当前内容，并明确注明来源。缺失或尺寸不同不会伪称一致。

## 🔎 常见问题

| 现象／错误 | 原因与处理 |
| --- | --- |
| `No module named numpy` | Python 环境不对；选择安装了依赖和 evo 的解释器 |
| `--basalt-run and --calibration-dir required` | 新运行缺少输入参数 |
| `Later stages require --from-run` | 单独 vio／compare／report 必须指定 OKVIS run |
| `Reuse takes frozen inputs` | 复用时混入锁定的输入参数；移除覆盖或新开运行 |
| `Unsupported historical OKVIS run` | 不是本入口 version 2 的结果，或误传 Basalt run |
| `Basalt prerequisite incomplete` | Basalt prepare／gt／vio 未完成 |
| `Provide --camera-mask-dir` | Basalt run 没有启用掩膜，须显式提供四张 PNG |
| `Camera model compatibility gate failed` | 查看逐相机诊断，核对标定和有效域；必要时生成专用掩膜后重新 prepare |
| `Delivery camera offset conflicts` | 本次交付与准备数据的时间参考／偏移不一致；核对交付及 Basalt 准备记录，不手动重复平移时间戳 |
| `Insufficient IMU support` | 首尾 IMU 不覆盖修正后的相机时刻及二进制要求的余量；修复上游准备数据 |
| `Prior artifacts changed` / `Referenced input index changed` | 旧阶段产物或索引被修改；恢复原文件或新开运行，不改 manifest 绕过 |
| `No feature evidence from a camera` | 某路没有有效特征证据；检查图像、掩膜和日志 |
| GUI 模式等待不退出 | evo 窗口需逐项关闭；自动批处理省略 `--evo-show-gui` |
| 修改 YAML 后看起来无效 | `--from-run` 使用冻结快照；改算法模板必须新开 prepare／all |

## 🔗 实现依据与相关文档

- [入口](/home/yuewang/Project/VSLAM/four_fisheye_rig/OKVIS2-X/scripts/run_vio_pipeline.py)、[阶段调度与参数](/home/yuewang/Project/VSLAM/four_fisheye_rig/OKVIS2-X/scripts/vio_pipeline_common.py)。
- [Basalt 产物读取](/home/yuewang/Project/VSLAM/four_fisheye_rig/OKVIS2-X/scripts/basalt_run_data.py)、[结果布局](/home/yuewang/Project/VSLAM/four_fisheye_rig/OKVIS2-X/scripts/pipeline_layout.py)。
- [标定转换](/home/yuewang/Project/VSLAM/four_fisheye_rig/OKVIS2-X/scripts/convert_rig_to_okvis.py)、[掩膜生成工具](/home/yuewang/Project/VSLAM/four_fisheye_rig/OKVIS2-X/scripts/make_kb4_domain_masks.py)。
- [轨迹评测](/home/yuewang/Project/VSLAM/four_fisheye_rig/OKVIS2-X/scripts/compare_vio_runs.py)、[报告生成](/home/yuewang/Project/VSLAM/four_fisheye_rig/OKVIS2-X/scripts/generate_pipeline_report.py)。
- [GUI 入口](/home/yuewang/Project/VSLAM/four_fisheye_rig/OKVIS2-X/okvis_apps/src/okvis_app_synchronous.cpp)、[原始分辨率拼接](/home/yuewang/Project/VSLAM/four_fisheye_rig/OKVIS2-X/okvis_apps/src/CameraDisplay.hpp)。

本次文档核对不重新运行 VIO。示例中的历史 run 路径用于说明和复用，读取前需确认目录仍在；新的输入仍须通过完整 prepare 检查。
