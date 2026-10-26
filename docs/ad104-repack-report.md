# AD104 (10de:2783) 重封装技术报告

对象：把「Linux 内核模块 + AD103 Windows UEFI 端口」的逆向成果，重封装成本仓库（`gpu-unlock-ad104`）里**能在这台 RTX 4070 SUPER 上编译、引导、采集、执行**的产物。

---

## 1. 上游图谱与获取方式

```
Zagitta/gpu-unlock                    原始 Linux 内核模块（GA102/CMP 解锁）
        └─ JustAResearcher/gpu-unlock-ada     加 AD102 四-PLM payload、initramfs/DKMS 打包
                                                （即用户给的那份 zip，v1.1.1）
TOTORONG/AD103_win_unlocker           独立的 Windows/UEFI 端口（AD103 4080），
        ├─ source/unlock/*.c/h                自带 UEFI 引导、所有权接管、GOP 复原
        ├─ source/firmware-tools/*            从 NVIDIA 610.43.03 生成 booter/GSP 资产
        └─ USB/RTX4080-EXPERIMENT/ASSETS/     已发布的 64 KB payload
WildFlash1st/cmp90hx-unlock           GA102 V67 链（被上面两者引用）
```

获取障碍与绕法（已记录，可复现）：

| 通道 | 结果 | 处理 |
|---|---|---|
| `git clone https://github.com/...` | `schannel: CRYPT_E_NO_REVOCATION_CHECK (0x80092012)` | 改用 `codeload.github.com/<repo>/zip/refs/heads/main` |
| `api.github.com` | 解析到非公网地址，被拦 | 不需要：直接取 zip |
| Hugging Face | 可直连 | `huggingface.co/<repo>/resolve/main/<path>` 逐文件取 |
| `download.nvidia.com` | 可直连 | 取 610.43.03 源码包（26 MB，sha `7e118923…`） |
| CachyOS 归档 | 可直连 | 取 `nvidia-utils`（314 MB，sha `e17e7c92…`） |
| `ziglang.org` | 可直连，0.14.1 产物名已改为 `zig-x86_64-windows-0.14.1.zip` | sha `554f5378…` 校验通过 |

---

## 2. 事务逆向：它到底动了什么

不是改 OTP、不是打补丁驱动，而是**借已签名固件的特权写**完成一次寄存器授权，再让原版驱动从干净状态初始化。七步（与 `rtx4090-register-report.md` 的状态表一致）：

1. 抢占冷态卡：未绑定驱动、bus mastering 关、WPR2 低、FEAT 权限关闭
2. 在 GSP Falcon 上跑板载 ROM 的签名 **FWSEC-FRTS**，建立固件保留区
3. 在 SEC2 上启动**官方签名 booter**，喂进构造的 V67 签名数据 → 栈槽被覆写、返回经既有认证指令回流，完成 `WPR_CFG → FBPA → WPR → FEAT` 四次受保护写，回写邮箱标记 `0x67b00001` 后 HALT
4. 门禁：标记 + SEC2 HALT + 三个必需权限读回 + PCI/BAR 可访问
5. 主机侧写 `SS0=0x88888888`、`SS1=0x8`，要求九个 effective speed-select 字段归零
6. PCIe FLR，验证 FEAT/selector 保持、WPR2 归零、DMA 收敛
7. 原版驱动加载后复测寄存器与吞吐

关键寄存器（BAR0 相对偏移，非物理地址）：

| 名称 | 偏移 | 冷态 | 事务后 |
|---|---|---|---|
| WPR_CFG PLM | `0x1fa7cc` | `0x0004cb8f` | `0xfffff0ff` |
| FBPA PLM | `0x9a0148` | `0xffffff0f` | 不变（观测项） |
| WPR PLM | `0x1fa7c4` | `0x0004cb8f` | `0xffffffff` |
| FEAT PLM | `0x823804` | `0xffffff8f` | `0xffffffff` |
| SS0 | `0x82381c` | `0x31322012` | `0x88888888` |
| SS1 | `0x823820` | `0x7` | `0x8` |
| effective | `0x823818` | `0x00410080` | `0x0` |
| SEC2 CPUCTL / MAILBOX0 | `0x840100` / `0x840040` | — | `0x10`（HALT）/ `0x67b00001` |

---

## 3. payload 逆向：它是数据，不是代码

`v67-ad102-610.43.03-four-plm.bin` 是 64 000 B（`0xfa00`）的**纯数据**：整幅填充 `0x0000019c`，只在 `0x1100` 与 `0xf948…0xf9fc` 打补丁。

