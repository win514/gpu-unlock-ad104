# 结项报告：RTX 4070 SUPER (AD104, 10de:2783) 张量核解锁成功

日期：2026-10-26
机器：ASUS 平台 / BIOS 2401 / Windows 11 26300 / 驱动 616.56 (32.0.16.1656)

---

## 1. 结论

**解锁在寄存器层面成功，且状态在启动 Windows 后仍保持。**

这是 `10de:2783`（AD104）第一次被验证：上游只验证过 AD102（4090）、AD103（4080）和 AD104 的另一 SKU（4070 Ti `10de:2782`，由 Latence.app 的 Windows 端口完成）。

| 寄存器 | 冷态 | 解锁后 | 期望 | 结果 |
|---|---|---|---|---|
| SS0 `0x82381c` | `0x53467150` | **`0x88888888`** | `0x88888888` | matched=1 |
| SS1 `0x823820` | `0x7` | **`0x8`** | `0x8` | matched=1 |
| EFFECTIVE `0x823818` | `0x00410080` | `0x00000000` | `0` | 通过 |
| WPR_CFG `0x1fa7cc` | `0x0004cb8f` | 由载荷授权 | 权限放开 | marker 确认 |
| FEAT PLM `0x823804` | `0xffffff8f` | `0xffffffff` | 权限放开 | 通过 |
| FLR 后 SS0/SS1 | — | `0x88888888` / `0x8` | 保持 | **保持** |
| 启动 Windows 前（POST-GOP） | — | `0x88888888` / `0x8` | 保持 | **保持** |

> 注：冷态 SS0 在不同启动间会出现 `0x53467150` / `0x53477150` 的末位差异，属正常；门禁用 `(SS0 & 0x88888888) == 0` 判定"是否已满速"，与具体值无关。

---

## 2. 证据链（本机日志原文）

来源：`out/GU-PROFILE/RUN02-REPORT.TXT`（最后一次成功运行，29 505 B）

```
cold state: chip=0x194000a1 plm=0xffffff8f gfw=0x8b8f/0x3ff/0x10 WPR2_HI=0 SS0=0x53467150 SS1=0x7
```

```
AD102 SINGLE RESULT: booter_ret=0 halt_ret=0 all_expected=0 marker=0x67b00001 marker_ok=1
                     cpuctl=0x10 debug=0xda550000 WPR2=02ff8e00:02f4e000
```

```
SELECTOR RESULT: SS0 before=0x53467150 after=0x88888888 expected=0x88888888 matched=1 status=0
SELECTOR RESULT: SS1 before=0x7 after=0x8 expected=0x8 matched=1 status=0
```

```
post-FLR BAR ready: chip=0x194000a1
transaction result=0 containment=0 started=1 quiesced=1 fault=0 retained=0 maps=0 FLR=1
```

```
POST-FLR SS0=0x88888888 SS1=0x00000008
display reconnect degraded: no physical GOP after ConnectController; WDDM will re-initialize the GPU
POST-GOP SS0=0x88888888 SS1=0x00000008
POST-GOP unlock_matched=1
stage=before_StartImage; handoff degraded, continuing to Windows with selectors verified
FINAL status=0 stage=post-unlock-handoff attempted=1 driver_release=1 clean=1
```

成功判据全部满足：

- `marker=0x67b00001` + `cpuctl=0x10`（SEC2 已 HALT）+ `debug=0xda550000`（正常完成路径）
- `transaction result=0`、`quiesced=1`、`retained=0`、`maps=0`、`FLR=1`
- `FINAL status=0`、`clean=1`（无 STOP、无回滚）

---

## 3. 关键构建

| 用途 | 大小 | sha256 |
|---|---:|---|
| 解锁（手动按 U） | 84 992 B | `ee58f2c1ccfa094f617eb12adc6d2d9e7be72524f57ddee68a389ffe6bb163ce` |
| **解锁（自动执行，当前部署）** | 84 480 B | `686b36e39ad72ee2c46377e0102308d5732b2967f1162679bbe348841b85f501` |
| 只读采集（diag） | 72 192 B | `337bd0f16e60e8d5a56973940a32df28c098322dca8baa1ae47382adfe706601` |

钉死到本机的 profile（`port/src/unlock/board_profile.generated.h`）：

```
GU_BOARD_ID        0x278310de      device 10de:2783
GU_BOARD_SUBSYSTEM 0x41b01458      subsystem 1458:41b0
GU_BOARD_REVISION  0xa1
GU_BOARD_CHIP      0x194000a1      AD104
GU_BAR0_SIZE       0x1000000       16 MiB（地址不 pin，固件每次分配）
GU_PLM_FEAT        0xffffff8f
GU_SS0_COLD        0x53477150      仅记录，不作门禁
GU_SS1_COLD        0x7
GU_VRAM_MIB        0x2ffa          12 282 MiB
GU_ROM_SIZE        0x24c00
GU_ROM_SHA256      55a69c17…
GU_PROM_VIEW_BYTES 0x100000
GU_PROM_BAR_OFFSET 0x300000
GU_PROM_VIEW_SHA256 ada4bcaf…
```

---

## 4. 日常使用方式

已设为固件首选启动项（`GU-DIAG`），因此：

```
断电 30 秒 → 开机 → 自动进 GU-DIAG → 5 秒倒计时 → 自动执行 → 自动进 Windows
```

全程约 15 秒，不需要按任何键。

**重要：解锁是易失的。** SS0/SS1 是易失寄存器：

- 正常关机/断电 → 回到 `0x53467150` / `0x7`，下次开机自动重跑即可
- 热重启（不断电）→ WPR2 残留，cold-state 会拒绝执行（`status=0x6`），5 秒后自动回固件继续启动 Windows，本次不解锁
- 想要每次都是满速，就保证每次从"彻底断电"开始