`analysis/gen_payload.py` 按结构独立重写，**与发布件字节完全一致**（`sha256 44c36b2d…`），说明构造已被掌握：

| 偏移 | dword | 作用 |
|---|---|---|
| `0x1100` | `0x00000007` | 继承的 `D[0x1700]=7` 语义位 |
| `0xf948` | `0xfffff0ff` | WPR_CFG 目标值 |
| `0xf960` | `0x001fa7cc` | WPR_CFG 目标地址 |
| `0xf984` | `0x009a0148` | FBPA 地址 |
| `0xf9a8` | `0x001fa7c4` | WPR 地址 |
| `0xf9cc` | `0x00823804` | FEAT 地址 |
| `0xf9e0` | `0x67b00001` | 邮箱标记 |
| `0xf950 / 0xf968 / 0xf97c` 等 | `0x21b2 / 0x33fc / 0x256f` | gadget 入口：参数装载、返回尾、BAR 写助手 |
| `0xf9ec / 0xf9f8 / 0xf9fc` | `0x7a02 / 0x31b5 / 0x771e` | 清理尾：SP 装载、状态写、exit |

重要细节：`0xf94c/0xf950` 是**文件偏移**，对应 DMEM `0xff4c/0xff50`（拷贝基址 `0x600`）。把文件偏移当 DMEM 地址会误判栈布局。

---

## 4. 供体 UEFI 的门禁布局（硬编码在哪）

供体（AD103 4080）把全部硬件事实写成常量，散落在 5 个文件、13 处：

| 位置 | 硬编码 | 含义 |
|---|---|---|
| `port.h:8-10` | `0x270410de / 0x179510de / 0x193000a1` | device / subsystem / chip |
| `port.c:GuTargetConfig` | `B==1 && !D && !F` | BDF 固定 `0000:01:00.0` |
| `checks.c:GuCheckConfig` | `Segment==0 && Bus==1 …` | 同上 |
| `app.c:ConfigCheck` | `config[2]==0x030000a1`、`config[0xc8/4]==0x00050011`、`config[0x10/4]==0x80000000` | class+revision、MSI-X cap 落在 0xc8、BAR0 固定基址 |
| `app.c:BarCheck` | `0x80000000` / `0x1000000` / `0x80ffffff` | BAR0 地址、长度、结束值 |
| `app.c:ColdCheck` | `chip!=GU_BOARD_CHIP`、`plm!=0xffffff8f`、`(ss0&0x88888888)`、`ss1!=7`、`vram∈{0x7ff8,0x8000}` | 冷态闸门 |
| `app.c:PromCheck` | `RomSize!=0x24c00`、固定 ROM/PROM 哈希 | 固件同一性 |
| `app_io.c` | `\RTX4080-EXPERIMENT`、5 个资产名/大小/哈希 | 目录与资产 |

---

## 5. 我们的改动（`port/patch.py`，13 处替换 + 6 个新文件）

新文件：

- `board_profile.h` —— 全部指纹集中到宏；`0`/`""` 表示"关闭该闸门并记录观测值"；末尾用 `__has_include` 吸收生成的钉死头
- `diag.c/.h` —— 只读采集模式（PCI 枚举 → 身份 → BAR → 21 个寄存器 → ROM/PROM 候选偏移哈希 → `PROFILE.TXT`）
- `compat/linux/printk.h`、`compat/linux/errno.h` —— 公开包缺这两个内核头，补最小 shim
- `port/build.py`、`port/patch.py`

替换要点：

| 文件 | 改动 |
|---|---|
| `port.h` | 3 个硬编码 → `#include "board_profile.h"` |
| `prom_profile.h` | 重写为转发（PROM 视图几何来自 profile） |
| `port.c` / `checks.c` | 删除 `bus==1/dev==0/func==0` 固定 BDF，改为"唯一匹配 + identity 对"（UEFI 分配的总线号不可预知） |
| `app.c:ConfigCheck` | class 用 `(config[2]&0xffffff00)==0x030000`；revision 可关；删掉固定 `0xc8` 的 MSI-X 断言（`GuCheckConfig` 已解析 caps）；BAR0 地址可关 |
| `app.c:BarCheck` | 地址 / 长度 / 结束值三项条件化（`GU_BAR0_ADDR`/`GU_BAR0_SIZE` 为 0 即跳过） |
| `app.c:ColdCheck` | chip、FEAT PLM、SS0 掩码、SS1、VRAM 五项条件化 |
| `app.c:PromCheck` | ROM 大小/哈希、PROM 视图哈希条件化 |
| `app.c:EfiMain` | 新增 `#if GU_DIAG_MODE` 早返分支：secure-boot 之后直接跑采集，**不 claim 控制器、不加载资产、不写 MMIO**；`attempted` 变量提升以共享收尾路径 |
| `app_io.c` | 目录名 → `GU_RUN_DIR_W`；新增 `GuSaveText()` 写 `PROFILE.TXT` |

设计原则：**闸门值来自真实采集，而不是猜**。默认（未采集）状态只记录不阻断，仅用于 diag 与验证编译；一旦 `profile_to_header.py` 生成钉死头，13 处闸门全部生效，换卡/换 VBIOS/换 PROM 一律拒绝。

---

## 6. 构建链与产物校验

工具链：Zig `0.14.1`（`zig cc -target x86_64-uefi`，自带 clang+lld，无需 MSVC/MinGW）。

```
ffreestanding, -fno-builtin, -fno-stack-protector, -mno-red-zone,
-fshort-wchar, -Os, -Wall -Wextra -Werror, -nostdlib
```

产物（PE 头已独立校验：`MZ`、`PE\0\0`、machine `0x8664`、magic `0x20b`、subsystem `10` = `EFI_APPLICATION`、`nRVA=16`）：

| 模式 | 大小 | sha256 | 说明 |
|---|---:|---|---|
| diag | 71 168 B | `7b82d7f11a86ee5f3f26226e0fdf1ce86af52b665adeda6402208599e2903e4f` | 只读采集 |
| unlock（默认宽门禁） | 83 456 B | `056cd349334dad3ed6279dfd220801b440888efd536dae2451546789f9dee45d` | 结构验证用 |
| unlock（钉死 AD103 样例） | 84 480 B | `8457ab957371a9946745e273c5265655070e8b23a09be951452ea2f57ab236ba` | 验证 profile 注入链路 |

> 钉死样例用的是 AD103 4080 的公开观测值（`analysis/fixtures/PROFILE-AD103-SAMPLE.txt`），只用来证明"采集 → 生成头 → 编译"闭环可用，**不是本机数据**。本机 unlock 构建必须在 diag 跑完后再生成。

---

## 7. 资产

全部在本地从钉死的 NVIDIA 610.43.03 输入生成，哈希逐个核对：

| 资产 | 大小 | 来源 | 校验 |
|---|---:|---|---|
| `booter_load_ad102.bin` | 57 672 | `open-gpu-kernel-modules` 源码 `g_bindata` | `6ee05b20…` ✓ |
| `gsp_boot_ad102.bin` | 36 864 | 同上 | `45d6335a…` ✓ |
| `gsp_boot_desc_ad102.bin` | 84 | 同上 | `83f8f3f1…` ✓ |
| `gsp_ga10x.bin` | 84 277 400 | `nvidia-utils-610.43.03` 包内 `usr/lib/firmware/…` | `572373620…` ✓ |
| `v67-ad102-610.43.03-four-plm.bin` | 64 000 | 供体发布件 + 本地独立复现 | `44c36b2d…` ✓ |

工具差异：上游 `generate_v67.py` 依赖外部 `zstd.exe`（本机没有，`FileNotFoundError`）。本工程用 Python 3.14 的 `compression.zstd` 走 `tarfile.open(..., "r:zst")` 流式提取（`tools/extract_gsp.py`），不落 800 MB 中间解包。

---

## 8. 未验证项（必须按此设预期）

1. `10de:2783` 的事务从未在任何硬件上跑过；AD104 的已证对象是 `10de:2782`（另一个 UEFI 端口，cuBLAS FP16 +80.1%）与 AD102 4090。
2. payload gadget 地址来自 AD102 调试 booter 分析。AD102-family 共享 booter 归档**不等于**各芯片指令边界相同；`0x21b2 / 0x33fc / 0x256f / 0x31b5 / 0x771e` 在 AD104 production booter 上是否落在同一 gadget 未验证。
3. 冷态期望值（PLM `0xffffff8f`、SS0 `0x31322012`、SS1 `0x7`、VRAM 编码）在 4070 SUPER 上未知——这正是 diag 模式存在的理由。
4. 未做 UEFI 环境模拟测试（供体自带模拟测试依赖其私有 ROM/PROM 转储，公开包已剔除）。
5. 未验证数值正确性之外的长期稳定性、功耗与多卡场景。
6. 采集模式未在真机 UEFI 跑过（本机 Secure Boot 状态为 unknown，需人工关闭后引导）。

失败语义：门不通过 → 记录 `CHECK stage=… status=…` 并停；事务中途异常 → `STOP: cleanup cannot be proven`，保留 DMA、拒绝重跑，必须断电。这是刻意设计，不要改成"失败继续"。