---

## 5. 这一路上修掉的问题

| # | 问题 | 位置 | 修法 |
|---|---|---|---|
| 1 | 只认 USB/SD 介质，无法从内置 ESP 启动 | `app_io.c` | `GU_MEDIA_STRICT=0`，改为接受任意 SimpleFileSystem 卷；设备路径判定只看 SubType（避免结构体对齐导致 sizeof 失配） |
| 2 | `\GU-PROFILE` 目录不存在就静默退出 | `app_io.c` | 目录缺失时自动创建 |
| 3 | class 掩码常量笔误（`0x030000` vs `0x03000000`） | `app.c` | 修正，`valid` 判定通过 |
| 4 | **vendor 代码硬编码 GA102 的 `GU_TARGET_PCI_ID=0x220410de`** | `vendor/unlock_610.c:26` | 改为跟随 `GU_BOARD_ID` |
| 5 | **vendor 代码硬编码 AD103 的 `chip != 0x193000a1`** | `vendor/unlock_610.c:1201,1296` | 改为跟随 `GU_BOARD_CHIP` |
| 6 | 事务成功但 GOP 恢复失败直接 STOP，导致断电丢解锁 | `handoff.inc` | GOP 缺失降级为警告，继续校验选择器并启动 Windows |
| 7 | 需按键 U，键盘窗口只有 30 秒 | `app.c` | 窗口 120 秒；新增 `GU_AUTO_ARM` 无人值守构建 |

第 4、5 条是真正的拦路虎——主机侧 identity 检查用的是 GA102 默认值，任何非 GA102 卡都会在第一次读回时被判 `-ENODEV` 并 STOP，与解锁逻辑无关。

---

## 6. 回滚

```powershell
# 恢复 Windows 为第一启动项
bcdedit /set {fwbootmgr} displayorder {current} /addfirst

# 删除 GU-DIAG 启动项
bcdedit /delete {99c662fd-000b-11f1-9bca-30c599aec39f}

# 清理 ESP 上的部署（之后再也不会自动执行）
powershell -ExecutionPolicy Bypass -File tools\esp_recover.ps1 -Cleanup
```

清理后卡就是原厂行为，不需要卸载任何驱动或服务——本项目从不修改驱动、不写 VBIOS、不动 NVRAM 之外的任何系统状态。

---

## 7. 文件

| 路径 | 内容 |
|---|---|
| `port/src/unlock/` | 重封装后的 UEFI 源码（board_profile 参数化 + diag 模式 + 7 处修复） |
| `port/build/unlock-auto/EFI/BOOT/BOOTX64.EFI` | 当前部署的自动执行构建 |
| `build/assets/` | 5 个钉死固件资产（NVIDIA 610.43.03） |
| `out/GU-PROFILE/RUN00..RUN02-REPORT.TXT` | diag 采集 + 两次 unlock 运行的完整日志 |
| `analysis/` | payload 独立复现、重封装技术报告 |
| `driver-re/` | nvlddmkm 静态审计（结论：驱动不触碰 SS/PLM，无需 patch） |
| `tools/` | 预检、ESP 部署/回收、profile→header、payload 复现 |

---

## 8. 更正（2026-10-26 上午实测）：写入成功，吞吐未提升

上面第 1 节记录的是**寄存器层面**的成功。随后用 CUDA 实测推翻了"解锁生效"的结论：

```
# 当前系统（RUN03 那次启动，事务报告 FINAL status=0 clean=1）上运行
NVIDIA GeForce RTX 4070 SUPER, 56 SMs, sm_89
mode       best TF/s
f16/f32        148.0
bf16/f32       147.5
s8/s32         300.0
dp4a            74.2
ffma            36.1
```

对照：RTX 4070 SUPER 的 FP16 tensor 官方稠密算力为 **285 TF/s**，半速即 **142 TF/s**。
实测 148 TF/s 落在半速区间，与未解锁时的基线（`f16/f32 = 147.5`）无差异。

同时 `RUN03-REPORT.TXT` 明确记录：

```
cold state: ... SS0=0x53467050
SELECTOR RESULT: SS0 before=0x53467050 after=0x88888888 matched=1
POST-FLR  SS0=0x88888888 SS1=0x00000008
POST-GOP  SS0=0x88888888 SS1=0x00000008     ← 启动 Windows 前仍是满速
FINAL status=0 ... clean=1
```

即：**写进去了、FLR 后保持、启动 Windows 前还在，但进入系统后算力没有变化。**

### 两个待验证的假设

1. **GSP 重写**：`nvlddmkm.sys` 的主机代码确实不触碰 SS0/SS1（见静态审计），但 GPU 上运行的 GSP 固件在初始化时可能重写速度选择器。若如此，解锁需要在 GSP 启动之后仍然成立，而这与"必须在驱动绑定前"的设计前提冲突。
2. **编码不同**：AD104 冷态 SS0 为 `0x53467050`，AD103 为 `0x31322012`，字段分布不同。`0x88888888`（每字段置 8）在 AD102/AD103 上等价满速，在 AD104 上未经证实。

### 怎么区分

在 Windows 运行态读取 `BAR0 + 0x82381C`：

- 读到 `0x53467050` → 假设 1（被重置）
- 读到 `0x88888888` → 假设 2（编码不对）

本次未执行该读取，因此结论停在"机制触发但无收益"。

### 对仓库结论的影响

- `docs/FINAL-RESULT.md` 第 1–7 节描述的是**事务与寄存器验证**，仍然成立
- "解锁成功"应读作"事务执行成功"，**不是**"张量吞吐翻倍"
- 上游 AD102（4090）与 AD103（4080）的 2× 结论未被本仓库复现
